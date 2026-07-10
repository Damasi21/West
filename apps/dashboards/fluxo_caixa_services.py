"""Calculos do dashboard Fluxo de Caixa."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
)
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    LancamentoContaCorrenteOmie,
)


STATUS_FECHADOS_RECEBER = {"RECEBIDO", "LIQUIDADO", "BAIXADO", "CANCELADO"}
STATUS_FECHADOS_PAGAR = {"PAGO", "LIQUIDADO", "BAIXADO", "CANCELADO"}


def _decimal(valor):
    return valor or Decimal("0")


def _query_receber_aberto(inicio, fim, empresas_ids, projetos):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_vencimento__gte=inicio,
        data_vencimento__lte=fim,
    ).exclude(status_titulo__in=STATUS_FECHADOS_RECEBER)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_pagar_aberto(inicio, fim, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_vencimento__gte=inicio,
        data_vencimento__lte=fim,
    ).exclude(status_titulo__in=STATUS_FECHADOS_PAGAR)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_lancamentos(inicio, fim, empresas_ids, projetos, natureza):
    queryset = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_lancamento__gte=inicio,
        data_lancamento__lte=fim,
        natureza=natureza,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _totais_por_mes(queryset, data_field, valor_field):
    totais = defaultdict(Decimal)
    linhas = (
        queryset.annotate(
            ano=ExtractYear(data_field),
            mes=ExtractMonth(data_field),
        )
        .values("ano", "mes")
        .annotate(total=Sum(valor_field))
    )
    for item in linhas:
        totais[f"{item['ano']}-{item['mes']:02d}"] = abs(_decimal(item["total"]))
    return totais


def _composicao(queryset, valor_field):
    linhas = (
        queryset.values("categoria_principal__descricao", "codigo_categoria")
        .annotate(total=Sum(valor_field))
        .order_by("-total")
    )
    principais = []
    outros = Decimal("0")
    for indice, item in enumerate(linhas):
        total = abs(_decimal(item["total"]))
        if not total:
            continue
        nome = (
            item["categoria_principal__descricao"]
            or item["codigo_categoria"]
            or "Sem categoria"
        )
        if indice < 4:
            principais.append({"nome": nome, "valor": float(total)})
        else:
            outros += total
    if outros:
        principais.append({"nome": "Outros", "valor": float(outros)})
    return principais


def _criticos(receber, pagar):
    hoje = date.today()
    itens = []
    for conta in receber.filter(data_vencimento__lt=hoje).select_related(
        "cliente", "categoria_principal"
    ):
        valor = abs(_decimal(conta.valor_a_receber or conta.valor_documento))
        itens.append(
            {
                "nome": (
                    getattr(conta.cliente, "nome_fantasia", "")
                    or getattr(conta.cliente, "razao_social", "")
                    or "Cliente nao informado"
                ),
                "vencimento": conta.data_vencimento,
                "vencimento_fmt": conta.data_vencimento.strftime("%d/%m/%Y"),
                "valor": valor,
                "valor_fmt": _formatar_moeda(valor),
                "dias": (hoje - conta.data_vencimento).days,
            }
        )
    for conta in pagar.filter(data_vencimento__lt=hoje).select_related(
        "fornecedor", "categoria_principal"
    ):
        valor = abs(_decimal(conta.valor_a_pagar or conta.valor_documento))
        itens.append(
            {
                "nome": (
                    getattr(conta.fornecedor, "nome_fantasia", "")
                    or getattr(conta.fornecedor, "razao_social", "")
                    or "Fornecedor nao informado"
                ),
                "vencimento": conta.data_vencimento,
                "vencimento_fmt": conta.data_vencimento.strftime("%d/%m/%Y"),
                "valor": valor,
                "valor_fmt": _formatar_moeda(valor),
                "dias": (hoje - conta.data_vencimento).days,
            }
        )
    return sorted(itens, key=lambda item: (item["dias"], item["valor"]), reverse=True)[:5]


def _prazo_medio_pagamento(pagar):
    prazos = []
    for conta in pagar.exclude(data_entrada__isnull=True).exclude(
        data_vencimento__isnull=True
    ):
        prazos.append((conta.data_vencimento - conta.data_entrada).days)
    if not prazos:
        return "0 dias"
    media = round(sum(prazos) / len(prazos))
    return f"{media} dias"


def fluxo_de_caixa(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])

    saldo_atual = _decimal(
        ContaCorrenteOmie.objects.filter(
            empresa_id__in=empresas_ids,
            inativo=False,
        ).aggregate(total=Sum("saldo_inicial"))["total"]
    )
    receber_aberto = _query_receber_aberto(inicio, fim, empresas_ids, projetos)
    pagar_aberto = _query_pagar_aberto(inicio, fim, empresas_ids, projetos)
    lanc_recebidos = _query_lancamentos(inicio, fim, empresas_ids, projetos, "R")
    lanc_pagos = _query_lancamentos(inicio, fim, empresas_ids, projetos, "P")

    entradas_previstas = abs(
        _decimal(receber_aberto.aggregate(total=Sum("valor_a_receber"))["total"])
    )
    saidas_previstas = abs(
        _decimal(pagar_aberto.aggregate(total=Sum("valor_a_pagar"))["total"])
    )
    entradas_realizadas = abs(
        _decimal(lanc_recebidos.aggregate(total=Sum("valor_lancamento"))["total"])
    )
    saidas_realizadas = abs(
        _decimal(lanc_pagos.aggregate(total=Sum("valor_lancamento"))["total"])
    )
    saldo_periodo = (
        entradas_previstas
        + entradas_realizadas
        - saidas_previstas
        - saidas_realizadas
    )
    saldo_projetado = saldo_atual + saldo_periodo

    entradas_previstas_mes = _totais_por_mes(
        receber_aberto,
        "data_vencimento",
        "valor_a_receber",
    )
    saidas_previstas_mes = _totais_por_mes(
        pagar_aberto,
        "data_vencimento",
        "valor_a_pagar",
    )
    entradas_realizadas_mes = _totais_por_mes(
        lanc_recebidos,
        "data_lancamento",
        "valor_lancamento",
    )
    saidas_realizadas_mes = _totais_por_mes(
        lanc_pagos,
        "data_lancamento",
        "valor_lancamento",
    )

    entradas = []
    saidas = []
    saldo_acumulado = []
    saldo_corrente = saldo_atual
    for item in meses:
        chave = item["chave"]
        entrada = entradas_previstas_mes[chave] + entradas_realizadas_mes[chave]
        saida = saidas_previstas_mes[chave] + saidas_realizadas_mes[chave]
        saldo_corrente += entrada - saida
        entradas.append(float(entrada))
        saidas.append(float(saida))
        saldo_acumulado.append(float(saldo_corrente))

    return {
        "indicadores": [
            {
                "titulo": "Saldo atual",
                "valor": _formatar_moeda_curta(saldo_atual),
                "icone": "bi-bank",
                "tom": "positive" if saldo_atual >= 0 else "negative",
            },
            {
                "titulo": "Entradas previstas",
                "valor": _formatar_moeda_curta(entradas_previstas),
                "icone": "bi-arrow-down-left-circle",
                "tom": "positive",
            },
            {
                "titulo": "Saidas previstas",
                "valor": _formatar_moeda_curta(saidas_previstas),
                "icone": "bi-arrow-up-right-circle",
                "tom": "negative",
            },
            {
                "titulo": "Saldo projetado",
                "valor": _formatar_moeda_curta(saldo_projetado),
                "icone": "bi-graph-up",
                "tom": "positive" if saldo_projetado >= 0 else "negative",
            },
            {
                "titulo": "Prazo medio de pagamento",
                "valor": _prazo_medio_pagamento(pagar_aberto),
                "icone": "bi-clock-history",
                "tom": "neutral",
            },
        ],
        "labels": [item["rotulo"] for item in meses],
        "entradas": entradas,
        "saidas": saidas,
        "saldo_acumulado": saldo_acumulado,
        "criticos": _criticos(receber_aberto, pagar_aberto),
        "composicao_entradas": _composicao(receber_aberto, "valor_a_receber"),
        "composicao_saidas": _composicao(pagar_aberto, "valor_a_pagar"),
    }
