"""Analise de preco e saving baseada nos recebimentos de NF-e OMIE."""

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from apps.empresas.models import (
    PosicaoEstoqueOmie,
    ProdutoOmie,
    RecebimentoNfeItemOmie,
)


ETAPAS_RECEBIMENTO_PRECO = ("60", "80")


def _numero(valor):
    return Decimal(str(valor or 0))


def _formatar_moeda(valor):
    valor = _numero(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sinal = "-" if valor < 0 else ""
    valor = abs(valor)
    inteiro, decimal = f"{valor:.2f}".split(".")
    partes = []
    while inteiro:
        partes.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"{sinal}R$ {'.'.join(partes)},{decimal}"


def _formatar_percentual(valor):
    return f"{_numero(valor).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


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


def _nao_gera_financeiro(item):
    ajustes = item.item_ajustes or {}
    dados = item.dados_originais or {}
    for origem in (ajustes, dados, dados.get("itensAjustes") or {}):
        if str(origem.get("cNaoGerarFinanceiro") or "").upper() == "S":
            return True
    return False


def _ordem_item(item):
    return (
        item.recebimento.data_emissao_nfe
        or item.data_recebimento
        or item.recebimento.data_registro
        or date.min
    )


def _query_itens(empresas_ids):
    return (
        RecebimentoNfeItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            recebimento__ativo_omie=True,
            recebimento__etapa__in=ETAPAS_RECEBIMENTO_PRECO,
            recebimento__data_emissao_nfe__isnull=False,
            preco_unitario__gt=0,
            quantidade_nfe__gt=0,
        )
        .select_related("recebimento")
        .order_by(
            "recebimento__data_emissao_nfe",
            "codigo_produto_texto",
            "codigo_recebimento",
            "sequencia",
            "pk",
        )
    )


def _produtos_por_codigo(empresas_ids):
    produtos = {}
    for produto in ProdutoOmie.objects.filter(empresa_id__in=empresas_ids, ativo_omie=True):
        for codigo in (produto.codigo, str(produto.codigo_produto or "")):
            codigo = str(codigo or "").strip()
            if codigo and codigo not in produtos:
                produtos[codigo] = produto
    return produtos


def _estoque_atual_por_produto(empresas_ids):
    estoques = {}
    posicoes = (
        PosicaoEstoqueOmie.objects.filter(empresa_id__in=empresas_ids, ativo_omie=True)
        .select_related("produto")
        .order_by("codigo_produto", "-data_posicao", "-pk")
    )
    for posicao in posicoes:
        cmc = _numero(posicao.cmc)
        saldo = _numero(posicao.saldo)
        if cmc <= 0 or saldo <= 0:
            continue
        dados = {"cmc": cmc, "saldo": saldo}
        codigo = str(posicao.codigo or "").strip()
        codigo_produto = str(posicao.codigo_produto or "").strip()
        for chave in (codigo, codigo_produto):
            if chave and chave not in estoques:
                estoques[chave] = dados
        if posicao.produto:
            produto_codigo = str(posicao.produto.codigo or "").strip()
            if produto_codigo and produto_codigo not in estoques:
                estoques[produto_codigo] = dados
    return estoques


def _nome_fornecedor(recebimento):
    cabec = recebimento.cabec or {}
    dados = recebimento.dados_originais or {}
    return (
        cabec.get("cNome")
        or cabec.get("cRazaoSocial")
        or dados.get("cNome")
        or dados.get("cRazaoSocial")
        or str(recebimento.codigo_fornecedor or "Fornecedor nao informado")
    )


def _familia_produto(produto):
    if not produto:
        return "Sem familia"
    return produto.descricao_familia or "Sem familia"


def _valor_total_item(item):
    valor_total = _numero(item.valor_total_item)
    if valor_total > 0:
        return valor_total
    return _numero(item.preco_unitario) * _numero(item.quantidade_nfe)


def _cmc_anterior_ultima_entrada(item, estoques):
    codigo = str(item.codigo_produto_texto or "").strip()
    estoque = estoques.get(codigo)
    if not estoque:
        return Decimal("0"), "Sem CMC"
    saldo_atual = estoque["saldo"]
    cmc_atual = estoque["cmc"]
    quantidade_entrada = _numero(item.quantidade_nfe)
    saldo_anterior = saldo_atual - quantidade_entrada
    if saldo_anterior <= 0:
        return Decimal("0"), "Sem saldo anterior"
    valor_estoque_anterior = (cmc_atual * saldo_atual) - _valor_total_item(item)
    if valor_estoque_anterior <= 0:
        return Decimal("0"), "Sem CMC anterior"
    return valor_estoque_anterior / saldo_anterior, "CMC anterior"


def _linha_item(item, produto, preco_base, base_origem, impacto):
    preco_atual = _numero(item.preco_unitario)
    variacao = (
        (preco_atual - preco_base) / preco_base * Decimal("100")
        if preco_base > 0
        else Decimal("0")
    )
    return {
        "codigo": item.codigo_produto_texto,
        "descricao": item.descricao or (produto.descricao if produto else ""),
        "familia": _familia_produto(produto),
        "fornecedor": _nome_fornecedor(item.recebimento),
        "preco_base": _formatar_moeda(preco_base),
        "preco_atual": _formatar_moeda(preco_atual),
        "base_origem": base_origem,
        "variacao": _formatar_percentual(variacao),
        "variacao_num": variacao,
        "impacto": _formatar_moeda(abs(impacto)),
        "impacto_num": impacto,
        "impacto_sinal": "+" if impacto > 0 else "-" if impacto < 0 else "",
        "tom": "saving" if impacto > 0 else "loss" if impacto < 0 else "neutral",
    }


def analise_preco_saving_compras(
    empresa,
    periodo_selecionado,
    data_inicio,
    data_fim,
    empresas_ids,
    projetos,
):
    del empresa, projetos
    data_inicio, data_fim = _resolver_datas(periodo_selecionado, data_inicio, data_fim)
    produtos = _produtos_por_codigo(empresas_ids)
    estoques = _estoque_atual_por_produto(empresas_ids)

    itens_validos = [item for item in _query_itens(empresas_ids) if not _nao_gera_financeiro(item)]
    itens_periodo = [
        item
        for item in itens_validos
        if (not data_inicio or item.recebimento.data_emissao_nfe >= data_inicio)
        and (not data_fim or item.recebimento.data_emissao_nfe <= data_fim)
    ]
    ultimos_por_produto = {}
    for item in itens_periodo:
        codigo = str(item.codigo_produto_texto or "").strip()
        if not codigo:
            continue
        atual = ultimos_por_produto.get(codigo)
        if atual is None or (_ordem_item(item), item.pk) > (_ordem_item(atual), atual.pk):
            ultimos_por_produto[codigo] = item

    linhas = []
    impactos_familia = defaultdict(Decimal)
    saving_total = Decimal("0")
    perda_total = Decimal("0")
    itens_alta = 0

    for item in ultimos_por_produto.values():
        codigo = str(item.codigo_produto_texto or "").strip()
        produto = produtos.get(codigo)
        preco_base, base_origem = _cmc_anterior_ultima_entrada(item, estoques)
        if preco_base <= 0:
            continue
        preco_atual = _numero(item.preco_unitario)
        quantidade = _numero(item.quantidade_nfe)
        impacto = (preco_base - preco_atual) * quantidade
        variacao = (preco_atual - preco_base) / preco_base * Decimal("100")
        if impacto > 0:
            saving_total += impacto
        elif impacto < 0:
            perda_total += abs(impacto)
        if variacao > Decimal("10"):
            itens_alta += 1
        familia = _familia_produto(produto)
        impactos_familia[familia] += impacto
        linhas.append(_linha_item(item, produto, preco_base, base_origem, impacto))

    linhas.sort(key=lambda linha: abs(linha["impacto_num"]), reverse=True)
    maior_impacto = max((abs(valor) for valor in impactos_familia.values()), default=Decimal("0"))
    familias = []
    for familia, impacto in sorted(
        impactos_familia.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:6]:
        familias.append(
            {
                "nome": familia,
                "impacto": _formatar_moeda(abs(impacto)),
                "impacto_sinal": "+" if impacto > 0 else "-" if impacto < 0 else "",
                "tom": "saving" if impacto > 0 else "loss" if impacto < 0 else "neutral",
                "largura": int((abs(impacto) / maior_impacto * Decimal("100")).quantize(Decimal("1"))) if maior_impacto else 0,
            }
        )

    destaque = max(
        (familia for familia in familias if familia["tom"] == "saving"),
        key=lambda item: Decimal(str(item["largura"])),
        default=None,
    )

    return {
        "saving_total": _formatar_moeda(saving_total),
        "perda_total": _formatar_moeda(perda_total),
        "itens_alta": itens_alta,
        "itens_comparados": len(linhas),
        "familia_destaque": destaque["nome"] if destaque else "Sem saving",
        "familia_destaque_valor": destaque["impacto"] if destaque else "R$ 0,00",
        "familias": familias,
        "itens": linhas[:12],
    }
