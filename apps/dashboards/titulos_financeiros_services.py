"""Carteiras em aberto por vencimento, com os filtros do modulo financeiro."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db.models import Q
from django.db.models.functions import Trim, Upper
from django.utils import timezone

from apps.empresas.models import ContaPagarOmie, ContaReceberOmie
from .dre_services import NOMES_MESES, _formatar_moeda, _intervalo_periodo
from .finance_filters import registros_com_conta_visivel_financeiro
from .fluxo_caixa_services import STATUS_FECHADOS_PAGAR, STATUS_FECHADOS_RECEBER


CORES_CATEGORIAS = ["#2563eb", "#0f9488", "#e8a125", "#d64f76", "#765ac2", "#4a8295", "#84909f"]


def _decimal(valor):
    try:
        resultado = Decimal(str(valor or 0))
        return resultado if resultado.is_finite() else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _selecionado(empresa_id, codigo, selecionados):
    return str(codigo) in selecionados or f"{empresa_id}:{codigo}" in selecionados


def _filtrar_codigos(queryset, campo, selecionados):
    if not selecionados:
        return queryset
    filtro = Q()
    for valor in selecionados:
        partes = str(valor).split(":", 1)
        if len(partes) == 2:
            filtro |= Q(empresa_id=partes[0], **{campo: partes[1]})
        else:
            filtro |= Q(**{campo: partes[0]})
    return queryset.filter(filtro)


def _fracao_departamentos(conta, selecionados):
    if not selecionados:
        return Decimal("1")
    distribuicao = conta.distribuicao if isinstance(conta.distribuicao, list) else []
    fracao = Decimal("0")
    for item in distribuicao:
        if not isinstance(item, dict) or not _selecionado(conta.empresa_id, item.get("cCodDep", ""), selecionados):
            continue
        if item.get("nPerDep") not in (None, ""):
            fracao += max(Decimal("0"), _decimal(item["nPerDep"])) / 100
        elif conta.valor_documento > 0:
            fracao += max(Decimal("0"), _decimal(item.get("nValDep"))) / conta.valor_documento
    return min(fracao, Decimal("1"))


def _fluxo(inicio, fim, por_data, periodo):
    dias = (fim - inicio).days + 1
    tipo_periodo = (periodo or "ano").split("-", 1)[0]
    granularidade = "dia" if tipo_periodo == "mes" or (tipo_periodo == "personalizado" and dias <= 62) else "mes"

    def chave(data):
        if granularidade == "mes":
            return data.replace(day=1)
        return data

    totais = defaultdict(Decimal)
    for data, valor in por_data.items():
        totais[chave(data)] += valor
    labels, valores = [], []
    atual = chave(inicio)
    while atual <= fim:
        labels.append(f"{NOMES_MESES[atual.month - 1]}/{atual.year % 100:02d}" if granularidade == "mes" else atual.strftime("%d/%m/%y" if inicio.year != fim.year else "%d/%m"))
        valores.append(float(totais[atual]))
        if granularidade == "mes":
            if atual.year == 9999 and atual.month == 12:
                break
            atual = atual.replace(year=atual.year + 1, month=1) if atual.month == 12 else atual.replace(month=atual.month + 1)
        else:
            if atual == fim:
                break
            atual += timedelta(days=1)
    return {"labels": labels, "valores": valores, "granularidade": granularidade, "tem_dados": any(valores)}


def carteira_financeira(empresa, tipo, periodo, data_inicio="", data_fim="", empresas_ids=None,
                        projetos=None, departamentos=None, categorias=None, hoje=None):
    if tipo not in {"pagar", "receber"}:
        raise ValueError("Carteira financeira invalida.")
    hoje = hoje or timezone.localdate()
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    modelo = ContaPagarOmie if tipo == "pagar" else ContaReceberOmie
    pessoa_field = "fornecedor" if tipo == "pagar" else "cliente"
    campo_valor = "valor_a_pagar" if tipo == "pagar" else "valor_a_receber"
    fechados = STATUS_FECHADOS_PAGAR if tipo == "pagar" else STATUS_FECHADOS_RECEBER
    queryset = modelo.objects.filter(
        empresa_id__in=empresas_ids if empresas_ids is not None else [empresa.pk],
        empresa__ativa=True, ativo_omie=True, data_vencimento__range=(inicio, fim),
        **{f"{campo_valor}__gt": 0},
    ).annotate(status_normalizado=Upper(Trim("status_titulo"))).exclude(status_normalizado__in=fechados)
    queryset = _filtrar_codigos(queryset, "codigo_projeto", projetos)
    queryset = _filtrar_codigos(queryset, "codigo_categoria", categorias)
    queryset = registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")
    queryset = queryset.select_related("empresa", pessoa_field, "categoria_principal").order_by("data_vencimento", "codigo_lancamento_omie", "pk")
    total = Decimal("0")
    subtotais = {"vencido": Decimal("0"), "hoje": Decimal("0"), "futuro": Decimal("0")}
    quantidades = defaultdict(int)
    por_data, por_categoria, por_pessoa = defaultdict(Decimal), defaultdict(Decimal), {}
    selecionados_dep = {str(valor) for valor in departamentos or []}
    for conta in queryset.iterator(chunk_size=1000):
        valor = (_decimal(getattr(conta, campo_valor)) * _fracao_departamentos(conta, selecionados_dep)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if valor <= 0:
            continue
        status = "vencido" if conta.data_vencimento < hoje else "hoje" if conta.data_vencimento == hoje else "futuro"
        pessoa = getattr(conta, pessoa_field)
        nome = getattr(pessoa, "nome_fantasia", "") or getattr(pessoa, "razao_social", "") or ("Fornecedor nao informado" if tipo == "pagar" else "Cliente nao informado")
        categoria = getattr(conta.categoria_principal, "descricao", "") or conta.codigo_categoria or "Sem categoria"
        pessoa_chave = (conta.empresa_id, conta.codigo_cliente_fornecedor or getattr(pessoa, "codigo_cliente_omie", None) or nome)
        if pessoa_chave not in por_pessoa:
            por_pessoa[pessoa_chave] = {"nome": nome, "empresa": conta.empresa.nome_fantasia or conta.empresa.nome, "valor": Decimal("0")}
        por_pessoa[pessoa_chave]["valor"] += valor
        por_data[conta.data_vencimento] += valor
        por_categoria[categoria] += valor
        subtotais[status] += valor
        quantidades[status] += 1
        total += valor
    indicadores = [{"titulo": "Total em aberto", "valor": _formatar_moeda(total), "quantidade": sum(quantidades.values()), "tom": "total", "icone": "bi-wallet2"}]
    for status, titulo, icone in [("vencido", "Vencido", "bi-exclamation-triangle"), ("hoje", "Vence hoje", "bi-calendar-event"), ("futuro", "A vencer no periodo", "bi-calendar-check")]:
        indicadores.append({"titulo": titulo, "valor": _formatar_moeda(subtotais[status]), "quantidade": quantidades[status], "tom": status, "icone": icone})
    ranking = sorted(por_pessoa.values(), key=lambda item: (-item["valor"], item["nome"]))[:5]
    maior = ranking[0]["valor"] if ranking else Decimal("0")
    for item in ranking:
        item.update(valor_fmt=_formatar_moeda(item["valor"]), largura=float(item["valor"] / maior * 100) if maior else 0)
    categorias_ordenadas = sorted(por_categoria.items(), key=lambda item: (-item[1], item[0]))
    if len(categorias_ordenadas) > 7:
        categorias_ordenadas = categorias_ordenadas[:6] + [("Outras categorias", sum((v for _, v in categorias_ordenadas[6:]), Decimal("0")))]
    composicao = [{"nome": nome, "valor": float(valor), "valor_fmt": _formatar_moeda(valor), "percentual": f"{valor / total * 100:.1f}%".replace(".", ","), "cor": CORES_CATEGORIAS[i]} for i, (nome, valor) in enumerate(categorias_ordenadas)]
    return {
        "tipo": tipo, "indicadores": indicadores, "ranking": ranking,
        "pessoa_rotulo": "Fornecedor" if tipo == "pagar" else "Cliente",
        "ranking_titulo": "Maiores fornecedores" if tipo == "pagar" else "Maiores clientes",
        "fluxo_titulo": "Fluxo de pagamentos" if tipo == "pagar" else "Fluxo de recebimentos",
        "serie_rotulo": "Valor a pagar" if tipo == "pagar" else "Valor a receber",
        "inicio": inicio, "fim": fim, "hoje": hoje, "total_fmt": _formatar_moeda(total),
        "fluxo": _fluxo(inicio, fim, por_data, periodo), "composicao": composicao,
        "composicao_chart": {"labels": [i["nome"] for i in composicao], "valores": [i["valor"] for i in composicao], "cores": [i["cor"] for i in composicao]},
        "rateado": bool(selecionados_dep),
    }
