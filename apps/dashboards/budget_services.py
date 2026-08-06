"""Calculos do dashboard de Budget de Compras."""

from collections import defaultdict
from decimal import Decimal

from apps.compras.models import BudgetConfiguracaoCompra, BudgetLimiteCompra
from apps.dashboards.dre_services import _formatar_moeda, _intervalo_periodo
from apps.empresas.models import PedidoCompraItemOmie


ROTULOS_DIMENSAO = dict(BudgetConfiguracaoCompra.TipoControle.choices)
PERIODICIDADE_MENSAL = "mensal"
TODOS_MESES = set(range(1, 13))


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_percentual(valor):
    return f"{valor:.0f}%".replace(".", ",")


def _opcoes_dimensao(empresa, empresas_ids):
    configuracoes = BudgetConfiguracaoCompra.objects.filter(
        empresa_id__in=empresas_ids,
    )
    tipos = []
    for configuracao in configuracoes:
        for tipo in configuracao.tipos_selecionados:
            if tipo not in tipos:
                tipos.append(tipo)
    if not tipos:
        try:
            tipos = empresa.budget_compras.tipos_selecionados
        except BudgetConfiguracaoCompra.DoesNotExist:
            tipos = [BudgetConfiguracaoCompra.TipoControle.PRODUTO]
    return [{"valor": tipo, "nome": ROTULOS_DIMENSAO[tipo]} for tipo in tipos]


def _dimensao_valida(dimensao, opcoes):
    valores = [opcao["valor"] for opcao in opcoes]
    if dimensao in valores:
        return dimensao
    return valores[0] if valores else BudgetConfiguracaoCompra.TipoControle.PRODUTO


def _chave_gasto(item, dimensao):
    if dimensao == BudgetConfiguracaoCompra.TipoControle.PRODUTO:
        return (
            str(item.codigo_produto) if item.codigo_produto is not None else "",
            item.produto.descricao if item.produto_id else item.descricao,
        )
    if dimensao == BudgetConfiguracaoCompra.TipoControle.FAMILIA_PRODUTO:
        produto = item.produto
        codigo = produto.codigo_familia if produto else None
        return (
            str(codigo) if codigo is not None else "",
            produto.descricao_familia if produto else "",
        )
    if dimensao == BudgetConfiguracaoCompra.TipoControle.PROJETO:
        pedido = item.pedido
        projeto = pedido.projeto
        return (
            str(pedido.codigo_projeto) if pedido.codigo_projeto is not None else "",
            projeto.nome if projeto else "",
        )
    pedido = item.pedido
    fornecedor = pedido.fornecedor
    nome_fornecedor = ""
    if fornecedor:
        nome_fornecedor = fornecedor.razao_social or fornecedor.nome_fantasia
    return (
        str(pedido.codigo_fornecedor) if pedido.codigo_fornecedor is not None else "",
        nome_fornecedor,
    )


def _gastos_por_referencia(inicio, fim, empresas_ids, dimensao):
    queryset = (
        PedidoCompraItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            pedido__data_previsao__gte=inicio,
            pedido__data_previsao__lte=fim,
        )
        .select_related("pedido", "pedido__projeto", "pedido__fornecedor", "produto")
        .order_by()
    )
    gastos = defaultdict(Decimal)
    nomes = {}
    for item in queryset:
        codigo, nome = _chave_gasto(item, dimensao)
        if not codigo:
            continue
        gastos[codigo] += _decimal(item.valor_total)
        if nome and codigo not in nomes:
            nomes[codigo] = nome
    return gastos, nomes


def _meses_no_periodo(inicio, fim, meses_selecionados=None):
    meses_selecionados = set(meses_selecionados or TODOS_MESES)
    total = 0
    ano = inicio.year
    mes = inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        if mes in meses_selecionados:
            total += 1
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return total


def _periodicidade_limite(limite):
    periodicidades = limite.configuracao.periodicidades_controle or {}
    return periodicidades.get(limite.tipo_controle, "anual")


def _meses_limite(limite):
    meses_controle = limite.configuracao.meses_controle or {}
    meses = meses_controle.get(limite.tipo_controle)
    if not isinstance(meses, list):
        return TODOS_MESES
    selecionados = set()
    for mes in meses:
        try:
            mes_numero = int(mes)
        except (TypeError, ValueError):
            continue
        if 1 <= mes_numero <= 12:
            selecionados.add(mes_numero)
    return selecionados or TODOS_MESES


def budget_compras(
    empresa,
    periodo,
    data_inicio,
    data_fim,
    empresas_ids,
    dimensao="",
):
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    opcoes = _opcoes_dimensao(empresa, empresas_ids)
    dimensao = _dimensao_valida(dimensao, opcoes)
    limites = list(
        BudgetLimiteCompra.objects.filter(
            empresa_id__in=empresas_ids,
            tipo_controle=dimensao,
        )
        .select_related("configuracao")
        .order_by("referencia_nome", "referencia_codigo")
    )
    gastos, nomes_gastos = _gastos_por_referencia(inicio, fim, empresas_ids, dimensao)

    itens = []
    total_budget = Decimal("0")
    total_gasto = Decimal("0")
    status = {
        "ok": 0,
        "atencao": 0,
        "estourado": 0,
    }
    for limite in limites:
        multiplicador = (
            Decimal(_meses_no_periodo(inicio, fim, _meses_limite(limite)))
            if _periodicidade_limite(limite) == PERIODICIDADE_MENSAL
            else Decimal("1")
        )
        budget = _decimal(limite.limite_compra) * multiplicador
        gasto = gastos.get(limite.referencia_codigo, Decimal("0"))
        percentual = (gasto / budget * Decimal("100")) if budget > 0 else Decimal("0")
        if percentual >= 100:
            tom = "danger"
            status["estourado"] += 1
        elif percentual >= 80:
            tom = "warning"
            status["atencao"] += 1
        else:
            tom = "success"
            status["ok"] += 1
        nome = (
            limite.referencia_nome
            or nomes_gastos.get(limite.referencia_codigo)
            or limite.referencia_codigo
        )
        itens.append(
            {
                "codigo": limite.referencia_codigo,
                "nome": nome,
                "budget": budget,
                "budget_fmt": _formatar_moeda(budget),
                "gasto": gasto,
                "gasto_fmt": _formatar_moeda(gasto),
                "saldo": budget - gasto,
                "saldo_fmt": _formatar_moeda(budget - gasto),
                "percentual": float(min(percentual, Decimal("130"))),
                "percentual_fmt": _formatar_percentual(percentual),
                "tom": tom,
            }
        )
        total_budget += budget
        total_gasto += gasto

    itens.sort(
        key=lambda item: (
            item["gasto"] / item["budget"] if item["budget"] else 0
        ),
        reverse=True,
    )
    saldo = total_budget - total_gasto
    percentual_total = (
        total_gasto / total_budget * Decimal("100")
        if total_budget > 0
        else Decimal("0")
    )
    return {
        "dimensao": dimensao,
        "dimensao_rotulo": ROTULOS_DIMENSAO[dimensao],
        "opcoes_dimensao": opcoes,
        "periodo_inicio": inicio,
        "periodo_fim": fim,
        "total_budget": total_budget,
        "total_budget_fmt": _formatar_moeda(total_budget),
        "total_gasto": total_gasto,
        "total_gasto_fmt": _formatar_moeda(total_gasto),
        "saldo": saldo,
        "saldo_fmt": _formatar_moeda(saldo),
        "saldo_tom": "danger" if saldo < 0 else "success",
        "percentual_total": float(min(percentual_total, Decimal("100"))),
        "percentual_total_fmt": _formatar_percentual(percentual_total),
        "total_itens": len(itens),
        "itens_estourados": status["estourado"],
        "status": status,
        "top_itens": itens[:6],
        "itens": itens,
    }
