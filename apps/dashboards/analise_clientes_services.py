"""Calculos do dashboard comercial Analise de Clientes."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
    _porcentagem,
)
from apps.dashboards.faturamento_services import _formatar_numero
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import CadastroOmie, OrdemServicoOmie, PedidoOmie


SEGMENTOS = (
    {
        "chave": "vip",
        "rotulo": "VIP",
        "cor": "#2f7de1",
    },
    {
        "chave": "ativo",
        "rotulo": "Ativos",
        "cor": "#16a34a",
    },
    {
        "chave": "risco",
        "rotulo": "Em risco",
        "cor": "#f4b740",
    },
    {
        "chave": "inativo",
        "rotulo": "Inativos",
        "cor": "#ef4444",
    },
)


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_percentual(valor):
    return f"{_decimal(valor):.0f}%".replace(".", ",")


def _media(total, quantidade):
    if not quantidade:
        return Decimal("0")
    return _decimal(total) / Decimal(quantidade)


def _query_pedidos_faturados(inicio, fim, empresas_ids, projetos):
    queryset = PedidoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        cancelado=False,
        faturado=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_ordens_faturadas(inicio, fim, empresas_ids):
    return OrdemServicoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        cancelada=False,
        faturada=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    )


def _somar_vendas(destino, queryset, campo_valor, campo_data=None):
    campo_data = campo_data or "data_faturamento"
    linhas = queryset.values("codigo_cliente").annotate(
        total=Sum(campo_valor),
        quantidade=Count("id"),
    )
    for item in linhas:
        codigo = str(item["codigo_cliente"] or "")
        if not codigo:
            continue
        destino[codigo]["valor"] += _decimal(item["total"])
        destino[codigo]["quantidade"] += item["quantidade"] or 0

    for item in queryset.values("codigo_cliente", campo_data):
        codigo = str(item["codigo_cliente"] or "")
        data = item.get(campo_data)
        if not codigo or not data:
            continue
        atual = destino[codigo].get("ultima_compra")
        if atual is None or data > atual:
            destino[codigo]["ultima_compra"] = data


def _compras_por_cliente(inicio, fim, empresas_ids, projetos):
    compras = defaultdict(lambda: {"valor": Decimal("0"), "quantidade": 0})
    _somar_vendas(
        compras,
        _query_pedidos_faturados(inicio, fim, empresas_ids, projetos),
        "valor_total_pedido",
    )
    _somar_vendas(
        compras,
        _query_ordens_faturadas(inicio, fim, empresas_ids),
        "valor_total",
    )
    return compras


def _classificar_cliente(cliente, compras_6_meses, ultima_compra, limite_6, limite_12):
    codigo = str(cliente.codigo_cliente_omie)
    quantidade_6_meses = compras_6_meses.get(codigo, {}).get("quantidade", 0)
    ultima = ultima_compra.get(codigo)

    if cliente.inativo or not ultima or ultima < limite_12:
        return "inativo"
    if ultima < limite_6:
        return "risco"
    if quantidade_6_meses > 1:
        return "vip"
    return "ativo"


def _segmentos_clientes(clientes, compras_6_meses, compras_12_meses, fim):
    limite_6 = fim - timedelta(days=183)
    limite_12 = fim - timedelta(days=365)
    ultima_compra = {
        codigo: dados.get("ultima_compra")
        for codigo, dados in compras_12_meses.items()
        if dados.get("ultima_compra")
    }
    por_cliente = {}
    contagens = defaultdict(int)

    for cliente in clientes:
        segmento = _classificar_cliente(
            cliente,
            compras_6_meses,
            ultima_compra,
            limite_6,
            limite_12,
        )
        codigo = str(cliente.codigo_cliente_omie)
        por_cliente[codigo] = segmento
        contagens[segmento] += 1

    total = sum(contagens.values())
    barras = []
    for segmento in SEGMENTOS:
        quantidade = contagens[segmento["chave"]]
        percentual = _porcentagem(Decimal(quantidade), Decimal(total))
        barras.append(
            {
                **segmento,
                "quantidade": quantidade,
                "percentual": float(percentual),
                "percentual_fmt": _formatar_percentual(percentual),
            }
        )
    return por_cliente, barras


def _top_clientes(compras_periodo, clientes_por_codigo):
    itens = []
    for codigo, dados in compras_periodo.items():
        cliente = clientes_por_codigo.get(codigo)
        nome = (
            (cliente.nome_fantasia or cliente.razao_social)
            if cliente
            else f"Cliente {codigo}"
        )
        itens.append({"nome": nome, "valor": dados["valor"]})
    itens.sort(key=lambda item: item["valor"], reverse=True)

    top = itens[:10]
    restante = sum((item["valor"] for item in itens[10:]), Decimal("0"))
    labels = [item["nome"] for item in top]
    valores = [float(item["valor"]) for item in top]
    if restante:
        labels.append("Restante")
        valores.append(float(restante))
    return labels or ["Sem faturamento"], valores or [0]


def _ticket_por_segmento(compras_periodo, compras_6_meses, segmentos_por_cliente, meses):
    meses_quantidade = max(len(meses), 1)
    linhas = []
    for segmento in SEGMENTOS:
        codigos = [
            codigo
            for codigo, segmento_cliente in segmentos_por_cliente.items()
            if segmento_cliente == segmento["chave"]
        ]
        total = sum(
            (compras_periodo.get(codigo, {}).get("valor", Decimal("0")) for codigo in codigos),
            Decimal("0"),
        )
        documentos = sum(
            (compras_periodo.get(codigo, {}).get("quantidade", 0) for codigo in codigos),
            0,
        )
        documentos_6_meses = sum(
            (compras_6_meses.get(codigo, {}).get("quantidade", 0) for codigo in codigos),
            0,
        )
        frequencia = 0
        if codigos:
            frequencia = documentos_6_meses / max(len(codigos), 1) / meses_quantidade
        linhas.append(
            {
                "segmento": segmento["rotulo"],
                "ticket": float(_media(total, documentos)),
                "frequencia": round(frequencia, 2),
            }
        )
    return linhas


def analise_clientes_comercial(
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
    inicio_6_meses = fim - timedelta(days=183)
    inicio_12_meses = fim - timedelta(days=365)

    clientes = list(
        CadastroOmie.objects.filter(
            empresa_id__in=empresas_ids,
            tipo__in=[CadastroOmie.Tipo.CLIENTE, CadastroOmie.Tipo.AMBOS],
        )
    )
    clientes_por_codigo = {
        str(cliente.codigo_cliente_omie): cliente for cliente in clientes
    }

    pedidos_periodo = _query_pedidos_faturados(inicio, fim, empresas_ids, projetos)
    ordens_periodo = _query_ordens_faturadas(inicio, fim, empresas_ids)
    total_pedidos = _decimal(
        pedidos_periodo.aggregate(total=Sum("valor_total_pedido"))["total"]
    )
    total_ordens = _decimal(ordens_periodo.aggregate(total=Sum("valor_total"))["total"])
    qtd_documentos = pedidos_periodo.count() + ordens_periodo.count()
    faturamento_total = total_pedidos + total_ordens
    compras_periodo = _compras_por_cliente(inicio, fim, empresas_ids, projetos)
    compras_6_meses = _compras_por_cliente(inicio_6_meses, fim, empresas_ids, projetos)
    compras_12_meses = _compras_por_cliente(
        inicio_12_meses,
        fim,
        empresas_ids,
        projetos,
    )
    compras_historicas = _compras_por_cliente(
        inicio - timedelta(days=3650),
        fim,
        empresas_ids,
        projetos,
    )

    clientes_ativos = sum(1 for cliente in clientes if not cliente.inativo)
    novos_periodo = CadastroOmie.objects.filter(
        empresa_id__in=empresas_ids,
        tipo__in=[CadastroOmie.Tipo.CLIENTE, CadastroOmie.Tipo.AMBOS],
        criado_em__date__gte=inicio,
        criado_em__date__lte=fim,
    ).count()
    limite_churn = fim - timedelta(days=183)
    churn = 0
    for codigo, dados in compras_historicas.items():
        cliente = clientes_por_codigo.get(codigo)
        if not cliente or cliente.inativo:
            continue
        ultima = dados.get("ultima_compra")
        if ultima and ultima < limite_churn:
            churn += 1

    segmentos_por_cliente, segmentos = _segmentos_clientes(
        clientes,
        compras_6_meses,
        compras_historicas,
        fim,
    )
    top_labels, top_valores = _top_clientes(compras_periodo, clientes_por_codigo)
    tickets_segmento = _ticket_por_segmento(
        compras_periodo,
        compras_6_meses,
        segmentos_por_cliente,
        meses,
    )

    return {
        "indicadores": [
            {
                "titulo": "Clientes ativos",
                "valor": _formatar_numero(Decimal(clientes_ativos)),
                "subvalor": "ativos no OMIE",
                "icone": "bi-people-fill",
                "tom": "primary",
            },
            {
                "titulo": "Novos no periodo",
                "valor": _formatar_numero(Decimal(novos_periodo)),
                "subvalor": "cadastros criados",
                "icone": "bi-person-plus-fill",
                "tom": "success",
            },
            {
                "titulo": "Churn no periodo",
                "valor": _formatar_numero(Decimal(churn)),
                "subvalor": "6+ meses sem compra",
                "icone": "bi-person-dash-fill",
                "tom": "warning",
            },
            {
                "titulo": "Ticket medio",
                "valor": _formatar_moeda_curta(_media(faturamento_total, qtd_documentos)),
                "subvalor": "por pedido faturado",
                "icone": "bi-receipt-cutoff",
                "tom": "neutral",
            },
        ],
        "segmentos": segmentos,
        "segmento_labels": [item["rotulo"] for item in segmentos],
        "segmento_percentuais": [item["percentual"] for item in segmentos],
        "segmento_cores": [item["cor"] for item in segmentos],
        "top_labels": top_labels,
        "top_valores": top_valores,
        "ticket_labels": [item["segmento"] for item in tickets_segmento],
        "ticket_valores": [item["ticket"] for item in tickets_segmento],
        "ticket_frequencia": [item["frequencia"] for item in tickets_segmento],
        "faturamento_total_fmt": _formatar_moeda(faturamento_total),
    }
