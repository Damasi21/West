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
from apps.empresas.models import PedidoItemOmie, PedidoOmie, PosicaoEstoqueOmie


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _formatar_percentual(valor):
    return f"{_decimal(valor):.1f}%"


def _formatar_pp(valor):
    valor = _decimal(valor)
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{valor:.1f}pp"


def _periodo_anterior(inicio, fim):
    dias = (fim - inicio).days + 1
    fim_anterior = inicio - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)
    return inicio_anterior, fim_anterior


def _query_pedidos(inicio, fim, empresas_ids, projetos):
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
    return queryset


def _mapear_cmc_por_produto(itens):
    codigos_produtos = {
        item.codigo_produto
        for item in itens
        if item.codigo_produto is not None
    }
    empresas_ids = {item.empresa_id for item in itens}
    posicoes = {}
    posicoes_por_produto = {}
    for posicao in PosicaoEstoqueOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        codigo_produto__in=codigos_produtos,
    ).order_by("codigo_local_estoque"):
        chave_produto = (posicao.empresa_id, posicao.codigo_produto)
        chave_local = (
            posicao.empresa_id,
            posicao.codigo_produto,
            posicao.codigo_local_estoque,
        )
        posicoes[chave_local] = posicao.cmc
        posicoes_por_produto.setdefault(chave_produto, posicao.cmc)
    return posicoes, posicoes_por_produto


def _cmc_item(item, posicoes, posicoes_por_produto):
    chave_local = (
        item.empresa_id,
        item.codigo_produto,
        item.codigo_local_estoque or 0,
    )
    chave_produto = (item.empresa_id, item.codigo_produto)
    cmc = _decimal(
        posicoes.get(chave_local, posicoes_por_produto.get(chave_produto))
    )
    return cmc if cmc > 0 else None


def _faixa_margem(margem):
    margem = _decimal(margem)
    if margem < 0:
        return {"rotulo": "Negativa", "tom": "negative", "cor": "#80837d"}
    if margem < 15:
        return {"rotulo": "Baixa", "tom": "low", "cor": "#a83232"}
    if margem < 35:
        return {"rotulo": "Media", "tom": "medium", "cor": "#965f11"}
    return {"rotulo": "Alta", "tom": "high", "cor": "#356d1d"}


def _itens_agregados(pedidos, produtos=None, familias=None):
    produtos_filtrados = {str(valor) for valor in (produtos or []) if str(valor)}
    familias_filtradas = {str(valor) for valor in (familias or []) if str(valor)}
    agregados = defaultdict(
        lambda: {
            "codigo": "",
            "produto": "",
            "familia_codigo": "",
            "familia": "",
            "receita": Decimal("0"),
            "custo": Decimal("0"),
            "desconto": Decimal("0"),
            "quantidade": Decimal("0"),
        }
    )
    itens = list(
        PedidoItemOmie.objects.filter(pedido__in=pedidos, ativo_omie=True)
        .select_related("produto")
        .order_by("codigo_produto", "codigo_produto_texto", "descricao")
    )
    posicoes, posicoes_por_produto = _mapear_cmc_por_produto(itens)
    for item in itens:
        produto_modelo = item.produto
        codigo_produto = str(item.codigo_produto or item.codigo_produto_texto or "")
        codigo_familia = str(
            produto_modelo.codigo_familia
            if produto_modelo and produto_modelo.codigo_familia is not None
            else ""
        )
        if produtos_filtrados and codigo_produto not in produtos_filtrados:
            continue
        if familias_filtradas and codigo_familia not in familias_filtradas:
            continue
        quantidade = _decimal(item.quantidade)
        cmc = _cmc_item(item, posicoes, posicoes_por_produto)
        if not cmc or not quantidade:
            continue
        codigo = str(
            item.codigo_produto
            or item.codigo_produto_texto
            or item.produto_id
            or item.codigo_item
        )
        produto = agregados[codigo]
        produto["codigo"] = item.codigo_produto_texto or (
            item.produto.codigo if item.produto_id else ""
        ) or str(item.codigo_produto or "")
        produto["familia_codigo"] = codigo_familia
        produto["familia"] = (
            produto_modelo.descricao_familia
            if produto_modelo and produto_modelo.descricao_familia
            else "Sem familia"
        )
        produto["produto"] = (
            item.produto.descricao if item.produto_id else ""
        ) or item.descricao or "Produto nao informado"
        produto["receita"] += _decimal(item.valor_unitario) * quantidade
        produto["custo"] += cmc * quantidade
        produto["desconto"] += _decimal(item.valor_desconto)
        produto["quantidade"] += quantidade
    return list(agregados.values())


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


def _mapa_lucro(linhas):
    maiores = sorted(
        linhas,
        key=lambda item: (item["receita"], item["lucro"], item["margem"]),
        reverse=True,
    )
    maior_receita = max((item["receita"] for item in maiores), default=Decimal("0"))
    itens = []
    for indice, item in enumerate(maiores):
        receita = item["receita"]
        lucro = max(item["lucro"], Decimal("0"))
        custo = max(item["custo"], Decimal("0"))
        receita_barra = float(_porcentagem(receita, maior_receita)) if maior_receita else 0
        lucro_barra = float(_porcentagem(lucro, receita)) if receita else 0
        custo_barra = max(100 - lucro_barra, 0)
        itens.append(
            {
                "produto": item["produto"],
                "codigo": item["codigo"] or "-",
                "familia_codigo": item["familia_codigo"],
                "familia": item["familia"],
                "receita_fmt": _formatar_moeda(receita),
                "lucro_fmt": _formatar_moeda(lucro),
                "margem_fmt": _formatar_percentual(item["margem"]),
                "receita_barra": receita_barra,
                "lucro_barra": lucro_barra,
                "custo_barra": custo_barra,
                "faixa": item["faixa"],
                "padrao_visivel": indice < 5,
            }
        )
    return itens


def _familias_mapa(linhas):
    familias = {}
    for item in linhas:
        codigo = item["familia_codigo"]
        if not codigo:
            continue
        familias[codigo] = item["familia"]
    return [
        {"codigo": codigo, "nome": nome}
        for codigo, nome in sorted(familias.items(), key=lambda item: item[1])
    ]


def margem_rentabilidade_comercial(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    produtos_selecionados=None,
    familias_selecionadas=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    inicio_anterior, fim_anterior = _periodo_anterior(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    produtos = _normalizar_filtro_composto(produtos_selecionados or [])
    familias = _normalizar_filtro_composto(familias_selecionadas or [])
    pedidos = _query_pedidos(inicio, fim, empresas_ids, projetos)
    pedidos_anteriores = _query_pedidos(inicio_anterior, fim_anterior, empresas_ids, projetos)

    linhas = _preparar_linhas(_itens_agregados(pedidos, produtos, familias))
    linhas_anteriores = _preparar_linhas(
        _itens_agregados(pedidos_anteriores, produtos, familias)
    )
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
                "valor_completo": _formatar_percentual(margem_bruta),
                "subvalor": f"{_formatar_pp(margem_bruta - margem_anterior)} vs. periodo anterior",
                "tom": "positive" if margem_bruta >= margem_anterior else "negative",
            },
            {
                "titulo": "Receita total",
                "valor": _formatar_moeda_curta(receita_total),
                "valor_completo": _formatar_moeda(receita_total),
                "subvalor": "periodo selecionado",
                "tom": "neutral",
            },
            {
                "titulo": "Produtos c/ mg negativa",
                "valor": str(produtos_negativos),
                "valor_completo": str(produtos_negativos),
                "subvalor": "requerem acao imediata" if produtos_negativos else "sem margem negativa",
                "tom": "negative" if produtos_negativos else "positive",
            },
            {
                "titulo": "Desconto medio",
                "valor": _formatar_percentual(desconto_medio),
                "valor_completo": _formatar_percentual(desconto_medio),
                "subvalor": "sobre a receita bruta",
                "tom": "neutral",
            },
        ],
        "mapa_lucro": _mapa_lucro(linhas),
        "familias_mapa": _familias_mapa(linhas),
        "top_rentaveis": _ranking(linhas, True),
        "bottom_urgente": _ranking(linhas, False),
    }
