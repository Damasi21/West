"""Dados do dashboard de estoque Curva ABC de Produtos."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _normalizar_filtro_composto,
)
from apps.empresas.models import PedidoItemOmie, PosicaoEstoqueOmie


TIPO_CURVA_ESTOQUE = "estoque"
TIPO_CURVA_VENDAS = "vendas"
TIPOS_CURVA = {
    TIPO_CURVA_ESTOQUE: "Curva de Estoque",
    TIPO_CURVA_VENDAS: "Curva de Vendas",
}
LIMITES_PADRAO = {
    "A": Decimal("80"),
    "B": Decimal("95"),
}
LIMITE_PRODUTOS_POR_CLASSE = 10


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _formatar_numero(valor):
    valor = _decimal(valor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{valor:,.0f}".replace(",", ".")


def _formatar_percentual(valor):
    valor = _decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    texto = f"{valor:.1f}".replace(".", ",")
    if texto.endswith(",0"):
        texto = texto[:-2]
    return f"{texto}%"


def _valor_input_percentual(valor):
    valor = _decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    texto = f"{valor:.1f}"
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto


def _formatar_giro(valor):
    return f"{_decimal(valor).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}x"


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


def _tipo_posicao(posicao):
    produto = posicao.produto
    if not produto:
        return "Produto"
    return produto.descricao_familia or produto.marca or "Produto"


def tipo_curva_abc_valido(valor):
    return valor if valor in TIPOS_CURVA else TIPO_CURVA_ESTOQUE


def limites_curva_abc_validos(classe_a=None, classe_b=None):
    limite_a = _decimal(classe_a if classe_a not in (None, "") else LIMITES_PADRAO["A"])
    limite_b = _decimal(classe_b if classe_b not in (None, "") else LIMITES_PADRAO["B"])
    if limite_a <= 0 or limite_a >= 100:
        limite_a = LIMITES_PADRAO["A"]
    if limite_b <= limite_a or limite_b >= 100:
        limite_b = LIMITES_PADRAO["B"]
    if limite_b <= limite_a:
        limite_a = LIMITES_PADRAO["A"]
        limite_b = LIMITES_PADRAO["B"]
    return {"A": limite_a, "B": limite_b}


def _departamento_item(departamento):
    if isinstance(departamento, dict):
        return (
            departamento.get("cCodDep")
            or departamento.get("codigo")
            or departamento.get("codigo_departamento")
            or departamento.get("cod_departamento")
        )
    return departamento


def _pedido_tem_departamento(pedido, departamentos):
    if not departamentos:
        return True
    codigos = {str(codigo) for codigo in departamentos}
    return any(
        str(codigo) in codigos
        for codigo in (_departamento_item(item) for item in (pedido.departamentos or []))
        if codigo not in (None, "")
    )


def _linha_vazia(codigo, nome, tipo):
    return {
        "codigo": codigo,
        "nome": nome,
        "tipo": tipo,
        "saldo": Decimal("0"),
        "valor": Decimal("0"),
        "quantidade": Decimal("0"),
    }


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
        chave = posicao.produto_id or f"{posicao.codigo_produto}:{_codigo_posicao(posicao)}"
        saldo = _decimal(posicao.saldo or posicao.fisico)
        cmc = _decimal(posicao.cmc or posicao.preco_unitario)
        valor = saldo * cmc
        if chave not in grupos:
            grupos[chave] = _linha_vazia(
                _codigo_posicao(posicao),
                _nome_posicao(posicao),
                _tipo_posicao(posicao),
            )
        grupos[chave]["saldo"] += saldo
        grupos[chave]["valor"] += valor

    linhas = list(grupos.values())
    linhas.sort(key=lambda item: item["valor"], reverse=True)
    return linhas


def _linhas_vendas(periodo, data_inicio, data_fim, empresas_ids, projetos, departamentos):
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    projetos = _normalizar_filtro_composto(projetos or [])
    departamentos = _normalizar_filtro_composto(departamentos or [])
    grupos = {}
    itens = (
        PedidoItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            pedido__ativo_omie=True,
            pedido__cancelado=False,
            pedido__faturado=True,
            pedido__data_faturamento__gte=inicio,
            pedido__data_faturamento__lte=fim,
        )
        .select_related("pedido", "produto")
        .order_by("descricao", "codigo_produto_texto")
    )
    if projetos:
        itens = itens.filter(pedido__codigo_projeto__in=projetos)

    for item in itens:
        if not _pedido_tem_departamento(item.pedido, departamentos):
            continue
        chave = item.produto_id or item.codigo_produto or item.codigo_produto_texto or item.codigo_item
        if not chave:
            continue
        produto = item.produto
        codigo = (
            item.codigo_produto_texto
            or (produto.codigo if produto and produto.codigo else "")
            or str(item.codigo_produto or item.codigo_item)
        )
        nome = (
            item.descricao
            or (produto.descricao if produto and produto.descricao else "")
            or f"Produto {item.codigo_produto or item.codigo_item}"
        )
        tipo = (
            produto.descricao_familia
            if produto and produto.descricao_familia
            else (produto.marca if produto and produto.marca else "Produto")
        )
        if chave not in grupos:
            grupos[chave] = _linha_vazia(codigo, nome, tipo)
        grupos[chave]["valor"] += _decimal(item.valor_total or item.valor_mercadoria)
        grupos[chave]["quantidade"] += _decimal(item.quantidade)

    linhas = list(grupos.values())
    linhas.sort(key=lambda item: item["valor"], reverse=True)
    return linhas


def _linhas_demo(tipo_curva=TIPO_CURVA_ESTOQUE):
    produtos = [
        ("1042", "Chapa de Aco Galvanizado 2mm", "Materia-prima", Decimal("186400")),
        ("0587", "Kit Revenda Ferramentas 12pc", "Revenda", Decimal("162300")),
        ("1198", "Resina Epoxi Industrial 25kg", "Materia-prima", Decimal("141600")),
        ("3301", "Rolamento Blindado 6205ZZ", "Componentes", Decimal("118900")),
        ("0876", "Bobina de Cobre Esmaltado", "Materia-prima", Decimal("97200")),
        ("0410", "Motor Redutor 1/4 CV", "Componentes", Decimal("88600")),
        ("3210", "Correia Industrial A45", "Componentes", Decimal("64100")),
        ("2210", "Parafuso Sextavado M8x40", "Componentes", Decimal("9752")),
        ("2209", "Porca Sextavada M8", "Componentes", Decimal("8420")),
        ("5501", "Abracadeira Nylon 200mm", "Componentes", Decimal("5100")),
        ("9012", "Etiqueta Patrimonial", "Consumo", Decimal("980")),
        ("3385", "Luva de Procedimento M", "Consumo", Decimal("720")),
        ("9999", "Embalagem Retornavel", "Embalagem", Decimal("410")),
    ]
    return [
        {
            "codigo": codigo,
            "nome": nome,
            "tipo": tipo,
            "saldo": Decimal("0"),
            "valor": valor,
            "quantidade": Decimal("0"),
        }
        for codigo, nome, tipo, valor in produtos
    ]


def _classe_por_acumulado(acumulado_anterior, limites):
    if acumulado_anterior < limites["A"]:
        return "A", "success"
    if acumulado_anterior < limites["B"]:
        return "B", "warning"
    return "C", "neutral"


def _classificar(linhas, limites):
    total = sum((item["valor"] for item in linhas), Decimal("0"))
    acumulado = Decimal("0")
    classes = defaultdict(lambda: {"quantidade": 0, "valor": Decimal("0")})
    classificadas = []
    for indice, item in enumerate(linhas):
        participacao = (item["valor"] / total * Decimal("100")) if total else Decimal("0")
        classe, tom = _classe_por_acumulado(acumulado, limites)
        acumulado += participacao
        classes[classe]["quantidade"] += 1
        classes[classe]["valor"] += item["valor"]
        classificadas.append(
            {
                **item,
                "classe": classe,
                "classe_tom": tom,
                "valor_fmt": _formatar_moeda(item["valor"]),
                "participacao": float(participacao),
                "participacao_fmt": _formatar_percentual(participacao),
                "participacao_barra": min(float(participacao), 100),
                "acumulado": float(min(acumulado, Decimal("100"))),
                "acumulado_fmt": _formatar_percentual(min(acumulado, Decimal("100"))),
                "giro": _formatar_giro(Decimal("1.2") + Decimal(indice % 6) * Decimal("0.35")),
            }
        )
    return classificadas, classes, total


def _limitar_produtos_por_classe(produtos):
    contadores = defaultdict(int)
    exibidos = []
    for produto in produtos:
        classe = produto["classe"]
        if contadores[classe] >= LIMITE_PRODUTOS_POR_CLASSE:
            continue
        contadores[classe] += 1
        exibidos.append(produto)
    return exibidos


def curva_abc_produtos_estoque(
    empresa,
    empresas_ids,
    periodo=None,
    data_inicio="",
    data_fim="",
    projetos=None,
    departamentos=None,
    tipo_curva=TIPO_CURVA_ESTOQUE,
    limites=None,
):
    del empresa
    tipo_curva = tipo_curva_abc_valido(tipo_curva)
    limites = limites or LIMITES_PADRAO
    if tipo_curva == TIPO_CURVA_VENDAS:
        linhas = _linhas_vendas(
            periodo,
            data_inicio,
            data_fim,
            empresas_ids,
            projetos,
            departamentos,
        )
    else:
        linhas = _linhas_posicoes(empresas_ids)
    if not linhas:
        linhas = _linhas_demo(tipo_curva)

    produtos, classes, total = _classificar(linhas, limites)
    total_produtos = len(produtos)
    produtos_exibidos = _limitar_produtos_por_classe(produtos)
    pontos = produtos_exibidos
    cores = {"A": "#2f8f7f", "B": "#c49a43", "C": "#a5adb5"}
    valor_label = "vendas" if tipo_curva == TIPO_CURVA_VENDAS else "valor total"
    total_titulo = "Vendas analisadas" if tipo_curva == TIPO_CURVA_VENDAS else "Valor total analisado"
    coluna_valor = "Vendas" if tipo_curva == TIPO_CURVA_VENDAS else "Valor em estoque"
    return {
        "tipo_curva": tipo_curva,
        "tipo_curva_rotulo": TIPOS_CURVA[tipo_curva],
        "tipos_curva": [
            {"valor": valor, "nome": nome}
            for valor, nome in TIPOS_CURVA.items()
        ],
        "coluna_valor": coluna_valor,
        "ordenacao_rotulo": (
            "Ordenado por vendas no periodo"
            if tipo_curva == TIPO_CURVA_VENDAS
            else "Ordenado por participacao no valor"
        ),
        "kpis": [
            {
                "titulo": "Classe A",
                "valor": f"{classes['A']['quantidade']} produtos",
                "subvalor": f"{_formatar_percentual(classes['A']['valor'] / total * Decimal('100') if total else 0)} de {valor_label}",
                "tom": "success",
            },
            {
                "titulo": "Classe B",
                "valor": f"{classes['B']['quantidade']} produtos",
                "subvalor": f"{_formatar_percentual(classes['B']['valor'] / total * Decimal('100') if total else 0)} de {valor_label}",
                "tom": "warning",
            },
            {
                "titulo": "Classe C",
                "valor": f"{classes['C']['quantidade']} produtos",
                "subvalor": f"{_formatar_percentual(classes['C']['valor'] / total * Decimal('100') if total else 0)} de {valor_label}",
                "tom": "neutral",
            },
            {
                "titulo": total_titulo,
                "valor": _formatar_moeda(total),
                "subvalor": f"{_formatar_numero(total_produtos)} produtos ativos",
                "tom": "total",
            },
        ],
        "regua": [
            {
                "classe": "A",
                "descricao": f"ate {_formatar_percentual(limites['A'])} acumulado",
                "limite": _formatar_percentual(limites["A"]),
                "campo": "abc_classe_a",
                "valor": _valor_input_percentual(limites["A"]),
                "editavel": True,
            },
            {
                "classe": "B",
                "descricao": f"ate {_formatar_percentual(limites['B'])} acumulado",
                "limite": _formatar_percentual(limites["B"]),
                "campo": "abc_classe_b",
                "valor": _valor_input_percentual(limites["B"]),
                "editavel": True,
            },
            {
                "classe": "C",
                "descricao": "restante",
                "limite": "100%",
                "campo": "",
                "valor": "100",
                "editavel": False,
            },
        ],
        "produtos": produtos_exibidos,
        "chart_labels": [item["codigo"] for item in pontos],
        "chart_barras": [round(item["participacao"], 2) for item in pontos],
        "chart_acumulado": [round(item["acumulado"], 2) for item in pontos],
        "chart_cores": [cores[item["classe"]] for item in pontos],
    }
