"""Calculos do dashboard comercial Faturamento."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
    _porcentagem,
    _variacao_percentual,
)
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    MetaVendedorComercial,
    OrdemServicoItemOmie,
    OrdemServicoOmie,
    PedidoItemOmie,
    PedidoOmie,
)


TIPOS_FATURAMENTO = {
    "produtos": "Produtos",
    "servicos": "Servicos",
}


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_numero(valor):
    valor = _decimal(valor)
    if valor == valor.to_integral():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_percentual(valor):
    return f"{valor:.0f}%".replace(".", ",")


def _tipos_validos(valores):
    valores_validos = [valor for valor in valores if valor in TIPOS_FATURAMENTO]
    return valores_validos or list(TIPOS_FATURAMENTO)


def _codigos_vendedores(valores):
    return _normalizar_filtro_composto(valores or [])


def _periodo_anterior(inicio, fim):
    dias = (fim - inicio).days + 1
    fim_anterior = inicio - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)
    return inicio_anterior, fim_anterior


def _meta_mensal(empresas_ids, vendedores):
    queryset = MetaVendedorComercial.objects.filter(
        empresa_id__in=empresas_ids,
        vendedor__inativo=False,
    )
    if vendedores:
        queryset = queryset.filter(vendedor__codigo__in=vendedores)
    return _decimal(queryset.aggregate(total=Sum("valor_mensal"))["total"])


def _query_pedidos_emitidos(inicio, fim, empresas_ids, projetos, vendedores):
    queryset = PedidoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        cancelado=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_pedidos_faturados(inicio, fim, empresas_ids, projetos, vendedores):
    queryset = PedidoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        cancelado=False,
        faturado=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_ordens_emitidas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        cancelada=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_ordens_faturadas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        cancelada=False,
        faturada=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    )
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _totais_por_mes(queryset, campo_data, campo_valor):
    totais = defaultdict(Decimal)
    linhas = (
        queryset.annotate(
            ano=ExtractYear(campo_data),
            mes=ExtractMonth(campo_data),
        )
        .values("ano", "mes")
        .annotate(total=Sum(campo_valor))
    )
    for item in linhas:
        if item["ano"] and item["mes"]:
            totais[f"{item['ano']}-{item['mes']:02d}"] = _decimal(item["total"])
    return totais


def _ranking_produtos(queryset, queryset_anterior, total_periodo):
    linhas = (
        PedidoItemOmie.objects.filter(pedido__in=queryset)
        .values("produto__descricao", "descricao", "codigo_produto_texto")
        .annotate(quantidade=Sum("quantidade"), total=Sum("valor_total"))
        .order_by("-total")[:5]
    )
    anterior_base = PedidoItemOmie.objects.filter(pedido__in=queryset_anterior)
    itens = []
    for item in linhas:
        nome = (
            item["produto__descricao"]
            or item["descricao"]
            or item["codigo_produto_texto"]
            or "Produto nao informado"
        )
        anterior = _decimal(
            anterior_base.filter(descricao=item["descricao"]).aggregate(
                total=Sum("valor_total")
            )["total"]
        )
        total = _decimal(item["total"])
        variacao = _variacao_percentual(total, anterior)
        itens.append(
            {
                "nome": nome,
                "quantidade": _formatar_numero(item["quantidade"]),
                "valor_fmt": _formatar_moeda(total),
                "participacao_fmt": _formatar_percentual(
                    _porcentagem(total, total_periodo)
                ),
                "participacao": float(_porcentagem(total, total_periodo)),
                "variacao_fmt": _formatar_percentual(variacao),
                "variacao_tom": "up" if variacao >= 0 else "down",
            }
        )
    return itens


def _ranking_servicos(queryset, queryset_anterior, total_periodo):
    valor_item = ExpressionWrapper(
        F("quantidade") * F("valor_unitario"),
        output_field=DecimalField(max_digits=18, decimal_places=4),
    )
    linhas = (
        OrdemServicoItemOmie.objects.filter(ordem_servico__in=queryset)
        .annotate(valor_calculado=valor_item)
        .values("servico__descricao", "descricao", "codigo_servico")
        .annotate(quantidade=Sum("quantidade"), total=Sum("valor_calculado"))
        .order_by("-total")[:5]
    )
    anterior_base = OrdemServicoItemOmie.objects.filter(
        ordem_servico__in=queryset_anterior
    ).annotate(valor_calculado=valor_item)
    itens = []
    for item in linhas:
        nome = (
            item["servico__descricao"]
            or item["descricao"]
            or str(item["codigo_servico"] or "")
            or "Servico nao informado"
        )
        anterior = _decimal(
            anterior_base.filter(descricao=item["descricao"]).aggregate(
                total=Sum("valor_calculado")
            )["total"]
        )
        total = _decimal(item["total"])
        variacao = _variacao_percentual(total, anterior)
        itens.append(
            {
                "nome": nome,
                "quantidade": _formatar_numero(item["quantidade"]),
                "valor_fmt": _formatar_moeda(total),
                "participacao_fmt": _formatar_percentual(
                    _porcentagem(total, total_periodo)
                ),
                "participacao": float(_porcentagem(total, total_periodo)),
                "variacao_fmt": _formatar_percentual(variacao),
                "variacao_tom": "up" if variacao >= 0 else "down",
            }
        )
    return itens


def faturamento_comercial(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    tipos_selecionados=None,
    vendedores_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    inicio_anterior, fim_anterior = _periodo_anterior(inicio, fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    vendedores = _codigos_vendedores(vendedores_selecionados or [])
    tipos = _tipos_validos(tipos_selecionados or [])

    pedidos_emitidos = _query_pedidos_emitidos(
        inicio, fim, empresas_ids, projetos, vendedores
    )
    pedidos_faturados = _query_pedidos_faturados(
        inicio, fim, empresas_ids, projetos, vendedores
    )
    pedidos_faturados_anteriores = _query_pedidos_faturados(
        inicio_anterior, fim_anterior, empresas_ids, projetos, vendedores
    )
    ordens_emitidas = _query_ordens_emitidas(inicio, fim, empresas_ids, vendedores)
    ordens_faturadas = _query_ordens_faturadas(inicio, fim, empresas_ids, vendedores)
    ordens_faturadas_anteriores = _query_ordens_faturadas(
        inicio_anterior, fim_anterior, empresas_ids, vendedores
    )

    total_produtos = _decimal(
        pedidos_faturados.aggregate(total=Sum("valor_total_pedido"))["total"]
    )
    total_servicos = _decimal(
        ordens_faturadas.aggregate(total=Sum("valor_total"))["total"]
    )
    total_faturado = Decimal("0")
    if "produtos" in tipos:
        total_faturado += total_produtos
    if "servicos" in tipos:
        total_faturado += total_servicos

    total_emitido = Decimal("0")
    quantidade_emitida = 0
    if "produtos" in tipos:
        total_emitido += _decimal(
            pedidos_emitidos.aggregate(total=Sum("valor_total_pedido"))["total"]
        )
        quantidade_emitida += pedidos_emitidos.aggregate(total=Count("id"))["total"]
    if "servicos" in tipos:
        total_emitido += _decimal(
            ordens_emitidas.aggregate(total=Sum("valor_total"))["total"]
        )
        quantidade_emitida += ordens_emitidas.aggregate(total=Count("id"))["total"]

    produtos_mes = _totais_por_mes(
        pedidos_faturados,
        "data_faturamento",
        "valor_total_pedido",
    )
    servicos_mes = _totais_por_mes(
        ordens_faturadas,
        "data_faturamento",
        "valor_total",
    )
    produtos_anterior = _decimal(
        pedidos_faturados_anteriores.aggregate(total=Sum("valor_total_pedido"))[
            "total"
        ]
    )
    servicos_anterior = _decimal(
        ordens_faturadas_anteriores.aggregate(total=Sum("valor_total"))["total"]
    )
    total_anterior = Decimal("0")
    if "produtos" in tipos:
        total_anterior += produtos_anterior
    if "servicos" in tipos:
        total_anterior += servicos_anterior
    media_anterior = total_anterior / Decimal(len(meses) or 1)
    meta_mensal = _meta_mensal(empresas_ids, vendedores)
    meta_periodo = meta_mensal * Decimal(len(meses) or 1)

    acumulado = []
    soma = Decimal("0")
    for item in meses:
        valor_mes = Decimal("0")
        if "produtos" in tipos:
            valor_mes += produtos_mes[item["chave"]]
        if "servicos" in tipos:
            valor_mes += servicos_mes[item["chave"]]
        soma += valor_mes
        acumulado.append(float(soma))

    ranking = []
    if "produtos" in tipos:
        ranking.extend(
            _ranking_produtos(
                pedidos_faturados,
                pedidos_faturados_anteriores,
                total_faturado,
            )
        )
    if "servicos" in tipos:
        ranking.extend(
            _ranking_servicos(
                ordens_faturadas,
                ordens_faturadas_anteriores,
                total_faturado,
            )
        )
    ranking = sorted(
        ranking,
        key=lambda item: Decimal(str(item["participacao"])),
        reverse=True,
    )[:5]

    return {
        "indicadores": [
            {
                "titulo": "Faturado",
                "valor": _formatar_moeda_curta(total_faturado),
                "icone": "bi-receipt-cutoff",
                "tom": "positive",
            },
            {
                "titulo": "Meta do periodo",
                "valor": _formatar_moeda_curta(meta_periodo),
                "icone": "bi-bullseye",
                "tom": "neutral",
            },
            {
                "titulo": "Pedidos emitidos",
                "valor": _formatar_numero(Decimal(quantidade_emitida)),
                "icone": "bi-clipboard-check",
                "tom": "positive",
            },
            {
                "titulo": "Ticket medio",
                "valor": _formatar_moeda_curta(
                    total_emitido / Decimal(quantidade_emitida or 1)
                ),
                "icone": "bi-ticket-perforated",
                "tom": "positive",
            },
        ],
        "labels": [item["rotulo"] for item in meses],
        "produtos": [
            float(produtos_mes[item["chave"]]) if "produtos" in tipos else 0
            for item in meses
        ],
        "servicos": [
            float(servicos_mes[item["chave"]]) if "servicos" in tipos else 0
            for item in meses
        ],
        "media_anterior": [float(media_anterior) for _ in meses],
        "acumulado": acumulado,
        "meta": [float(meta_mensal) for _ in meses],
        "ranking": ranking,
        "tipos": tipos,
    }
