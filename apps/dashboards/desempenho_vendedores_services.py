"""Calculos do dashboard comercial Desempenho de Vendedores."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, Exists, Min, OuterRef, Q, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
    _porcentagem,
)
from apps.dashboards.faturamento_services import _formatar_numero, _tipos_validos
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    MetaVendedorComercial,
    NfseOmie,
    OrdemServicoOmie,
    PedidoOmie,
    VendedorOmie,
)


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_percentual(valor):
    return f"{_decimal(valor):.0f}%"


def _codigos_vendedores(valores):
    return _normalizar_filtro_composto(valores or [])


def _status_meta(percentual):
    percentual = _decimal(percentual)
    if percentual >= 100:
        return {"rotulo": "Acima da meta", "tom": "above"}
    if percentual >= 80:
        return {"rotulo": "Proximo a meta", "tom": "near"}
    if percentual >= 51:
        return {"rotulo": "No ritmo", "tom": "pace"}
    return {"rotulo": "Abaixo", "tom": "below"}


def _dias_atras(data):
    if not data:
        return "-"
    dias = (date.today() - data).days
    if dias <= 0:
        return "Hoje"
    if dias == 1:
        return "1d atras"
    return f"{dias}d atras"


def _meta_por_vendedor(empresas_ids, vendedores, meses):
    queryset = MetaVendedorComercial.objects.filter(
        empresa_id__in=empresas_ids,
        vendedor__inativo=False,
    ).select_related("vendedor")
    if vendedores:
        queryset = queryset.filter(vendedor__codigo__in=vendedores)
    filtros_periodo = {(item["ano"], item["mes"]) for item in meses}
    queryset = queryset.filter(
        ano__in={ano for ano, _ in filtros_periodo},
        mes__in={mes for _, mes in filtros_periodo},
    )
    metas = {}
    for meta in queryset:
        if (meta.ano, meta.mes) not in filtros_periodo:
            continue
        codigo = str(meta.vendedor.codigo)
        metas[codigo] = metas.get(codigo, Decimal("0")) + _decimal(meta.valor_mensal)
    return metas


def _vendedores_ativos(empresas_ids, vendedores):
    queryset = VendedorOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        inativo=False,
    ).select_related("empresa")
    if vendedores:
        queryset = queryset.filter(codigo__in=vendedores)
    return list(queryset.order_by("nome", "codigo"))


def _pedidos_faturados(inicio, fim, empresas_ids, projetos, vendedores):
    queryset = PedidoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
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


def _pedidos_abertos(inicio, fim, empresas_ids, projetos, vendedores):
    queryset = PedidoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelado=False,
        faturado=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _ordens_faturadas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelada=False,
        faturada=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    ).annotate(
        nfse_faturada=Exists(
            NfseOmie.objects.filter(
                empresa_id=OuterRef("empresa_id"),
                codigo_os=OuterRef("codigo_os"),
                ativo_omie=True,
                status_nfse="F",
            )
        )
    ).filter(Q(nfse_faturada=True) | ~Q(numero_recibo__in=["", "0"]))
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _ordens_abertas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelada=False,
        faturada=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _totais_por_vendedor(queryset):
    totais = defaultdict(Decimal)
    quantidades = defaultdict(int)
    linhas = queryset.values("codigo_vendedor").annotate(
        total=Sum("valor_total_pedido"),
        pedidos=Count("id"),
    )
    for item in linhas:
        codigo = str(item["codigo_vendedor"] or "")
        totais[codigo] += _decimal(item["total"])
        quantidades[codigo] += item["pedidos"] or 0
    return totais, quantidades


def _totais_por_vendedor_os(queryset):
    totais = defaultdict(Decimal)
    quantidades = defaultdict(int)
    linhas = queryset.values("codigo_vendedor").annotate(
        total=Sum("valor_total"),
        pedidos=Count("id"),
    )
    for item in linhas:
        codigo = str(item["codigo_vendedor"] or "")
        totais[codigo] += _decimal(item["total"])
        quantidades[codigo] += item["pedidos"] or 0
    return totais, quantidades


def _somar_mapas(destino, origem):
    for chave, valor in origem.items():
        destino[chave] += valor


def desempenho_vendedores(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    vendedores_selecionados=None,
    tipos_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    vendedores_filtro = _codigos_vendedores(vendedores_selecionados or [])
    tipos = _tipos_validos(tipos_selecionados or [])
    vendedores = _vendedores_ativos(empresas_ids, vendedores_filtro)
    vendedores_por_codigo = {str(vendedor.codigo): vendedor for vendedor in vendedores}
    metas = _meta_por_vendedor(empresas_ids, vendedores_filtro, meses)

    faturados = PedidoOmie.objects.none()
    abertos = PedidoOmie.objects.none()
    ordens_faturadas = OrdemServicoOmie.objects.none()
    ordens_abertas = OrdemServicoOmie.objects.none()
    if "produtos" in tipos:
        faturados = _pedidos_faturados(
            inicio,
            fim,
            empresas_ids,
            projetos,
            vendedores_filtro,
        )
        abertos = _pedidos_abertos(
            inicio,
            fim,
            empresas_ids,
            projetos,
            vendedores_filtro,
        )
    if "servicos" in tipos:
        ordens_faturadas = _ordens_faturadas(
            inicio,
            fim,
            empresas_ids,
            vendedores_filtro,
        )
        ordens_abertas = _ordens_abertas(
            inicio,
            fim,
            empresas_ids,
            vendedores_filtro,
        )
    realizado_por_vendedor, quantidade_por_vendedor = _totais_por_vendedor(faturados)
    realizado_os, quantidade_os = _totais_por_vendedor_os(ordens_faturadas)
    _somar_mapas(realizado_por_vendedor, realizado_os)
    _somar_mapas(quantidade_por_vendedor, quantidade_os)
    total_realizado = sum(realizado_por_vendedor.values(), Decimal("0"))
    total_pedidos = sum(quantidade_por_vendedor.values())
    total_meta = sum(metas.values(), Decimal("0"))
    percentual_meta = _porcentagem(total_realizado, total_meta)

    ranking_vendedores = []
    for codigo, vendedor in vendedores_por_codigo.items():
        realizado = realizado_por_vendedor[codigo]
        meta = metas.get(codigo, Decimal("0"))
        percentual = _porcentagem(realizado, meta)
        ranking_vendedores.append(
            {
                "codigo": codigo,
                "nome": vendedor.nome or str(vendedor.codigo),
                "realizado": realizado,
                "realizado_fmt": _formatar_moeda(realizado),
                "meta": meta,
                "meta_fmt": _formatar_moeda(meta),
                "falta": max(meta - realizado, Decimal("0")),
                "percentual": percentual,
                "percentual_fmt": _formatar_percentual(percentual),
                "status": _status_meta(percentual),
            }
        )
    ranking_vendedores.sort(key=lambda item: item["realizado"], reverse=True)
    melhor = ranking_vendedores[0] if ranking_vendedores else None

    tendencia_codigos = [item["codigo"] for item in ranking_vendedores[:3]]
    tendencia_labels = [item["rotulo"] for item in meses]
    tendencia_series = []
    totais_mensais = defaultdict(Decimal)
    linhas_mensais = (
        faturados.filter(codigo_vendedor__in=tendencia_codigos)
        .annotate(
            ano=ExtractYear("data_faturamento"),
            mes=ExtractMonth("data_faturamento"),
        )
        .values("codigo_vendedor", "ano", "mes")
        .annotate(total=Sum("valor_total_pedido"))
    )
    for item in linhas_mensais:
        totais_mensais[
            (str(item["codigo_vendedor"]), f"{item['ano']}-{item['mes']:02d}")
        ] += _decimal(item["total"])
    linhas_os_mensais = (
        ordens_faturadas.filter(codigo_vendedor__in=tendencia_codigos)
        .annotate(
            ano=ExtractYear("data_faturamento"),
            mes=ExtractMonth("data_faturamento"),
        )
        .values("codigo_vendedor", "ano", "mes")
        .annotate(total=Sum("valor_total"))
    )
    for item in linhas_os_mensais:
        totais_mensais[
            (str(item["codigo_vendedor"]), f"{item['ano']}-{item['mes']:02d}")
        ] += _decimal(item["total"])
    for codigo in tendencia_codigos:
        vendedor = vendedores_por_codigo.get(codigo)
        tendencia_series.append(
            {
                "nome": vendedor.nome if vendedor else codigo,
                "valores": [
                    float(totais_mensais[(codigo, item["chave"])]) for item in meses
                ],
            }
        )

    abertos_por_vendedor = {
        str(item["codigo_vendedor"] or ""): item
        for item in abertos.values("codigo_vendedor").annotate(
            pedidos=Count("id"),
            valor=Sum("valor_total_pedido"),
            mais_antigo=Min("data_referencia"),
        )
    }
    for item in ordens_abertas.values("codigo_vendedor").annotate(
        pedidos=Count("id"),
        valor=Sum("valor_total"),
        mais_antigo=Min("data_referencia"),
    ):
        codigo = str(item["codigo_vendedor"] or "")
        if codigo not in abertos_por_vendedor:
            abertos_por_vendedor[codigo] = {
                "codigo_vendedor": item["codigo_vendedor"],
                "pedidos": 0,
                "valor": Decimal("0"),
                "mais_antigo": item["mais_antigo"],
            }
        abertos_por_vendedor[codigo]["pedidos"] += item["pedidos"] or 0
        abertos_por_vendedor[codigo]["valor"] = _decimal(
            abertos_por_vendedor[codigo].get("valor")
        ) + _decimal(item["valor"])
        data_atual = abertos_por_vendedor[codigo].get("mais_antigo")
        data_nova = item["mais_antigo"]
        if data_nova and (not data_atual or data_nova < data_atual):
            abertos_por_vendedor[codigo]["mais_antigo"] = data_nova
    carteira = []
    for codigo, vendedor in vendedores_por_codigo.items():
        item = abertos_por_vendedor.get(codigo, {})
        valor = _decimal(item.get("valor"))
        pedidos = item.get("pedidos") or 0
        ticket = valor / Decimal(pedidos or 1)
        meta = metas.get(codigo, Decimal("0"))
        percentual = _porcentagem(realizado_por_vendedor[codigo], meta)
        carteira.append(
            {
                "iniciais": "".join(
                    parte[0] for parte in (vendedor.nome or str(vendedor.codigo)).split()[:2]
                ).upper(),
                "vendedor": vendedor.nome or str(vendedor.codigo),
                "pedidos": _formatar_numero(Decimal(pedidos)),
                "pedidos_num": pedidos,
                "valor": valor,
                "valor_fmt": _formatar_moeda_curta(valor),
                "ticket_fmt": _formatar_moeda_curta(ticket),
                "mais_antigo": _dias_atras(item.get("mais_antigo")),
                "percentual": percentual,
                "percentual_fmt": _formatar_percentual(percentual),
                "status": _status_meta(percentual),
            }
        )
    carteira.sort(key=lambda item: item["valor"], reverse=True)

    return {
        "indicadores": [
            {
                "titulo": "Faturamento total da equipe",
                "valor": _formatar_moeda_curta(total_realizado),
                "valor_completo": _formatar_moeda(total_realizado),
                "icone": "bi-cash-stack",
                "tom": "positive",
            },
            {
                "titulo": "% da meta atingida",
                "valor": _formatar_percentual(percentual_meta),
                "valor_completo": _formatar_percentual(percentual_meta),
                "icone": "bi-bullseye",
                "tom": "positive" if percentual_meta >= 80 else "neutral",
            },
            {
                "titulo": "Melhor performance",
                "valor": melhor["nome"] if melhor else "-",
                "subvalor": melhor["percentual_fmt"] if melhor else "0%",
                "valor_completo": melhor["nome"] if melhor else "-",
                "icone": "bi-trophy",
                "tom": "positive",
            },
            {
                "titulo": "Ticket medio da equipe",
                "valor": _formatar_moeda_curta(total_realizado / Decimal(total_pedidos or 1)),
                "valor_completo": _formatar_moeda(total_realizado / Decimal(total_pedidos or 1)),
                "icone": "bi-ticket-perforated",
                "tom": "positive",
            },
        ],
        "ranking": ranking_vendedores,
        "ranking_labels": [item["nome"] for item in ranking_vendedores],
        "ranking_realizado": [float(item["realizado"]) for item in ranking_vendedores],
        "ranking_falta": [float(item["falta"]) for item in ranking_vendedores],
        "ranking_meta": [float(item["meta"]) for item in ranking_vendedores],
        "tendencia_labels": tendencia_labels,
        "tendencia_series": tendencia_series,
        "carteira": carteira,
    }
