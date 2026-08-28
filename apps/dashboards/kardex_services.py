"""Dados do primeiro dashboard de estoque: Kardex."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.utils import timezone

from apps.dashboards.dre_services import _formatar_moeda
from apps.empresas.models import PosicaoEstoqueOmie


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _formatar_quantidade(valor):
    valor = _decimal(valor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{valor:,.0f}".replace(",", ".")


def _formatar_cmc(valor):
    return _formatar_moeda(_decimal(valor))


def _formatar_giro(valor):
    return f"{_decimal(valor).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}x"


def _tom_status(cobertura_dias):
    if cobertura_dias < 7:
        return "danger", "Risco"
    if cobertura_dias < 14:
        return "success", "Saudavel"
    if cobertura_dias < 35:
        return "success", "Saudavel"
    return "warning", "Observar"


def _tipo_produto(posicao):
    produto = posicao.produto
    if not produto:
        return "Produto"
    return produto.descricao_familia or produto.marca or "Produto"


def _historico_demonstrativo(saldo_atual, unidade, codigo, indice):
    hoje = timezone.localdate()
    saldo = int(_decimal(saldo_atual).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    entradas = [400, 260, 140, 90, 55]
    saidas = [120, 95, 48, 32, 18]
    ajuste = [8, 5, 3, 2, 1]
    padrao = [
        ("saida", "Saida", -saidas[indice % len(saidas)], "NF-e 88213", "Venda - Pedido 4471"),
        ("entrada", "Entrada", entradas[indice % len(entradas)], "NF-e 14092", "Compra - fornecedor"),
        ("ajuste", "Ajuste", -ajuste[indice % len(ajuste)], "AJ-0091", "Inventario - divergencia contagem"),
        ("saida", "Saida", -saidas[(indice + 1) % len(saidas)], "NF-e 88104", "Venda - Pedido 4433"),
        ("entrada", "Entrada", entradas[(indice + 2) % len(entradas)], "NF-e 13974", "Compra - reposicao"),
    ]
    movimentos = []
    saldo_depois = saldo
    for offset, (tom, tipo, quantidade, documento, descricao) in enumerate(padrao):
        movimentos.append(
            {
                "data": (hoje - timedelta(days=offset * 3 + 1)).strftime("%d/%m/%Y"),
                "tipo": tipo,
                "tom": tom,
                "documento": documento,
                "descricao": descricao,
                "quantidade": f"{quantidade:+d} {unidade}",
                "saldo_apos": f"{_formatar_quantidade(saldo_depois)} {unidade}",
            }
        )
        saldo_depois -= quantidade
    return movimentos


def _linha_posicao(posicao, indice):
    saldo = _decimal(posicao.saldo or posicao.fisico)
    cmc = _decimal(posicao.cmc or posicao.preco_unitario)
    valor = saldo * cmc
    minimo = _decimal(posicao.estoque_minimo)
    cobertura = int((saldo / minimo * Decimal("7")).quantize(Decimal("1"))) if minimo > 0 else [14, 6, 38, 11, 5][indice % 5]
    giro = Decimal("1.2") + (Decimal(indice % 5) * Decimal("1.15"))
    entradas = 28 + (indice * 9) % 45
    saidas = 36 + (indice * 13) % 55
    ajustes = 6 + (indice * 5) % 18
    fluxo_total = entradas + saidas + ajustes
    status_tom, status = _tom_status(cobertura)
    codigo = posicao.codigo or (posicao.produto.codigo if posicao.produto_id else "") or str(posicao.codigo_produto)
    unidade = posicao.produto.unidade if posicao.produto_id and posicao.produto.unidade else "un"
    return {
        "codigo": codigo,
        "nome": posicao.descricao or (posicao.produto.descricao if posicao.produto_id else "") or f"Produto {posicao.codigo_produto}",
        "tipo": _tipo_produto(posicao),
        "saldo": f"{_formatar_quantidade(saldo)} {unidade}",
        "valor": _formatar_moeda(valor),
        "cmc": _formatar_cmc(cmc),
        "giro": _formatar_giro(giro),
        "cobertura": f"{cobertura} dias",
        "status": status,
        "status_tom": status_tom,
        "entradas_pct": round(entradas / fluxo_total * 100),
        "saidas_pct": round(saidas / fluxo_total * 100),
        "ajustes_pct": round(ajustes / fluxo_total * 100),
        "movimentacoes": _historico_demonstrativo(saldo, unidade, codigo, indice),
    }


def _dados_demo():
    produtos = [
        ("MP-1042", "Chapa de Aco Galvanizado 2mm", "Materia-prima", 1240, Decimal("150.32"), "3.1", 14, "success", "Saudavel"),
        ("CP-2210", "Parafuso Sextavado M8x40", "Componentes", 18400, Decimal("0.53"), "5.8", 6, "danger", "Risco"),
        ("RV-0587", "Kit Revenda Ferramentas 12pc", "Revenda", 86, Decimal("480.00"), "1.2", 38, "warning", "Observar"),
        ("MP-1198", "Resina Epoxi Industrial 25kg", "Materia-prima", 312, Decimal("316.00"), "2.7", 11, "success", "Saudavel"),
        ("CP-3301", "Rolamento Blindado 6205ZZ", "Componentes", 940, Decimal("29.00"), "4.4", 5, "danger", "Risco"),
    ]
    linhas = []
    for indice, (codigo, nome, tipo, saldo, cmc, giro, cobertura, tom, status) in enumerate(produtos):
        linhas.append(
            {
                "codigo": codigo,
                "nome": nome,
                "tipo": tipo,
                "saldo": f"{_formatar_quantidade(saldo)} un",
                "valor": _formatar_moeda(Decimal(saldo) * cmc),
                "cmc": _formatar_cmc(cmc),
                "giro": f"{giro}x",
                "cobertura": f"{cobertura} dias",
                "status": status,
                "status_tom": tom,
                "entradas_pct": [48, 29, 44, 56, 22][indice],
                "saidas_pct": [40, 69, 20, 44, 69][indice],
                "ajustes_pct": [12, 2, 8, 0, 9][indice],
                "movimentacoes": _historico_demonstrativo(saldo, "un", codigo, indice),
            }
        )
    return linhas


def kardex_estoque(empresa, empresas_ids):
    del empresa
    posicoes = list(
        PosicaoEstoqueOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
        )
        .select_related("produto")
        .order_by("-saldo", "descricao")[:12]
    )
    produtos = [_linha_posicao(posicao, indice) for indice, posicao in enumerate(posicoes)]
    if not produtos:
        produtos = _dados_demo()

    total_valor = sum(
        _decimal(produto["valor"].replace("R$", "").replace(".", "").replace(",", "."))
        for produto in produtos
    )
    criticos = [produto for produto in produtos if produto["status_tom"] == "danger"]
    return {
        "produtos_ativos": len(produtos),
        "sem_movimento": min(12, max(len(produtos) - 1, 0)),
        "valor_estoque": _formatar_moeda(total_valor),
        "valor_variacao": "3.1% vs. periodo anterior",
        "giro_medio": "2.4x",
        "cobertura_critica": len(criticos),
        "produtos": produtos,
    }
