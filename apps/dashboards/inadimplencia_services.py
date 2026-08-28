"""Calculos do dashboard de inadimplencia."""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.dashboards.finance_filters import filtrar_por_categorias_financeiras
from apps.dashboards.dre_services import (
    _formatar_moeda,
    _formatar_percentual,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
)
from apps.dashboards.fluxo_caixa_services import STATUS_FECHADOS_RECEBER
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import ContaReceberOmie, LancamentoContaCorrenteOmie


STATUS_CANCELADOS = {"CANCELADO"}
AGING_BUCKETS = (
    ("1-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90-180", 90, 180),
    (">180", 181, None),
)


def _decimal(valor):
    return valor or Decimal("0")


def _query_carteira(inicio, fim, empresas_ids, projetos, categorias):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_vencimento__gte=inicio,
        data_vencimento__lte=fim,
    ).exclude(status_titulo__in=STATUS_CANCELADOS)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = filtrar_por_categorias_financeiras(queryset, categorias)
    return queryset


def _query_inadimplentes(carteira, data_referencia):
    return carteira.filter(data_vencimento__lt=data_referencia).exclude(
        status_titulo__in=STATUS_FECHADOS_RECEBER
    )


def _valor_aberto(item):
    return abs(_decimal(item.valor_a_receber or item.valor_documento))


def _aging(inadimplentes, data_referencia):
    valores = {bucket[0]: Decimal("0") for bucket in AGING_BUCKETS}
    for item in inadimplentes:
        dias = (data_referencia - item.data_vencimento).days
        for nome, inicio, fim in AGING_BUCKETS:
            if dias >= inicio and (fim is None or dias <= fim):
                valores[nome] += _valor_aberto(item)
                break
    return {
        "labels": list(valores.keys()),
        "valores": [float(valor) for valor in valores.values()],
    }


def _dso(carteira):
    prazos = []
    for item in carteira:
        inicio = item.data_emissao or item.data_registro
        if inicio and item.data_vencimento:
            prazos.append((item.data_vencimento - inicio).days)
    if not prazos:
        return "0 dias"
    return f"{round(sum(prazos) / len(prazos))} dias"


def _recuperado(inicio, fim, empresas_ids, projetos, categorias):
    queryset = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_lancamento__gte=inicio,
        data_lancamento__lte=fim,
        natureza="R",
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = filtrar_por_categorias_financeiras(queryset, categorias)
    return abs(_decimal(queryset.aggregate(total=Sum("valor_lancamento"))["total"]))


def _fim_mes(ano, mes):
    return date(ano, mes, monthrange(ano, mes)[1])


def _tendencia(meses, empresas_ids, projetos, categorias):
    labels = []
    valores = []
    for mes in meses:
        fim_mes = _fim_mes(mes["ano"], mes["mes"])
        carteira = ContaReceberOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            data_vencimento__lte=fim_mes,
        ).exclude(status_titulo__in=STATUS_CANCELADOS)
        if projetos:
            carteira = carteira.filter(codigo_projeto__in=projetos)
        carteira = filtrar_por_categorias_financeiras(carteira, categorias)
        total_carteira = abs(
            _decimal(carteira.aggregate(total=Sum("valor_documento"))["total"])
        )
        total_inadimplente = abs(
            _decimal(
                _query_inadimplentes(carteira, fim_mes).aggregate(
                    total=Sum("valor_a_receber")
                )["total"]
            )
        )
        percentual = (
            (total_inadimplente / total_carteira) * Decimal("100")
            if total_carteira
            else Decimal("0")
        )
        labels.append(mes["rotulo"])
        valores.append(float(percentual))
    return {"labels": labels, "valores": valores}


def _top_devedores(inadimplentes, data_referencia):
    itens = []
    for item in inadimplentes.select_related("cliente"):
        valor = _valor_aberto(item)
        itens.append(
            {
                "cliente": (
                    getattr(item.cliente, "nome_fantasia", "")
                    or getattr(item.cliente, "razao_social", "")
                    or "Cliente nao informado"
                ),
                "dias": (data_referencia - item.data_vencimento).days,
                "valor": valor,
                "valor_fmt": _formatar_moeda(valor),
            }
        )
    return sorted(itens, key=lambda item: item["valor"], reverse=True)[:10]


def inadimplencia(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    categorias_selecionadas=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    categorias = _normalizar_filtro_composto(categorias_selecionadas or [])
    data_referencia = min(date.today(), fim)
    carteira = _query_carteira(inicio, fim, empresas_ids, projetos, categorias)
    inadimplentes = _query_inadimplentes(carteira, data_referencia)

    total_carteira = abs(
        _decimal(carteira.aggregate(total=Sum("valor_documento"))["total"])
    )
    total_inadimplente = abs(
        _decimal(inadimplentes.aggregate(total=Sum("valor_a_receber"))["total"])
    )
    percentual = (
        (total_inadimplente / total_carteira) * Decimal("100")
        if total_carteira
        else Decimal("0")
    )
    recuperado = _recuperado(inicio, fim, empresas_ids, projetos, categorias)
    tendencia = _tendencia(meses, empresas_ids, projetos, categorias)

    return {
        "indicadores": [
            {
                "titulo": "Total inadimplente",
                "subtitulo": "Exposicao",
                "valor": _formatar_moeda_curta(total_inadimplente),
                "valor_completo": _formatar_moeda(total_inadimplente),
                "tom": "negative",
            },
            {
                "titulo": "% Inadimplencia",
                "subtitulo": "Termometro da carteira",
                "valor": _formatar_percentual(percentual),
                "valor_completo": _formatar_percentual(percentual),
                "tom": "negative" if percentual else "neutral",
            },
            {
                "titulo": "DSO",
                "subtitulo": "Prazo medio de recebimento",
                "valor": _dso(carteira),
                "valor_completo": _dso(carteira),
                "tom": "warning",
            },
            {
                "titulo": "Recuperado no mes",
                "subtitulo": "Eficiencia cobranca",
                "valor": _formatar_moeda_curta(recuperado),
                "valor_completo": _formatar_moeda(recuperado),
                "tom": "positive",
            },
        ],
        "aging": _aging(inadimplentes, data_referencia),
        "tendencia": tendencia,
        "top_devedores": _top_devedores(inadimplentes, data_referencia),
    }
