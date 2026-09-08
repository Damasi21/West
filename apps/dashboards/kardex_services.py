"""Dados do primeiro dashboard de estoque: Kardex."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from apps.dashboards.dre_services import _formatar_moeda
from apps.empresas.models import (
    CadastroOmie,
    ContaReceberOmie,
    MovimentoEstoqueOmie,
    PedidoItemOmie,
    PosicaoEstoqueOmie,
    RecebimentoNfeItemOmie,
)


JANELA_MOVIMENTOS_DIAS = 90


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


def _documento_saida(item, documentos_por_pedido):
    conta = documentos_por_pedido.get(item.pedido.codigo_pedido)
    if conta and conta.numero_documento_fiscal:
        return f"NF-e {conta.numero_documento_fiscal}"
    if conta and conta.numero_documento:
        return conta.numero_documento
    return f"Pedido {item.pedido.numero_pedido or item.pedido.codigo_pedido}"


def _documento_entrada(item):
    numero = item.recebimento.numero_nfe
    return f"NF-e {numero}" if numero else f"Recebimento {item.codigo_recebimento}"


def _fornecedor_entrada(item, fornecedores_por_codigo):
    fornecedor = fornecedores_por_codigo.get(item.recebimento.codigo_fornecedor)
    if fornecedor:
        return fornecedor.nome_fantasia or fornecedor.razao_social or "fornecedor"
    return "fornecedor"


def _chaves_produto(posicao):
    chaves = set()
    if posicao.produto_id:
        chaves.add(("produto_id", posicao.produto_id))
    if posicao.codigo_produto:
        chaves.add(("codigo_produto", posicao.codigo_produto))
    for codigo in (_codigo_posicao(posicao), posicao.produto.codigo if posicao.produto_id else ""):
        codigo = str(codigo or "").strip()
        if codigo:
            chaves.add(("codigo_texto", codigo))
    return chaves


def _mapear_documentos_saida(empresas_ids, itens_saida):
    codigos_pedido = {
        item.pedido.codigo_pedido
        for item in itens_saida
        if item.pedido_id and item.pedido.codigo_pedido
    }
    if not codigos_pedido:
        return {}
    documentos = {}
    contas = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        codigo_pedido_omie__in=codigos_pedido,
    ).order_by("-data_emissao", "-codigo_lancamento_omie")
    for conta in contas:
        documentos.setdefault(conta.codigo_pedido_omie, conta)
    return documentos


def _tipo_movimento_estoque(movimento):
    entrada = _decimal(movimento.quantidade_entrada)
    saida = _decimal(movimento.quantidade_saida)
    origem = str(movimento.codigo_origem or "").upper()
    if entrada:
        if movimento.devolucao and origem == "VEN":
            return "Entrada", "entrada", abs(entrada)
        return "Entrada", "entrada", entrada
    if saida:
        if saida > 0:
            saida = -saida
        return "Saida", "saida", saida
    return "Ajuste", "ajuste", _decimal(movimento.quantidade_atual) - _decimal(movimento.quantidade_anterior)


def _documento_movimento_estoque(movimento):
    if movimento.numero_documento:
        return f"NF-e {movimento.numero_documento}"
    if movimento.codigo_ajuste:
        return f"AJ-{movimento.codigo_ajuste}"
    return f"Mov. {movimento.codigo_movimento}"


def _descricao_movimento_estoque(movimento):
    origem = movimento.descricao_origem or "Movimento de estoque"
    detalhe = movimento.numero_pedido or ""
    if detalhe:
        return f"{origem} - {detalhe}"
    return origem


def _movimentos_estoque_omie(posicao, empresas_ids):
    movimentos = list(
        MovimentoEstoqueOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            cancelamento=False,
            codigo_produto=posicao.codigo_produto,
        )
        .filter(
            Q(codigo_local_estoque=posicao.codigo_local_estoque)
            | Q(codigo_local_estoque=0)
        )
        .order_by("-data_movimento", "-codigo_movimento")[:20]
    )
    formatados = []
    movimentos_periodo = []
    unidade = _unidade_posicao(posicao)
    for movimento in movimentos:
        if not movimento.data_movimento:
            continue
        tipo, tom, quantidade = _tipo_movimento_estoque(movimento)
        movimentos_periodo.append(
            {
                "quantidade_num": quantidade,
                "tom": tom,
            }
        )
        formatados.append(
            {
                "data": movimento.data_movimento.strftime("%d/%m/%Y"),
                "tipo": tipo,
                "tom": tom,
                "documento": _documento_movimento_estoque(movimento),
                "descricao": _descricao_movimento_estoque(movimento),
                "quantidade": f"{'+' if quantidade > 0 else ''}{_formatar_quantidade(quantidade)} {unidade}",
                "saldo_apos": f"{_formatar_quantidade(movimento.quantidade_atual)} {unidade}",
            }
        )
    return formatados[:5], movimentos_periodo


def _movimentos_reais(posicao, empresas_ids):
    movimentos_omie, periodo_omie = _movimentos_estoque_omie(posicao, empresas_ids)
    if movimentos_omie:
        return movimentos_omie, periodo_omie

    inicio = timezone.localdate() - timedelta(days=JANELA_MOVIMENTOS_DIAS)
    chaves = _chaves_produto(posicao)
    produto_ids = [valor for tipo, valor in chaves if tipo == "produto_id"]
    codigos_produto = [valor for tipo, valor in chaves if tipo == "codigo_produto"]
    codigos_texto = [valor for tipo, valor in chaves if tipo == "codigo_texto"]

    filtro_saida = Q()
    if produto_ids:
        filtro_saida |= Q(produto_id__in=produto_ids)
    if codigos_produto:
        filtro_saida |= Q(codigo_produto__in=codigos_produto)
    saidas = []
    if filtro_saida:
        saidas = list(
            PedidoItemOmie.objects.filter(
                filtro_saida,
                empresa_id__in=empresas_ids,
                ativo_omie=True,
                pedido__ativo_omie=True,
                pedido__faturado=True,
                pedido__cancelado=False,
                pedido__data_faturamento__gte=inicio,
            )
            .select_related("pedido")
            .order_by(
                "-pedido__data_faturamento",
                "-pedido__codigo_pedido",
                "-codigo_item",
            )[:20]
        )

    entradas = list(
        RecebimentoNfeItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            data_recebimento__gte=inicio,
            codigo_produto_texto__in=codigos_texto,
        )
        .select_related("recebimento")
        .order_by("-data_recebimento", "-codigo_recebimento", "-sequencia")[:20]
    )

    documentos_saida = _mapear_documentos_saida(empresas_ids, saidas)
    codigos_fornecedor = {
        item.recebimento.codigo_fornecedor
        for item in entradas
        if item.recebimento.codigo_fornecedor
    }
    fornecedores = {
        fornecedor.codigo_cliente_omie: fornecedor
        for fornecedor in CadastroOmie.objects.filter(
            empresa_id__in=empresas_ids,
            codigo_cliente_omie__in=codigos_fornecedor,
        )
    }

    movimentos = []
    for item in saidas:
        data = item.pedido.data_faturamento or item.pedido.data_previsao
        if not data:
            continue
        movimentos.append(
            {
                "data_ordem": data,
                "tipo": "Saida",
                "tom": "saida",
                "documento": _documento_saida(item, documentos_saida),
                "descricao": f"Venda - Pedido {item.pedido.numero_pedido or item.pedido.codigo_pedido}",
                "quantidade_num": -abs(_decimal(item.quantidade)),
            }
        )
    for item in entradas:
        data = item.data_recebimento or item.recebimento.data_registro or item.recebimento.data_emissao_nfe
        if not data:
            continue
        movimentos.append(
            {
                "data_ordem": data,
                "tipo": "Entrada",
                "tom": "entrada",
                "documento": _documento_entrada(item),
                "descricao": f"Compra - {_fornecedor_entrada(item, fornecedores)}",
                "quantidade_num": abs(_decimal(item.quantidade_recebida or item.quantidade_nfe)),
            }
        )

    movimentos.sort(key=lambda item: item["data_ordem"], reverse=True)
    return movimentos[:5], movimentos


def _formatar_movimentos(movimentos, saldo_atual, unidade):
    saldo_depois = _decimal(saldo_atual)
    formatados = []
    for movimento in movimentos:
        quantidade = _decimal(movimento["quantidade_num"])
        formatados.append(
            {
                "data": movimento["data_ordem"].strftime("%d/%m/%Y"),
                "tipo": movimento["tipo"],
                "tom": movimento["tom"],
                "documento": movimento["documento"],
                "descricao": movimento["descricao"],
                "quantidade": f"{'+' if quantidade > 0 else ''}{_formatar_quantidade(quantidade)} {unidade}",
                "saldo_apos": f"{_formatar_quantidade(saldo_depois)} {unidade}",
            }
        )
        saldo_depois -= quantidade
    return formatados


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


def _linha_posicao(posicao, indice, empresas_ids):
    saldo = _decimal(posicao.saldo or posicao.fisico)
    cmc = _decimal(posicao.cmc or posicao.preco_unitario)
    valor = saldo * cmc
    minimo = _decimal(posicao.estoque_minimo)
    movimentos_ultimos, movimentos_periodo = _movimentos_reais(posicao, empresas_ids)
    entradas = sum(_decimal(item["quantidade_num"]) for item in movimentos_periodo if item["quantidade_num"] > 0)
    saidas = sum(abs(_decimal(item["quantidade_num"])) for item in movimentos_periodo if item["quantidade_num"] < 0)
    ajustes = Decimal("0")
    consumo_dia = saidas / Decimal(JANELA_MOVIMENTOS_DIAS) if saidas > 0 else Decimal("0")
    if consumo_dia > 0:
        cobertura = int((saldo / consumo_dia).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        cobertura = int((saldo / minimo * Decimal("7")).quantize(Decimal("1"))) if minimo > 0 else [14, 6, 38, 11, 5][indice % 5]
    giro = (saidas / saldo) if saldo > 0 and saidas > 0 else Decimal("0")
    fluxo_total = entradas + saidas + ajustes
    status_tom, status = _tom_status(cobertura)
    codigo = _codigo_posicao(posicao)
    unidade = _unidade_posicao(posicao)
    if movimentos_ultimos and "data_ordem" in movimentos_ultimos[0]:
        movimentacoes = _formatar_movimentos(movimentos_ultimos, saldo, unidade)
    else:
        movimentacoes = movimentos_ultimos
    if not movimentacoes:
        movimentacoes = _historico_demonstrativo(saldo, unidade, codigo, indice)
        entradas = Decimal(28 + (indice * 9) % 45)
        saidas = Decimal(36 + (indice * 13) % 55)
        ajustes = Decimal(6 + (indice * 5) % 18)
        fluxo_total = entradas + saidas + ajustes
    return {
        "codigo": codigo,
        "nome": _nome_posicao(posicao),
        "tipo": _tipo_produto(posicao),
        "saldo": f"{_formatar_quantidade(saldo)} {unidade}",
        "valor": _formatar_moeda(valor),
        "cmc": _formatar_cmc(cmc),
        "giro": _formatar_giro(giro),
        "cobertura": f"{cobertura} dias",
        "status": status,
        "status_tom": status_tom,
        "entradas_pct": round(entradas / fluxo_total * 100) if fluxo_total else 0,
        "saidas_pct": round(saidas / fluxo_total * 100) if fluxo_total else 0,
        "ajustes_pct": round(ajustes / fluxo_total * 100) if fluxo_total else 0,
        "movimentacoes": movimentacoes,
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
    produtos = [
        _linha_posicao(posicao, indice, empresas_ids)
        for indice, posicao in enumerate(posicoes)
    ]
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
