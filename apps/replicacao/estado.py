"""Inativação/reativação explícita de categorias filhas existentes, sem inclusões."""
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import CategoriaOmie
from apps.empresas.omie import _salvar_categorias
from . import omie
from .comparacao import dados, normalizar, semelhanca, tipo, sem_observacoes
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa, VinculoCategoria
from .services import aplicativo_livre, atualizar_catalogo, identificar_aplicativos, auditar

MODOS = {"inativar", "reativar"}


def snapshot(categoria):
    return {**dados(categoria), "codigo_dre": categoria.codigo_dre}


def identidade(registro):
    return {k: v for k, v in registro.items() if k not in {"conta_inativa", "natureza"}}


def validar_categoria(categoria):
    if not categoria.ativo_omie or categoria.totalizadora or categoria.transferencia or not tipo(dados(categoria)):
        raise ValidationError("Selecione uma categoria filha de receita ou despesa presente no OMIE. Grupos pais e transferências não são alterados por esta rotina.")


def solicitar(plano, usuario, categoria, modo, empresas_ids):
    from .central import conferir_empresas, OCUPADOS
    if modo not in MODOS:
        raise ValidationError("Escolha Inativar ou Reativar.")
    if not isinstance(empresas_ids, list) or not empresas_ids or any(type(pk) is not int for pk in empresas_ids) or len(set(empresas_ids)) != len(empresas_ids):
        raise ValidationError("Selecione ao menos uma empresa do grupo, sem repetições.")
    with transaction.atomic():
        plano = PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        empresas = conferir_empresas(plano, usuario)
        if not set(empresas_ids).issubset({e.pk for e in empresas}):
            raise PermissionDenied("A seleção contém empresa de fora da configuração.")
        if plano.cadastros.filter(status__in=OCUPADOS | {"revisao"}).exists() or plano.comparacoes.filter(status__in=["fila", "comparando", "enviando"]).exists():
            raise ValidationError("Conclua a solicitação em andamento antes de iniciar outra.")
        categoria = CategoriaOmie.objects.get(pk=categoria.pk, empresa_id=plano.matriz_id)
        validar_categoria(categoria)
        pai = CategoriaOmie.objects.filter(empresa_id=plano.matriz_id, codigo=categoria.categoria_superior, ativo_omie=True, totalizadora=True, transferencia=False).first()
        if not pai:
            raise ValidationError("O grupo superior da categoria não está disponível. Atualize a árvore.")
        op = CadastroCategoria.objects.create(plano=plano, solicitado_por=usuario, modo=modo,
            pedido={"etapa": "consulta", "descricao": categoria.descricao, "origem_id": categoria.pk,
                "origem": snapshot(categoria), "pai": snapshot(pai)},
            aplicativos=identificar_aplicativos(plano), progresso_total=len(empresas_ids)*2,
            mensagem="Aguardando o worker para localizar as categorias. Nenhuma alteração foi autorizada ainda.")
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op, empresa=e) for e in empresas if e.pk in empresas_ids])
        auditar(plano, usuario, "Solicitou prévia de situação de categoria", cadastro_id=op.pk, modo=modo, categoria_id=categoria.pk, empresas=empresas_ids)
        return op


def catalogo(empresa, integracao):
    return [snapshot(c) for c in atualizar_catalogo(empresa, integracao)]


def pai_destino(op, empresa, categorias):
    origem = op.pedido["pai"]
    if empresa.pk == op.plano.matriz_id:
        return next((c for c in categorias if c["codigo"] == origem["codigo"] and identidade(c) == identidade(origem)), None)
    vinculo = VinculoCategoria.objects.filter(destino__plano=op.plano, destino__empresa=empresa, origem__codigo=origem["codigo"]).select_related("categoria").first()
    possiveis = [c for c in categorias if c["totalizadora"] and not c["transferencia"] and tipo(c) == tipo(origem)]
    if vinculo:
        return next((c for c in possiveis if c["codigo"] == vinculo.categoria.codigo), None)
    iguais = [c for c in possiveis if normalizar(c["descricao"]) == normalizar(origem["descricao"])]
    return iguais[0] if len(iguais) == 1 else None


def compativel(op, candidato, pai):
    return bool(pai and candidato["ativo_omie"] and not candidato["totalizadora"] and not candidato["transferencia"]
        and tipo(candidato) == tipo(op.pedido["origem"]) and candidato["categoria_superior"] == pai["codigo"]
        and (op.modo != "reativar" or not pai["conta_inativa"]))


def preparar_linha(op, linha, categorias):
    origem = op.pedido["origem"]
    pai = pai_destino(op, linha.empresa, categorias)
    candidatos = [c for c in categorias if compativel(op, c, pai)]
    candidatos.sort(key=lambda c: (-semelhanca(origem["descricao"], c["descricao"]), normalizar(c["descricao"]), c["codigo"]))
    alvo = None
    if linha.empresa_id == op.plano.matriz_id:
        alvo = next((c for c in candidatos if c["codigo"] == origem["codigo"]), None)
    else:
        vinculo = VinculoCategoria.objects.filter(destino__plano=op.plano, destino__empresa=linha.empresa, origem_id=op.pedido["origem_id"]).select_related("categoria").first()
        if vinculo:
            alvo = next((c for c in candidatos if c["codigo"] == vinculo.categoria.codigo), None)
        else:
            iguais = [c for c in candidatos if normalizar(c["descricao"]) == normalizar(origem["descricao"])]
            alvo = iguais[0] if len(iguais) == 1 else None
    linha.passos = [{"origem": origem, "alvo": alvo, "acao": op.modo, "status": "pendente",
        "candidatos": [{"dados": c, "compativel": True} for c in candidatos], "pai": pai}]
    linha.status = "revisao"
    linha.mensagem = ("Confira o cadastro correspondente antes de confirmar a alteração." if alvo
        else "Escolha explicitamente a categoria correspondente ou ignore esta empresa." if candidatos
        else "Não há categoria compatível ou o grupo superior está ausente/ambíguo/inativo para reativação. Esta empresa pode ser ignorada.")
    linha.save()


def conferir_origem(op, categorias):
    fonte = next((c for c in categorias if c["codigo"] == op.pedido["origem"]["codigo"]), None)
    pai = next((c for c in categorias if c["codigo"] == op.pedido["pai"]["codigo"]), None)
    if not fonte or identidade(fonte) != identidade(op.pedido["origem"]) or not pai or identidade(pai) != identidade(op.pedido["pai"]):
        raise ValidationError("A categoria ou seu grupo superior mudou na base PAI. Atualize a árvore e inicie uma nova solicitação.")


def processar(op):
    """Called inside central's worker claim, scope and operation lock."""
    from .central import conferir_operacao, conferir_sem_incerteza, progresso
    empresas = conferir_operacao(op)
    linhas = list(op.empresas.select_related("empresa"))
    if not linhas or not {l.empresa_id for l in linhas}.issubset({e.pk for e in empresas}):
        raise PermissionDenied("Empresas da solicitação não pertencem ao grupo.")
    if op.pedido.get("etapa") == "consulta":
        with aplicativo_livre(op.plano.matriz, aguardar_sincronizacao=False) as integracao:
            fonte = catalogo(op.plano.matriz, integracao)
        conferir_origem(op, fonte)
        for linha in linhas:
            conferir_operacao(op)
            conferir_sem_incerteza(linha.empresa, linha)
            progresso(op, f"Localizando {op.pedido['descricao']} em {linha.empresa.nome_fantasia or linha.empresa.nome}.")
            if linha.empresa_id == op.plano.matriz_id:
                categorias = fonte
            else:
                with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                    categorias = catalogo(linha.empresa, integracao)
            preparar_linha(op, linha, categorias)
            progresso(op, op.mensagem, 1)
        op.status = "revisao"
        progresso(op, "Prévia pronta. Confira empresas, categorias e códigos e confirme a alteração. Nenhuma categoria foi alterada.")
        return
    if op.pedido.get("etapa") != "envio":
        raise ValidationError("Etapa da solicitação inválida.")
    with aplicativo_livre(op.plano.matriz, aguardar_sincronizacao=False) as integracao:
        fonte = catalogo(op.plano.matriz, integracao)
    conferir_origem(op, fonte)
    op.status = "enviando"
    op.progresso_atual = len(linhas)
    op.save()
    for linha in linhas:
        if linha.status in {"sucesso", "ignorada"}:
            progresso(op, op.mensagem, 1)
            continue
        progresso(op, f"{op.modo.capitalize()} {op.pedido['descricao']} em {linha.empresa.nome_fantasia or linha.empresa.nome}.")
        try:
            conferir_operacao(op)
            conferir_sem_incerteza(linha.empresa, linha)
            if linha.status == "incerto" or any(p.get("status") in {"executando", "incerto"} for p in linha.passos):
                raise ValidationError("Verifique o envio sem confirmação antes de retomar.")
            with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                categorias = catalogo(linha.empresa, integracao)
                passo = linha.passos[0]
                escolhido = passo["alvo"]
                atual = next((c for c in categorias if escolhido and c["codigo"] == escolhido["codigo"]), None)
                pai = pai_destino(op, linha.empresa, categorias)
                if not atual or not compativel(op, atual, pai) or identidade(atual) != identidade(escolhido):
                    preparar_linha(op, linha, categorias)
                    linha.mensagem = "O cadastro mudou após a confirmação. Confira a nova prévia antes de aplicar."
                    linha.save()
                    continue
                desejado = op.modo == "inativar"
                if atual["conta_inativa"] == desejado:
                    passo.update(status="sucesso", codigo=atual["codigo"], confirmado=atual)
                else:
                    payload = {k: atual[k] for k in ("codigo", "descricao", "tipo_categoria", "codigo_dre")}
                    payload["conta_inativa"] = "S" if desejado else "N"
                    passo.update(status="executando", codigo=atual["codigo"], metodo="AlterarCategoria", parametros=payload,
                        esperado={**atual, "conta_inativa": desejado})
                    linha.status, linha.mensagem = "executando", "Aguardando confirmação da alteração na OMIE."
                    linha.save()
                    try:
                        resposta = omie.chamada(integracao, "AlterarCategoria", payload)
                    except omie.OmieRecusada:
                        passo["status"] = "erro"
                        linha.save()
                        raise
                    if str(resposta.get("codigo")) != atual["codigo"]:
                        raise omie.OmieIncerta("Código retornado diferente do confirmado.")
                    confirmar_resultado(linha, 0, integracao)
                linha.status = "sucesso"
                linha.mensagem = "Categoria inativada e confirmada na OMIE." if desejado else "Categoria reativada e confirmada na OMIE."
                linha.save()
                auditar(op.plano, op.solicitado_por, "Confirmou situação de categoria na OMIE", cadastro_id=op.pk,
                    empresa_id=linha.empresa_id, modo=op.modo, codigo=atual["codigo"], passos=linha.passos)
        except omie.OmieRecusada:
            linha.status, linha.mensagem = "erro", "A OMIE recusou a alteração. Corrija a causa antes de retomar."
            linha.save()
        except Exception as exc:
            linha.status = "incerto" if any(p.get("status") in {"executando", "incerto"} for p in linha.passos) else "erro"
            linha.mensagem = ("Resultado sem confirmação. Use Verificar resultado; não será reenviado." if linha.status == "incerto"
                else " ".join(exc.messages) if isinstance(exc, ValidationError) else "Não foi possível alterar esta empresa. As demais continuam.")
            linha.save()
        finally:
            progresso(op, op.mensagem, 1)
    op.status = "revisao" if op.empresas.filter(status="revisao").exists() else "concluido"
    progresso(op, "Processamento finalizado. Confira o resultado por empresa." if op.status == "concluido" else "Há cadastros que mudaram. Confira a prévia para continuar.")


def confirmar(op, usuario, escolhas):
    from .central import conferir_empresas, conferir_operacao
    with transaction.atomic():
        PlanoReplicacao.objects.select_for_update().get(pk=op.plano_id)
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_empresas(op.plano, usuario)
        conferir_operacao(op)
        if op.modo not in MODOS or op.status != "revisao":
            raise ValidationError("Esta solicitação não está aguardando confirmação de situação.")
        cancelar = escolhas.get("cancelar") == "sim"
        if not cancelar and escolhas.get("confirmar") != "sim":
            raise ValidationError("Confirme a alteração das categorias selecionadas nos OMIEs.")
        for linha in op.empresas.select_for_update().exclude(status__in=["sucesso", "ignorada"]):
            if linha.status == "incerto":
                raise ValidationError("Verifique os envios sem confirmação antes de continuar.")
            if cancelar or escolhas.get(f"aplicar_{linha.pk}") != "sim":
                linha.status, linha.mensagem = "ignorada", "Empresa ignorada por decisão do usuário; nenhuma nova alteração será enviada."
            else:
                passo = linha.passos[0]
                codigo = escolhas.get(f"categoria_{linha.pk}", "")
                escolhido = next((c["dados"] for c in passo["candidatos"] if c["compativel"] and c["dados"]["codigo"] == codigo), None)
                if not escolhido:
                    raise ValidationError("Escolha uma categoria compatível para cada empresa marcada, ou desmarque a empresa para ignorar.")
                passo.update(alvo=deepcopy(escolhido), status="pendente", decisao={"usuario_id": usuario.pk, "em": timezone.now().isoformat()})
                linha.status, linha.mensagem = "pronta", "Alteração confirmada; aguardando o worker."
            linha.save()
        op.solicitado_por = usuario
        op.pedido["etapa"] = "envio"
        op.status = "fila" if op.empresas.filter(status="pronta").exists() else "concluido"
        op.iniciada_em = None
        if op.status == "concluido":
            op.progresso_atual = op.progresso_total
            op.mensagem = "Solicitação encerrada. Nenhuma nova alteração será enviada."
        op.save()
        auditar(op.plano, usuario, "Confirmou prévia de situação de categoria", cadastro_id=op.pk, modo=op.modo, cancelar=cancelar,
            empresas=list(op.empresas.values("empresa_id", "status", "passos")))
        return op


def confirmar_resultado(linha, indice, integracao, codigo=""):
    passo = linha.passos[indice]
    esperado = passo["esperado"]
    if codigo and codigo != esperado["codigo"]:
        raise ValidationError("O código difere do cadastro originalmente enviado.")
    registros = omie.listar(integracao, descricao=esperado["descricao"])
    registro = next((c for c in registros if str(c.get("codigo")) == esperado["codigo"]), None)
    if not registro:
        raise omie.OmieIncerta("A OMIE ainda não confirmou a situação da categoria.")
    with transaction.atomic():
        _salvar_categorias(linha.empresa, [registro])
        categoria = CategoriaOmie.objects.get(empresa=linha.empresa, codigo=esperado["codigo"])
        confirmado = snapshot(categoria)
        comparar = (lambda c: c) if "natureza" in passo.get("parametros", {}) else sem_observacoes
        if comparar(confirmado) != comparar(esperado):
            raise omie.OmieIncerta("Situação ou dados diferentes do aprovado. Verifique sem reenviar.")
        passo.update(status="sucesso", codigo=confirmado["codigo"], confirmado=confirmado)
        linha.save()
