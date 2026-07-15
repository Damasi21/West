"""Calculos do dashboard comercial Margem e Rentabilidade."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _normalizar_filtro_composto,
    _porcentagem,
    _variacao_percentual,
)
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import PedidoItemOmie, PedidoOmie


CHAVES_CUSTO = (
    "valor_custo",
    "valorCusto",
    "nValorCusto",
    "custo",
    "custo_unitario",
    "valor_custo_unitario",
    "preco_custo",
    "precoCusto",
)


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _formatar_percentual(valor):
    return f"{_decimal(valor):.1f}%".replace(".", ",")


def _formatar_pp(valor):
    valor = _decimal(valor)
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{valor:.1f}pp".replace(".", ",")


def _periodo_anterior(inicio, fim):
    dias = (fim - inicio).days + 1
    fim_anterior = inicio - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)
    return inicio_anterior, fim_anterior


def _query_pedidos(inicio, fim, empresas_ids, projetos):
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


def _valor_em_json(*fontes):
    for fonte in fontes:
        if not isinstance(fonte, dict):
            continue
        for chave in CHAVES_CUSTO:
            valor = fonte.get(chave)
            if valor not in (None, ""):
                return _decimal(valor)
    return Decimal("0")


def _custo_item(item):
    custo_unitario = _valor_em_json(
        item.produto_dados,
        item.inf_adic,
        item.dados_originais,
        item.produto.info if item.produto_id else {},
        item.produto.dados_originais if item.produto_id else {},
    )
    if not custo_unitario:
        return Decimal("0")
    return custo_unitario * _decimal(item.quantidade)


def _faixa_margem(margem):
    margem = _decimal(margem)
    if margem < 0:
        return {"rotulo": "Negativa", "tom": "negative", "cor": "#80837d"}
    if margem < 15:
        return {"rotulo": "Baixa", "tom": "low", "cor": "#a83232"}
    if margem < 35:
        return {"rotulo": "Media", "tom": "medium", "cor": "#965f11"}
    return {"rotulo": "Alta", "tom": "high", "cor": "#356d1d"}


def _itens_agregados(pedidos):
    produtos = defaultdict(
        lambda: {
            "codigo": "",
            "produto": "",
            "receita": Decimal("0"),
            "custo": Decimal("0"),
            "desconto": Decimal("0"),
            "quantidade": Decimal("0"),
        }
    )
    itens = (
        PedidoItemOmie.objects.filter(pedido__in=pedidos)
        .select_related("produto")
        .order_by("codigo_produto", "codigo_produto_texto", "descricao")
    )
    for item in itens:
        codigo = str(
            item.codigo_produto
            or item.codigo_produto_texto
            or item.produto_id
            or item.codigo_item
        )
        produto = produtos[codigo]
        produto["codigo"] = item.codigo_produto_texto or (
            item.produto.codigo if item.produto_id else ""
        ) or str(item.codigo_produto or "")
        produto["produto"] = (
            item.produto.descricao if item.produto_id else ""
        ) or item.descricao or "Produto nao informado"
        produto["receita"] += _decimal(item.valor_total)
        produto["custo"] += _custo_item(item)
        produto["desconto"] += _decimal(item.valor_desconto)
        produto["quantidade"] += _decimal(item.quantidade)
    return list(produtos.values())


def _preparar_linhas(produtos):
    linhas = []
    for produto in produtos:
        receita = produto["receita"]
        custo = produto["custo"]
        lucro = receita - custo
        margem = _porcentagem(lucro, receita)
        faixa = _faixa_margem(margem)
        linhas.append(
            {
                **produto,
                "lucro": lucro,
                "margem": margem,
                "margem_barra": max(min(float(margem), 100), 0),
                "margem_fmt": _formatar_percentual(margem),
                "receita_fmt": _formatar_moeda_curta(receita),
                "faixa": faixa,
            }
        )
    return linhas


def _ranking(linhas, reverso=True):
    chave = (lambda item: (item["lucro"], item["margem"], item["receita"]))
    ordenados = sorted(linhas, key=chave, reverse=reverso)[:5]
    return [
        {
            "codigo": item["codigo"] or "-",
            "produto": item["produto"],
            "receita": item["receita"],
            "receita_fmt": item["receita_fmt"],
            "margem": float(item["margem"]),
            "margem_barra": item["margem_barra"],
            "margem_fmt": item["margem_fmt"],
            "faixa": item["faixa"],
        }
        for item in ordenados
    ]


def _bolhas(linhas):
    maior_volume = max((item["quantidade"] for item in linhas), default=Decimal("0"))
    dados = []
    for item in linhas:
        volume = item["quantidade"]
        raio = Decimal("7")
        if maior_volume:
            raio += (volume / maior_volume) * Decimal("18")
        dados.append(
            {
                "x": float(item["receita"]),
                "y": float(item["margem"]),
                "r": float(raio),
                "produto": item["produto"],
                "codigo": item["codigo"] or "-",
                "volume": float(volume),
                "faixa": item["faixa"]["rotulo"],
                "cor": item["faixa"]["cor"],
            }
        )
    return dados


def margem_rentabilidade_comercial(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    inicio_anterior, fim_anterior = _periodo_anterior(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    pedidos = _query_pedidos(inicio, fim, empresas_ids, projetos)
    pedidos_anteriores = _query_pedidos(inicio_anterior, fim_anterior, empresas_ids, projetos)

    linhas = _preparar_linhas(_itens_agregados(pedidos))
    linhas_anteriores = _preparar_linhas(_itens_agregados(pedidos_anteriores))
    receita_total = sum((item["receita"] for item in linhas), Decimal("0"))
    custo_total = sum((item["custo"] for item in linhas), Decimal("0"))
    desconto_total = _decimal(pedidos.aggregate(total=Sum("valor_descontos"))["total"])
    receita_bruta = receita_total + desconto_total
    margem_bruta = _porcentagem(receita_total - custo_total, receita_total)

    receita_anterior = sum((item["receita"] for item in linhas_anteriores), Decimal("0"))
    custo_anterior = sum((item["custo"] for item in linhas_anteriores), Decimal("0"))
    margem_anterior = _porcentagem(receita_anterior - custo_anterior, receita_anterior)
    desconto_medio = _porcentagem(desconto_total, receita_bruta)
    produtos_negativos = sum(1 for item in linhas if item["margem"] < 0)

    return {
        "indicadores": [
            {
                "titulo": "Margem bruta media",
                "valor": _formatar_percentual(margem_bruta),
                "subvalor": f"{_formatar_pp(margem_bruta - margem_anterior)} vs. periodo anterior",
                "tom": "positive" if margem_bruta >= margem_anterior else "negative",
            },
            {
                "titulo": "Receita total",
                "valor": _formatar_moeda_curta(receita_total),
                "subvalor": "periodo selecionado",
                "tom": "neutral",
            },
            {
                "titulo": "Produtos c/ mg negativa",
                "valor": str(produtos_negativos),
                "subvalor": "requerem acao imediata" if produtos_negativos else "sem margem negativa",
                "tom": "negative" if produtos_negativos else "positive",
            },
            {
                "titulo": "Desconto medio",
                "valor": _formatar_percentual(desconto_medio),
                "subvalor": "sobre a receita bruta",
                "tom": "neutral",
            },
        ],
        "bubble_data": _bolhas(linhas),
        "top_rentaveis": _ranking(linhas, True),
        "bottom_urgente": _ranking(linhas, False),
    }
