"""Curva ABC de fornecedores baseada nos pedidos de compra OMIE."""

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from apps.empresas.models import PedidoCompraItemOmie


ETAPAS_PEDIDO_CURVA_ABC = ("10", "15")


def _numero(valor):
    return Decimal(str(valor or 0))


def _formatar_percentual(valor, casas=1):
    quantizador = Decimal("1") if casas == 0 else Decimal("0.1")
    texto = str(
        Decimal(str(valor)).quantize(quantizador, rounding=ROUND_HALF_UP)
    ).replace(".", ",")
    return f"{texto}%"


def _formatar_moeda(valor):
    valor = _numero(valor)
    if valor >= Decimal("1000000"):
        return f"R$ {str((valor / Decimal('1000000')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)).replace('.', ',')} mi"
    if valor >= Decimal("1000"):
        mil = (valor / Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"R$ {str(mil).replace('.', ',')} mil"
    return f"R$ {str(valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)).replace('.', ',')}"


def _nome_fornecedor(pedido, codigo_fornecedor):
    fornecedor = pedido.fornecedor
    if fornecedor:
        return (
            fornecedor.razao_social
            or fornecedor.nome_fantasia
            or str(codigo_fornecedor or "")
        )
    return str(codigo_fornecedor or "Fornecedor nao informado")


def _resolver_datas(periodo_selecionado, data_inicio, data_fim):
    if data_inicio and data_fim:
        return data_inicio, data_fim
    partes = str(periodo_selecionado or "").split("-")
    try:
        if len(partes) == 3 and partes[0] == "mes":
            ano = int(partes[1])
            mes = int(partes[2])
            return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
        if len(partes) == 3 and partes[0] == "tri":
            ano = int(partes[1])
            trimestre = int(partes[2])
            mes_inicial = (trimestre - 1) * 3 + 1
            mes_final = mes_inicial + 2
            return (
                date(ano, mes_inicial, 1),
                date(ano, mes_final, monthrange(ano, mes_final)[1]),
            )
        if len(partes) == 2 and partes[0] == "ano":
            ano = int(partes[1])
            return date(ano, 1, 1), date(ano, 12, 31)
    except (TypeError, ValueError):
        return data_inicio, data_fim
    return data_inicio, data_fim


def _query_itens(data_inicio, data_fim, empresas_ids, projetos):
    queryset = (
        PedidoCompraItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            pedido__ativo_omie=True,
            pedido__etapa__in=ETAPAS_PEDIDO_CURVA_ABC,
        )
        .select_related("pedido", "pedido__fornecedor")
        .order_by("pedido__data_previsao", "pedido__codigo_pedido", "codigo_item")
    )
    if data_inicio and data_fim:
        queryset = queryset.filter(pedido__data_previsao__range=(data_inicio, data_fim))
    if projetos:
        queryset = queryset.filter(pedido__projeto__in=projetos)
    return list(queryset)


def _valor_item(item):
    return _numero(item.valor_total or item.valor_mercadoria)


def _classe_por_acumulado(acumulado):
    if acumulado <= Decimal("80"):
        return "A", "a"
    if acumulado <= Decimal("95"):
        return "B", "b"
    return "C", "c"


def _pontos_curva(fornecedores):
    if not fornecedores:
        return ""
    largura_inicio = Decimal("16")
    largura_fim = Decimal("510")
    altura_base = Decimal("186")
    altura_topo = Decimal("5")
    intervalo = largura_fim - largura_inicio
    divisor = max(len(fornecedores) - 1, 1)

    pontos = []
    for indice, fornecedor in enumerate(fornecedores):
        x = largura_inicio + (intervalo * Decimal(indice) / Decimal(divisor))
        y = altura_base - (
            Decimal(str(fornecedor["acumulado_num"]))
            / Decimal("100")
            * (altura_base - altura_topo)
        )
        pontos.append(f"{int(x.quantize(Decimal('1')))}," f"{int(y.quantize(Decimal('1')))}")
    return " ".join(pontos)


def _classes(fornecedores, total_gasto):
    total_fornecedores = len(fornecedores)
    por_classe = {
        "A": {"classe": "A", "quantidade": 0, "valor": Decimal("0"), "tom": "a"},
        "B": {"classe": "B", "quantidade": 0, "valor": Decimal("0"), "tom": "b"},
        "C": {"classe": "C", "quantidade": 0, "valor": Decimal("0"), "tom": "c"},
    }
    for fornecedor in fornecedores:
        classe = por_classe[fornecedor["classe"]]
        classe["quantidade"] += 1
        classe["valor"] += fornecedor["valor_num"]

    distribuicao = []
    for classe in por_classe.values():
        percentual_fornecedores = (
            classe["quantidade"] / total_fornecedores * 100
            if total_fornecedores
            else Decimal("0")
        )
        percentual_valor = (
            classe["valor"] / total_gasto * Decimal("100")
            if total_gasto
            else Decimal("0")
        )
        distribuicao.append(
            {
                "classe": classe["classe"],
                "fornecedores": (
                    f"{classe['quantidade']} fornecedores "
                    f"({_formatar_percentual(percentual_fornecedores, 0)})"
                ),
                "valor": f"{_formatar_percentual(percentual_valor, 0)} do valor",
                "tom": classe["tom"],
            }
        )
    return distribuicao


def curva_abc_fornecedores_compras(
    empresa,
    periodo_selecionado,
    data_inicio,
    data_fim,
    empresas_ids,
    projetos,
):
    data_inicio, data_fim = _resolver_datas(periodo_selecionado, data_inicio, data_fim)
    gastos = defaultdict(lambda: {"valor": Decimal("0"), "nome": "", "pedido": None})

    for item in _query_itens(data_inicio, data_fim, empresas_ids, projetos):
        valor = _valor_item(item)
        if valor <= 0:
            continue
        codigo = item.pedido.codigo_fornecedor or item.pedido.fornecedor_id or 0
        dados = gastos[codigo]
        dados["valor"] += valor
        if not dados["nome"]:
            dados["nome"] = _nome_fornecedor(item.pedido, codigo)
            dados["pedido"] = item.pedido

    total_gasto = sum((dados["valor"] for dados in gastos.values()), Decimal("0"))
    ordenados = sorted(gastos.values(), key=lambda dados: dados["valor"], reverse=True)
    maior_valor = ordenados[0]["valor"] if ordenados else Decimal("0")

    fornecedores = []
    acumulado = Decimal("0")
    for dados in ordenados:
        individual = (
            dados["valor"] / total_gasto * Decimal("100")
            if total_gasto
            else Decimal("0")
        )
        acumulado += individual
        classe, tom = _classe_por_acumulado(acumulado)
        altura = (
            int((dados["valor"] / maior_valor * Decimal("100")).quantize(Decimal("1")))
            if maior_valor
            else 0
        )
        fornecedores.append(
            {
                "nome": dados["nome"],
                "valor": _formatar_moeda(dados["valor"]),
                "valor_num": dados["valor"],
                "individual": _formatar_percentual(individual),
                "individual_num": individual,
                "acumulado": _formatar_percentual(acumulado),
                "acumulado_num": min(acumulado, Decimal("100")),
                "classe": classe,
                "altura": max(altura, 6),
                "tom": tom,
            }
        )

    top10 = sum(
        (fornecedor["valor_num"] for fornecedor in fornecedores[:10]),
        Decimal("0"),
    )
    concentracao_top10 = (
        top10 / total_gasto * Decimal("100") if total_gasto else Decimal("0")
    )

    return {
        "gasto_total": _formatar_moeda(total_gasto),
        "fornecedores_ativos": len(fornecedores),
        "concentracao_top10": _formatar_percentual(concentracao_top10, 0),
        "fornecedores_classe_a": sum(
            1 for fornecedor in fornecedores if fornecedor["classe"] == "A"
        ),
        "fornecedores": fornecedores,
        "curva_pontos": _pontos_curva(fornecedores),
        "classes": _classes(fornecedores, total_gasto),
    }
