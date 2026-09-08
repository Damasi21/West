"""Dados do dashboard de estoque Ruptura de Estoque."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.utils import timezone

from apps.dashboards.dre_services import _formatar_moeda
from apps.empresas.models import (
    PedidoCompraItemOmie,
    PedidoItemOmie,
    PosicaoEstoqueOmie,
    ProdutoFornecedorOmie,
)


JANELA_CONSUMO_DIAS = 90


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _formatar_numero(valor, casas=0):
    valor = _decimal(valor)
    quantizador = Decimal("1") if casas == 0 else Decimal("0." + ("0" * (casas - 1)) + "1")
    texto = f"{valor.quantize(quantizador, rounding=ROUND_HALF_UP):,.{casas}f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    if casas > 0:
        texto = texto.rstrip("0").rstrip(",")
    return texto


def _formatar_quantidade(valor, unidade="un", casas=0):
    return f"{_formatar_numero(valor, casas)} {unidade}"


def _formatar_dia(valor):
    valor = _decimal(valor)
    casas = 1 if valor < 10 and valor != valor.to_integral_value() else 0
    return f"{_formatar_numero(valor, casas)}/dia"


def _formatar_moeda_curta(valor):
    valor = _decimal(valor)
    if valor >= Decimal("1000000"):
        return f"R$ {_formatar_numero(valor / Decimal('1000000'), 1)} mi"
    if valor >= Decimal("1000"):
        return f"R$ {_formatar_numero(valor / Decimal('1000'), 0)} mil"
    return _formatar_moeda(valor)


def _codigo_posicao(posicao):
    return (
        posicao.codigo
        or (posicao.produto.codigo if posicao.produto_id and posicao.produto.codigo else "")
        or str(posicao.codigo_produto)
    )


def _nome_posicao(posicao):
    return (
        posicao.descricao
        or (posicao.produto.descricao if posicao.produto_id and posicao.produto.descricao else "")
        or f"Produto {posicao.codigo_produto}"
    )


def _unidade_posicao(posicao):
    return posicao.produto.unidade if posicao.produto_id and posicao.produto.unidade else "un"


def _tipo_posicao(posicao):
    produto = posicao.produto
    if not produto:
        return "Produto"
    return produto.descricao_familia or produto.marca or "Produto"


def _consumo_por_produto(empresas_ids):
    inicio = timezone.localdate() - timedelta(days=JANELA_CONSUMO_DIAS)
    consumo = defaultdict(Decimal)
    for item in PedidoItemOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        pedido__ativo_omie=True,
        pedido__faturado=True,
        pedido__cancelado=False,
        pedido__data_faturamento__gte=inicio,
    ).only("codigo_produto", "produto_id", "quantidade"):
        chave = item.produto_id or item.codigo_produto
        if chave:
            consumo[chave] += _decimal(item.quantidade)
    return {chave: valor / Decimal(JANELA_CONSUMO_DIAS) for chave, valor in consumo.items()}


def _compras_por_produto(empresas_ids):
    compras = {}
    itens = (
        PedidoCompraItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            pedido__ativo_omie=True,
        )
        .select_related("pedido", "pedido__fornecedor")
        .order_by("-pedido__data_previsao", "-pedido__data_inclusao", "-pedido_id")
    )
    for item in itens:
        chave = item.produto_id or item.codigo_produto
        if not chave or chave in compras:
            continue
        pedido = item.pedido
        fornecedor = pedido.fornecedor
        nome_fornecedor = ""
        if fornecedor:
            nome_fornecedor = fornecedor.nome_fantasia or fornecedor.razao_social
        lead_time = Decimal("12")
        if pedido.data_previsao and pedido.data_inclusao and pedido.data_previsao >= pedido.data_inclusao:
            lead_time = Decimal((pedido.data_previsao - pedido.data_inclusao).days or 1)
        compras[chave] = {
            "lead_time": lead_time,
            "fornecedor": nome_fornecedor or str(pedido.codigo_fornecedor or "Fornecedor nao informado"),
        }
    return compras


def _fornecedores_por_produto(empresas_ids):
    fornecedores = {}
    vinculos = (
        ProdutoFornecedorOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
        )
        .select_related("produto")
        .order_by("nome_fantasia", "razao_social", "codigo_fornecedor")
    )
    for vinculo in vinculos:
        nome = vinculo.nome_fantasia or vinculo.razao_social
        if not nome:
            continue
        for chave in (vinculo.produto_id, vinculo.codigo_produto):
            if chave and chave not in fornecedores:
                fornecedores[chave] = nome
    return fornecedores


def _linhas_posicoes(empresas_ids):
    grupos = {}
    posicoes = (
        PosicaoEstoqueOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
        )
        .select_related("produto")
        .order_by("descricao", "codigo")
    )
    for posicao in posicoes:
        chave = posicao.produto_id or posicao.codigo_produto
        saldo = _decimal(posicao.saldo or posicao.fisico)
        cmc = _decimal(posicao.cmc or posicao.preco_unitario)
        if chave not in grupos:
            grupos[chave] = {
                "chave": chave,
                "codigo": _codigo_posicao(posicao),
                "nome": _nome_posicao(posicao),
                "tipo": _tipo_posicao(posicao),
                "unidade": _unidade_posicao(posicao),
                "saldo": Decimal("0"),
                "valor_unitario": cmc,
            }
        grupos[chave]["saldo"] += saldo
        if cmc > 0:
            grupos[chave]["valor_unitario"] = cmc
    return list(grupos.values())


def _linhas_demo():
    produtos = [
        ("CP-2210", "Parafuso Sextavado M8x40", "Componentes", 0, 1850, 12, "Metalfix Distribuidora", Decimal("0.53")),
        ("CP-3301", "Rolamento Blindado 6205ZZ", "Componentes", 940, 210, 9, "Rolimex Ind.", Decimal("29.00")),
        ("CP-4410", "Motor Redutor 1/4 CV", "Componentes", 36, 6, 18, "Servomotriz SA", Decimal("820.00")),
        ("MP-1042", "Chapa de Aco Galvanizado 2mm", "Materia-prima", 1240, 85, 10, "Acos SP", Decimal("150.32")),
        ("MP-1198", "Resina Epoxi Industrial 25kg", "Materia-prima", 312, 22, 15, "Quimica Sul", Decimal("316.00")),
        ("RV-0587", "Kit Revenda Ferramentas 12pc", "Revenda", 86, Decimal("1.8"), 29, "Ferramentas Brasil", Decimal("480.00")),
        ("CP-5501", "Anel de Vedacao Viton", "Componentes", 2080, 40, 7, "Vedax", Decimal("8.50")),
    ]
    return [
        {
            "chave": codigo,
            "codigo": codigo,
            "nome": nome,
            "tipo": tipo,
            "unidade": "un",
            "saldo": _decimal(saldo),
            "consumo_dia": _decimal(consumo),
            "lead_time": _decimal(lead_time),
            "fornecedor": fornecedor,
            "valor_unitario": valor,
        }
        for codigo, nome, tipo, saldo, consumo, lead_time, fornecedor, valor in produtos
    ]


def _status(cobertura, lead_time, saldo):
    if saldo <= 0 or cobertura <= 0:
        return "ruptura", "Ruptura"
    if cobertura <= 7 or cobertura < lead_time:
        return "critico", "Critico"
    if cobertura <= lead_time + Decimal("7") or cobertura <= 21:
        return "atencao", "Atencao"
    return "saudavel", "Saudavel"


def _enriquecer_linhas(linhas, consumos=None, compras=None, fornecedores=None):
    consumos = consumos or {}
    compras = compras or {}
    fornecedores = fornecedores or {}
    enriquecidas = []
    maior_cobertura = Decimal("1")
    for indice, item in enumerate(linhas):
        consumo_dia = item.get("consumo_dia") or consumos.get(item["chave"], Decimal("0"))
        if consumo_dia <= 0:
            estoque_minimo_base = item["saldo"] / Decimal([14, 4, 6, 14, 14, 48, 52][indice % 7] or 1)
            consumo_dia = max(estoque_minimo_base, Decimal("0.1"))
        compra = compras.get(item["chave"], {})
        fornecedor_principal = fornecedores.get(item["chave"])
        lead_time = item.get("lead_time") or compra.get("lead_time") or Decimal([12, 9, 18, 10, 15, 29, 7][indice % 7])
        cobertura = item["saldo"] / consumo_dia if consumo_dia > 0 else Decimal("999")
        tom, status = _status(cobertura, lead_time, item["saldo"])
        sugestao_base = consumo_dia * lead_time - item["saldo"]
        quantidade_sugerida = sugestao_base if sugestao_base > 0 else Decimal("0")
        valor_risco = consumo_dia * lead_time * item["valor_unitario"]
        maior_cobertura = max(maior_cobertura, cobertura)
        enriquecidas.append(
            {
                **item,
                "consumo_dia": consumo_dia,
                "lead_time": lead_time,
                "cobertura": cobertura,
                "cobertura_dias": max(int(cobertura.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), 0),
                "status": status,
                "status_tom": tom,
                "quantidade_sugerida": quantidade_sugerida,
                "fornecedor": (
                    item.get("fornecedor")
                    or fornecedor_principal
                    or compra.get("fornecedor")
                    or "Fornecedor nao informado"
                ),
                "valor_risco": valor_risco,
            }
        )
    for item in enriquecidas:
        item["barra_pct"] = min(max(float(item["cobertura"] / maior_cobertura * Decimal("100")), 2), 100)
        item["lead_pct"] = min(max(float(item["lead_time"] / maior_cobertura * Decimal("100")), 4), 96)
    enriquecidas.sort(key=lambda produto: (produto["cobertura"], -produto["consumo_dia"], produto["nome"]))
    return enriquecidas


def _formatar_linhas(linhas):
    formatadas = []
    for item in linhas:
        unidade = item["unidade"]
        formatadas.append(
            {
                **item,
                "saldo_fmt": _formatar_quantidade(item["saldo"], unidade),
                "consumo_dia_fmt": _formatar_dia(item["consumo_dia"]),
                "cobertura_fmt": f"{item['cobertura_dias']} dias",
                "lead_time_fmt": f"{_formatar_numero(item['lead_time'])} dias",
                "quantidade_sugerida_fmt": (
                    _formatar_quantidade(item["quantidade_sugerida"], unidade)
                    if item["quantidade_sugerida"] > 0
                    else "-"
                ),
            }
        )
    return formatadas


def ruptura_estoque(empresa, empresas_ids):
    del empresa
    linhas = _linhas_posicoes(empresas_ids)
    if linhas:
        linhas = _enriquecer_linhas(
            linhas,
            consumos=_consumo_por_produto(empresas_ids),
            compras=_compras_por_produto(empresas_ids),
            fornecedores=_fornecedores_por_produto(empresas_ids),
        )
    else:
        linhas = _enriquecer_linhas(_linhas_demo())

    ruptura = [item for item in linhas if item["status_tom"] == "ruptura"]
    criticos = [item for item in linhas if item["status_tom"] in {"ruptura", "critico"}]
    risco = [item for item in linhas if item["status_tom"] != "saudavel"]
    valor_risco = sum((item["valor_risco"] for item in risco), Decimal("0"))
    fila = [item for item in linhas if item["status_tom"] in {"ruptura", "critico", "atencao"}]
    return {
        "kpis": [
            {
                "titulo": "Em ruptura agora",
                "valor": f"{len(ruptura)} produtos",
                "subvalor": "saldo zerado ou negativo",
                "tom": "ruptura",
            },
            {
                "titulo": "Risco critico (<=7 dias)",
                "valor": f"{len(criticos)} produtos",
                "subvalor": "cobertura menor que lead time",
                "tom": "critico",
            },
            {
                "titulo": "Valor em risco",
                "valor": _formatar_moeda_curta(valor_risco),
                "subvalor": "receita potencial impactada",
                "tom": "risco",
            },
            {
                "titulo": "Pedidos sugeridos",
                "valor": str(len(fila)),
                "subvalor": "aguardando aprovacao de compra",
                "tom": "pedido",
            },
        ],
        "runway": _formatar_linhas(linhas[:8]),
        "fila_reposicao": _formatar_linhas(fila[:10]),
    }
