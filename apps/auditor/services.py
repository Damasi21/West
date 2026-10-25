import hashlib
import json
import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.db import transaction
from django.db.models import Max, Q, Subquery
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.empresas.models import CadastroOmie, ContaPagarOmie, ContaReceberOmie, Empresa, SincronizacaoOmie
from .catalogo import PARAMETROS, REGRAS, VERSAO_REGRAS
from .models import (
    CasoAuditoria, EvidenciaAuditoria, EventoAuditoria, ExecucaoAuditoria,
    PoliticaAuditoria, VersaoRegistroAuditoria,
)

logger = logging.getLogger(__name__)


def assinatura(dados):
    return hashlib.sha256(json.dumps(dados, sort_keys=True, default=str).encode()).hexdigest()


def _segredo(dados):
    return salted_hmac("auditor.registro", json.dumps(dados, sort_keys=True, default=str), algorithm="sha256").hexdigest()


def _mascarar(valor):
    if isinstance(valor, dict):
        return {k: _mascarar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_mascarar(v) for v in valor]
    texto = str(valor or "")
    return "***" + texto[-4:] if len(texto) > 4 else "***" if texto else ""


def politicas_empresa(empresa):
    for codigo, regra in REGRAS.items():
        PoliticaAuditoria.objects.get_or_create(
            empresa=empresa, codigo=codigo,
            defaults={"severidade": regra["severidade"], "parametros": PARAMETROS.copy()},
        )
    return PoliticaAuditoria.objects.filter(empresa=empresa, codigo__in=REGRAS).order_by("codigo")


def solicitar_execucao(empresa, usuario):
    with transaction.atomic():
        Empresa.objects.select_for_update().get(pk=empresa.pk)
        existente = ExecucaoAuditoria.objects.filter(empresa=empresa, status__in=["fila", "executando"]).first()
        if existente:
            return existente, False
        execucao = ExecucaoAuditoria.objects.create(empresa=empresa, solicitada_por=usuario)
    return execucao, True


def fontes_empresa(empresa):
    fontes = []
    for codigo, nome, modelo in (
        ("cadastros", "Cadastros", CadastroOmie),
        ("pagar", "Contas a pagar", ContaPagarOmie),
        ("receber", "Contas a receber", ContaReceberOmie),
    ):
        qs = modelo.objects.filter(empresa=empresa, ativo_omie=True)
        ultima = qs.aggregate(ultima=Max("sincronizado_em"))["ultima"]
        fontes.append({
            "codigo": codigo, "nome": nome, "registros": qs.count(),
            "atualizada_em": ultima.isoformat() if ultima else "",
            "atualizacao_label": timezone.localtime(ultima).strftime("%d/%m/%Y %H:%M") if ultima else "Sem captura",
            "situacao": "Sem dados" if not ultima else "Desatualizada" if ultima < timezone.now() - timedelta(days=2) else "Disponivel",
        })
    return fontes


def _capturar(execucao, entidade, codigo, dados, anteriores):
    chave = (entidade, codigo)
    anterior = anteriores.get(chave)
    digest = assinatura(dados)
    if anterior is None or anterior.assinatura != digest:
        nova = VersaoRegistroAuditoria.objects.create(
            empresa_id=execucao.empresa_id, execucao=execucao, entidade=entidade, codigo=codigo,
            versao=anterior.versao + 1 if anterior else 1, assinatura=digest, dados=dados,
        )
        anteriores[chave] = nova
    return anterior


def _evidencia_titulo(titulo, natureza):
    parceiro = titulo.fornecedor if natureza == "pagar" else titulo.cliente
    return {
        "origem": natureza, "codigo": titulo.codigo_lancamento_omie,
        "parceiro": titulo.codigo_cliente_fornecedor,
        "nome_parceiro": (parceiro.razao_social or parceiro.nome_fantasia) if parceiro else "",
        "documento": titulo.numero_documento_fiscal or titulo.numero_documento,
        "parcela": titulo.numero_parcela, "valor_original": str(titulo.valor_documento),
        "emissao": str(titulo.data_emissao or ""), "vencimento": str(titulo.data_vencimento or ""),
        "categoria": titulo.codigo_categoria, "status_origem": titulo.status_titulo,
    }


def _detectar(execucao, politicas, anteriores):
    achados = []
    cobertura = {codigo: {"avaliados": 0, "sem_base": 0} for codigo in politicas}

    def registrar(regra, chave, titulo, evidencia):
        if regra not in politicas:
            return
        achados.append((regra, assinatura([regra, chave]), titulo[:200], evidencia))

    cadastros = CadastroOmie.objects.filter(empresa_id=execucao.empresa_id).order_by("pk")
    for c in cadastros.iterator():
        dados = {
            "nome": c.razao_social or c.nome_fantasia, "documento": _mascarar(c.cnpj_cpf),
            "documento_assinatura": _segredo(c.cnpj_cpf), "ativo": c.ativo_omie and not c.inativo,
            "banco": _mascarar(c.dados_bancarios), "banco_assinatura": _segredo(c.dados_bancarios),
        }
        anterior = _capturar(execucao, "cadastro", c.codigo_cliente_omie, dados, anteriores)
        if not dados["ativo"] or c.tipo not in ["fornecedor", "ambos"]:
            continue
        faltantes = []
        if not dados["nome"].strip():
            faltantes.append("Nome")
        if not c.exterior and not c.cnpj_cpf.strip():
            faltantes.append("CPF/CNPJ")
        if "cadastro_incompleto" in politicas:
            cobertura["cadastro_incompleto"]["avaliados"] += 1
        if faltantes:
            registrar("cadastro_incompleto", c.codigo_cliente_omie,
                      f"Cadastro incompleto: {dados['nome'] or c.codigo_cliente_omie}",
                      {"codigo": c.codigo_cliente_omie, "campos_ausentes": faltantes,
                       "limite": "Nao verifica validade fiscal ou situacao cadastral na Receita."})
        if "alteracao_bancaria" in politicas:
            cobertura["alteracao_bancaria"]["avaliados" if anterior else "sem_base"] += 1
        if anterior and anterior.dados.get("banco_assinatura") != dados["banco_assinatura"]:
            registrar("alteracao_bancaria", [c.codigo_cliente_omie, dados["banco_assinatura"]],
                      f"Alteracao bancaria: {dados['nome'] or c.codigo_cliente_omie}",
                      {"codigo": c.codigo_cliente_omie, "anterior": anterior.dados.get("banco"),
                       "atual": dados["banco"], "captura_anterior": anterior.observada_em.isoformat(),
                       "captura_atual": timezone.now().isoformat(), "autor_na_origem": "Nao disponivel",
                       "limite": "Mudanca observada entre capturas; horario exato e beneficiario pago nao confirmados."})

    for natureza, modelo in (("pagar", ContaPagarOmie), ("receber", ContaReceberOmie)):
        grupos = defaultdict(list)
        historicos = defaultdict(list)
        titulos = list(modelo.objects.filter(empresa_id=execucao.empresa_id).select_related(
            "fornecedor" if natureza == "pagar" else "cliente").order_by("pk"))
        for t in titulos:
            dado = _evidencia_titulo(t, natureza)
            dado["ativo"] = t.ativo_omie
            _capturar(execucao, natureza, t.codigo_lancamento_omie, dado, anteriores)
        ativos = [t for t in titulos if t.ativo_omie and t.status_titulo.strip().upper() != "CANCELADO"]
        for t in ativos:
            doc = "".join(c for c in (t.numero_documento_fiscal or t.numero_documento).upper() if c.isalnum())
            if "titulo_duplicado" in politicas:
                cobertura["titulo_duplicado"]["avaliados" if doc and t.codigo_cliente_fornecedor and t.data_vencimento else "sem_base"] += 1
            if doc and t.codigo_cliente_fornecedor and t.data_vencimento and t.valor_documento > 0:
                chave = (t.codigo_cliente_fornecedor, doc, t.numero_parcela.strip(), str(t.valor_documento), str(t.data_vencimento))
                grupos[chave].append(t)
        for chave, iguais in grupos.items():
            if len(iguais) > 1:
                registrar("titulo_duplicado", [natureza, chave], f"Possivel duplicidade a {natureza}: documento {chave[1]}",
                          {"correspondencia": "Provavel", "titulos": [_evidencia_titulo(t, natureza) for t in iguais],
                           "limite": "Serie e documento original exigem conferencia; parcelas nao sao somadas como duplicidade."})

        for t in sorted(ativos, key=lambda x: (x.data_emissao or timezone.localdate(), x.pk)):
            for codigo in ("valor_atipico", "categoria_atipica"):
                if codigo not in politicas:
                    continue
                p = politicas[codigo].parametros
                janela = int(p.get("janela_dias", 365))
                minimo = int(p.get("amostras_minimas", 6))
                base = [h for h in historicos[t.codigo_cliente_fornecedor]
                        if t.data_emissao and h.data_emissao < t.data_emissao
                        and h.data_emissao >= t.data_emissao - timedelta(days=janela)]
                if not t.codigo_cliente_fornecedor or not t.data_emissao or len(base) < minimo:
                    cobertura[codigo]["sem_base"] += 1
                    continue
                cobertura[codigo]["avaliados"] += 1
                referencia = {"amostras": len(base), "janela_dias": janela,
                              "data_limite_exclusiva": t.data_emissao.isoformat(),
                              "limite": "Sinal historico; sazonalidade, quantidade e mudanca de escopo ainda exigem analise."}
                if codigo == "valor_atipico":
                    valores = [h.valor_documento for h in base]
                    mediana = median(valores)
                    mad = median([abs(v - mediana) for v in valores])
                    limite = max(mediana * Decimal(str(p.get("multiplicador_valor", 3))), mediana + 3 * mad)
                    if mediana > 0 and t.valor_documento > limite:
                        registrar(codigo, [natureza, t.codigo_lancamento_omie], f"Valor atipico a {natureza}: {t.numero_documento or t.codigo_lancamento_omie}",
                                  {"titulo": _evidencia_titulo(t, natureza), "referencia": referencia,
                                   "mediana": str(mediana), "desvio_absoluto_mediano": str(mad), "limite": str(limite)})
                else:
                    categorias = [h.codigo_categoria for h in base if h.codigo_categoria]
                    if len(categorias) < minimo or not t.codigo_categoria:
                        cobertura[codigo]["avaliados"] -= 1
                        cobertura[codigo]["sem_base"] += 1
                        continue
                    dominante = max(set(categorias), key=categorias.count)
                    if t.codigo_categoria not in categorias and categorias.count(dominante) / len(categorias) >= .8:
                        registrar(codigo, [natureza, t.codigo_lancamento_omie], f"Categoria incomum a {natureza}: {t.numero_documento or t.codigo_lancamento_omie}",
                                  {"titulo": _evidencia_titulo(t, natureza), "referencia": referencia,
                                   "categoria_habitual": dominante, "ocorrencias_habituais": categorias.count(dominante)})
            if t.codigo_cliente_fornecedor and t.data_emissao and t.valor_documento > 0:
                historicos[t.codigo_cliente_fornecedor].append(t)
    return achados, dict(cobertura)


def executar_auditoria(execucao_id):
    with transaction.atomic():
        execucao = ExecucaoAuditoria.objects.select_for_update().select_related("empresa").get(pk=execucao_id)
        if execucao.status != "fila":
            return
        execucao.status = "executando"
        execucao.iniciada_em = timezone.now()
        execucao.save(update_fields=["status", "iniciada_em"])
    try:
        with transaction.atomic():
            todas_politicas = list(politicas_empresa(execucao.empresa))
            politicas = {p.codigo: p for p in todas_politicas if p.ativa}
            execucao.politicas = [{"codigo": p.codigo, "ativa": p.ativa, "severidade": p.severidade,
                                  "parametros": p.parametros, "versao": VERSAO_REGRAS} for p in todas_politicas]
            execucao.fontes = fontes_empresa(execucao.empresa)
            anteriores = {}
            ultimas = VersaoRegistroAuditoria.objects.filter(empresa=execucao.empresa).order_by().values("entidade", "codigo").annotate(ultima=Max("pk")).values("ultima")
            for registro in VersaoRegistroAuditoria.objects.filter(pk__in=Subquery(ultimas)).iterator():
                anteriores[(registro.entidade, registro.codigo)] = registro
            achados, cobertura = _detectar(execucao, politicas, anteriores)
            novos = 0
            for codigo, identidade, titulo, dados in achados:
                regra = REGRAS[codigo]
                caso, criado = CasoAuditoria.objects.get_or_create(
                    empresa=execucao.empresa, identidade=identidade,
                    defaults={"regra": codigo, "titulo": titulo, "severidade": politicas[codigo].severidade,
                              "recomendacao": regra["recomendacao"], "ultima_deteccao": timezone.now(), "ultima_execucao": execucao},
                )
                if not criado:
                    # Human treatment is preserved when the same signal is observed again.
                    CasoAuditoria.objects.filter(pk=caso.pk).update(ultima_deteccao=timezone.now(), ultima_execucao=execucao,
                                                                   severidade=politicas[codigo].severidade)
                novos += int(criado)
                EvidenciaAuditoria.objects.create(caso=caso, execucao=execucao,
                    dados={"regra": codigo, "versao": VERSAO_REGRAS, "politica": politicas[codigo].parametros,
                           "severidade_detectada": politicas[codigo].severidade, "evidencia": dados})
            execucao.resumo = {"novos": novos, "sinais": len(achados), "cobertura": cobertura,
                               "sincronizacao_em_andamento": SincronizacaoOmie.objects.filter(empresa=execucao.empresa).filter(
                                   Q(status="em_andamento") | Q(finalizada_em__gte=execucao.iniciada_em)).exists(),
                               "limites": ["Extrato bancario independente nao integrado.", "Recebimento fisico e segregacao de funcoes nao avaliados.",
                                           "Sem alertas nao significa ausencia de inconsistencias.", "Historico preservado a partir das capturas do Auditor."]}
            execucao.status = "concluida"
            execucao.finalizada_em = timezone.now()
            execucao.save()
    except Exception:
        logger.exception("Falha na auditoria %s", execucao_id)
        ExecucaoAuditoria.objects.filter(pk=execucao_id).update(
            status="erro", finalizada_em=timezone.now(), erro="Nao foi possivel concluir a analise. Consulte os logs do worker e tente novamente.",
        )
        raise
