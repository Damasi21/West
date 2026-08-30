"""Calculos do dashboard comercial Faturamento."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
    _porcentagem,
    _variacao_percentual,
)
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    MetaVendedorComercial,
    OrdemServicoItemOmie,
    OrdemServicoOmie,
    PedidoItemOmie,
    PedidoOmie,
)


TIPOS_FATURAMENTO = {
    "produtos": "Produtos",
    "servicos": "Servicos",
    "impostos": "Impostos",
}
TIPOS_FATURAMENTO_PADRAO = ["produtos", "servicos"]

CHAVES_FRETE_DESPESAS_PRODUTO = {
    "valor_frete",
    "valor_seguro",
    "outras_despesas",
    "valor_outras_despesas",
    "nvalfrete",
    "nvalseguro",
    "nvaloutras",
    "nfrete",
    "nseguro",
    "ndespesas",
}

CHAVES_IMPOSTOS_PRODUTO = {
    "valor_cofins",
    "valor_cofins_st",
    "valor_csll",
    "valor_icms",
    "valor_fcp_icms_inter",
    "valor_icms_uf_dest",
    "valor_icms_uf_remet",
    "valor_icms_st",
    "valor_inss",
    "valor_ipi",
    "valor_irrf",
    "valor_iss",
    "valor_pis",
    "valor_pis_st",
    "nvalorcofins",
    "nvalorcofinsst",
    "nvalorcsll",
    "nvaloricms",
    "nvalorfcpicmsinter",
    "nvaloricmsufdest",
    "nvaloricmsufremet",
    "nvaloricmsst",
    "nvalorinss",
    "nvaloripi",
    "nvalorirrf",
    "nvaloriss",
    "nvalorpis",
    "nvalorpisst",
    "nvalorst",
}

IMPOSTOS_SERVICO_RETENCAO = {
    "nValorCOFINS": "cRetemCOFINS",
    "nValorCSLL": "cRetemCSLL",
    "nValorINSS": "cRetemINSS",
    "nValorIRRF": "cRetemIRRF",
    "nValorPIS": "cRetemPIS",
}


def _decimal(valor):
    return valor or Decimal("0")


def _decimal_omie(valor):
    if valor in (None, ""):
        return Decimal("0")
    if isinstance(valor, Decimal):
        return valor
    texto = str(valor)
    if isinstance(valor, str) and "," in valor:
        texto = texto.replace(".", "").replace(",", ".")
    return Decimal(texto)


def _formatar_numero(valor):
    valor = _decimal(valor)
    if valor == valor.to_integral():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_percentual(valor):
    return f"{valor:.0f}%"


def _tipos_validos(valores):
    valores_validos = [valor for valor in valores if valor in TIPOS_FATURAMENTO]
    return valores_validos or TIPOS_FATURAMENTO_PADRAO[:]


def _codigos_vendedores(valores):
    return _normalizar_filtro_composto(valores or [])


def _periodo_anterior(inicio, fim):
    dias = (fim - inicio).days + 1
    fim_anterior = inicio - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)
    return inicio_anterior, fim_anterior


def _metas_por_mes(empresas_ids, vendedores, meses):
    queryset = MetaVendedorComercial.objects.filter(
        empresa_id__in=empresas_ids,
        vendedor__inativo=False,
    )
    if vendedores:
        queryset = queryset.filter(vendedor__codigo__in=vendedores)
    filtros_periodo = [(item["ano"], item["mes"]) for item in meses]
    queryset = queryset.filter(
        ano__in={ano for ano, _ in filtros_periodo},
        mes__in={mes for _, mes in filtros_periodo},
    )
    totais = defaultdict(Decimal)
    for meta in queryset:
        chave = f"{meta.ano}-{meta.mes:02d}"
        if (meta.ano, meta.mes) in filtros_periodo:
            totais[chave] += _decimal(meta.valor_mensal)
    return totais


def _query_pedidos_emitidos(inicio, fim, empresas_ids, projetos, vendedores):
    queryset = PedidoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelado=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_pedidos_faturados(inicio, fim, empresas_ids, projetos, vendedores):
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
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_ordens_emitidas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.annotate(
        data_referencia=Coalesce("data_inclusao", "data_previsao"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelada=False,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _query_ordens_faturadas(inicio, fim, empresas_ids, vendedores):
    queryset = OrdemServicoOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        cancelada=False,
        faturada=True,
        data_faturamento__gte=inicio,
        data_faturamento__lte=fim,
    )
    if vendedores:
        queryset = queryset.filter(codigo_vendedor__in=vendedores)
    return queryset


def _totais_por_mes(queryset, campo_data, campo_valor):
    totais = defaultdict(Decimal)
    linhas = (
        queryset.annotate(
            ano=ExtractYear(campo_data),
            mes=ExtractMonth(campo_data),
        )
        .values("ano", "mes")
        .annotate(total=Sum(campo_valor))
    )
    for item in linhas:
        if item["ano"] and item["mes"]:
            totais[f"{item['ano']}-{item['mes']:02d}"] = _decimal(item["total"])
    return totais


def _normalizar_chave_omie(chave):
    return "".join(caractere for caractere in str(chave).lower() if caractere.isalnum())


def _somar_chaves_json(dados, chaves):
    chaves_normalizadas = {_normalizar_chave_omie(chave) for chave in chaves}
    if isinstance(dados, dict):
        total = Decimal("0")
        for chave, valor in dados.items():
            if _normalizar_chave_omie(chave) in chaves_normalizadas:
                total += _decimal_omie(valor)
            elif isinstance(valor, (dict, list)):
                total += _somar_chaves_json(valor, chaves)
        return total
    if isinstance(dados, list):
        return sum((_somar_chaves_json(item, chaves) for item in dados), Decimal("0"))
    return Decimal("0")


def _buscar_valor_json(dados, chaves):
    chaves_normalizadas = {_normalizar_chave_omie(chave) for chave in chaves}
    if isinstance(dados, dict):
        for chave, valor in dados.items():
            if _normalizar_chave_omie(chave) in chaves_normalizadas and valor not in (None, ""):
                return valor
            if isinstance(valor, (dict, list)):
                encontrado = _buscar_valor_json(valor, chaves)
                if encontrado not in (None, ""):
                    return encontrado
    if isinstance(dados, list):
        for item in dados:
            encontrado = _buscar_valor_json(item, chaves)
            if encontrado not in (None, ""):
                return encontrado
    return ""


def _componentes_produtos_pedido(pedido):
    itens = list(getattr(pedido, "_prefetched_objects_cache", {}).get("itens", []))
    if not itens:
        itens = list(pedido.itens.filter(ativo_omie=True))

    mercadorias = _decimal(pedido.valor_mercadorias)
    if not mercadorias:
        mercadorias = sum(
            (_decimal(item.valor_mercadoria) for item in itens),
            Decimal("0"),
        )

    frete_despesas = (
        _decimal(pedido.valor_frete)
        + _decimal(pedido.valor_seguro)
        + _somar_chaves_json(
            pedido.frete,
            {"outras_despesas", "valor_outras_despesas", "nvaloutras"},
        )
        + _somar_chaves_json(
            pedido.total_pedido,
            {"outras_despesas", "valor_outras_despesas", "nvaloutras"},
        )
    )
    if not frete_despesas:
        frete_despesas = sum(
            (
                _somar_chaves_json(item.produto_dados, CHAVES_FRETE_DESPESAS_PRODUTO)
                + _somar_chaves_json(item.inf_adic, CHAVES_FRETE_DESPESAS_PRODUTO)
            )
            for item in itens
        )

    impostos = sum(
        (_somar_chaves_json(item.imposto, CHAVES_IMPOSTOS_PRODUTO) for item in itens),
        Decimal("0"),
    )
    if not impostos:
        impostos = (
            _somar_chaves_json(pedido.total_pedido, CHAVES_IMPOSTOS_PRODUTO)
            + _somar_chaves_json(pedido.dados_originais, CHAVES_IMPOSTOS_PRODUTO)
        )

    total_pedido = _decimal(pedido.valor_total_pedido)
    if total_pedido and not any((mercadorias, frete_despesas)):
        mercadorias = total_pedido

    total_faturamento = mercadorias + frete_despesas
    if total_pedido and total_faturamento < total_pedido:
        mercadorias += total_pedido - total_faturamento

    return {
        "mercadorias": mercadorias,
        "frete_despesas": frete_despesas,
        "impostos": impostos,
    }


def _componentes_produtos_por_mes(queryset):
    totais = {
        "mercadorias": defaultdict(Decimal),
        "frete_despesas": defaultdict(Decimal),
        "impostos": defaultdict(Decimal),
    }
    for pedido in queryset.prefetch_related("itens"):
        if not pedido.data_faturamento:
            continue
        chave = f"{pedido.data_faturamento.year}-{pedido.data_faturamento.month:02d}"
        componentes = _componentes_produtos_pedido(pedido)
        for nome, valor in componentes.items():
            totais[nome][chave] += valor
    return totais


def _imposto_servico_item(item):
    impostos = item.impostos or {}
    total = _decimal(item.valor_iss) or _decimal_omie(impostos.get("nValorISS"))
    for chave_valor, chave_retencao in IMPOSTOS_SERVICO_RETENCAO.items():
        if str(impostos.get(chave_retencao, "")).strip().upper() == "S":
            continue
        total += _decimal_omie(impostos.get(chave_valor))
    return total


def _impostos_servicos_por_mes(queryset):
    totais = defaultdict(Decimal)
    for ordem in queryset.prefetch_related("itens"):
        if not ordem.data_faturamento:
            continue
        chave = f"{ordem.data_faturamento.year}-{ordem.data_faturamento.month:02d}"
        totais[chave] += sum(
            (
                _imposto_servico_item(item)
                for item in ordem.itens.all()
                if item.ativo_omie
            ),
            Decimal("0"),
        )
    return totais


def _nome_cliente_pedido(pedido):
    cliente = pedido.cliente
    return (
        getattr(cliente, "nome_fantasia", "")
        or getattr(cliente, "razao_social", "")
        or str(pedido.codigo_cliente or "")
        or "Cliente nao informado"
    )


def _numero_nf_pedido(pedido):
    valor = _buscar_valor_json(
        pedido.dados_originais,
        {
            "numero_nf",
            "numero_nfe",
            "cNumNF",
            "cNumeroNF",
            "cNumeroNFe",
            "nNF",
            "nNumNF",
        },
    )
    return str(valor or pedido.numero_pedido or "")


def linhas_excel_faturamento_produtos(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    vendedores_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    vendedores = _codigos_vendedores(vendedores_selecionados or [])
    pedidos = _query_pedidos_faturados(
        inicio,
        fim,
        empresas_ids,
        projetos,
        vendedores,
    ).select_related("cliente").order_by("data_faturamento", "numero_pedido")

    linhas = []
    for pedido in pedidos:
        componentes = _componentes_produtos_pedido(pedido)
        linhas.append(
            {
                "data_emissao": pedido.data_faturamento,
                "data_emissao_fmt": (
                    pedido.data_faturamento.strftime("%d/%m/%Y")
                    if pedido.data_faturamento
                    else ""
                ),
                "cliente": _nome_cliente_pedido(pedido),
                "numero_nf": _numero_nf_pedido(pedido),
                "total_mercadoria": componentes["mercadorias"],
                "frete": componentes["frete_despesas"],
                "total_nota": _decimal(pedido.valor_total_pedido),
            }
        )
    return linhas


def _ranking_produtos(queryset, queryset_anterior, total_periodo):
    linhas = (
        PedidoItemOmie.objects.filter(pedido__in=queryset, ativo_omie=True)
        .values("produto__descricao", "descricao", "codigo_produto_texto")
        .annotate(quantidade=Sum("quantidade"), total=Sum("valor_total"))
        .order_by("-total")[:5]
    )
    anterior_base = PedidoItemOmie.objects.filter(
        pedido__in=queryset_anterior,
        ativo_omie=True,
    )
    itens = []
    for item in linhas:
        nome = (
            item["produto__descricao"]
            or item["descricao"]
            or item["codigo_produto_texto"]
            or "Produto nao informado"
        )
        anterior = _decimal(
            anterior_base.filter(descricao=item["descricao"]).aggregate(
                total=Sum("valor_total")
            )["total"]
        )
        total = _decimal(item["total"])
        variacao = _variacao_percentual(total, anterior)
        itens.append(
            {
                "nome": nome,
                "quantidade": _formatar_numero(item["quantidade"]),
                "valor_fmt": _formatar_moeda(total),
                "participacao_fmt": _formatar_percentual(
                    _porcentagem(total, total_periodo)
                ),
                "participacao": float(_porcentagem(total, total_periodo)),
                "variacao_fmt": _formatar_percentual(variacao),
                "variacao_tom": "up" if variacao >= 0 else "down",
            }
        )
    return itens


def _ranking_servicos(queryset, queryset_anterior, total_periodo):
    valor_item = ExpressionWrapper(
        F("quantidade") * F("valor_unitario"),
        output_field=DecimalField(max_digits=18, decimal_places=4),
    )
    linhas = (
        OrdemServicoItemOmie.objects.filter(
            ordem_servico__in=queryset,
            ativo_omie=True,
        )
        .annotate(valor_calculado=valor_item)
        .values("servico__descricao", "descricao", "codigo_servico")
        .annotate(quantidade=Sum("quantidade"), total=Sum("valor_calculado"))
        .order_by("-total")[:5]
    )
    anterior_base = OrdemServicoItemOmie.objects.filter(
        ordem_servico__in=queryset_anterior,
        ativo_omie=True,
    ).annotate(valor_calculado=valor_item)
    itens = []
    for item in linhas:
        nome = (
            item["servico__descricao"]
            or item["descricao"]
            or str(item["codigo_servico"] or "")
            or "Servico nao informado"
        )
        anterior = _decimal(
            anterior_base.filter(descricao=item["descricao"]).aggregate(
                total=Sum("valor_calculado")
            )["total"]
        )
        total = _decimal(item["total"])
        variacao = _variacao_percentual(total, anterior)
        itens.append(
            {
                "nome": nome,
                "quantidade": _formatar_numero(item["quantidade"]),
                "valor_fmt": _formatar_moeda(total),
                "participacao_fmt": _formatar_percentual(
                    _porcentagem(total, total_periodo)
                ),
                "participacao": float(_porcentagem(total, total_periodo)),
                "variacao_fmt": _formatar_percentual(variacao),
                "variacao_tom": "up" if variacao >= 0 else "down",
            }
        )
    return itens


def faturamento_comercial(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    tipos_selecionados=None,
    vendedores_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    inicio_anterior, fim_anterior = _periodo_anterior(inicio, fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    vendedores = _codigos_vendedores(vendedores_selecionados or [])
    tipos = _tipos_validos(tipos_selecionados or [])

    pedidos_emitidos = _query_pedidos_emitidos(
        inicio, fim, empresas_ids, projetos, vendedores
    )
    pedidos_faturados = _query_pedidos_faturados(
        inicio, fim, empresas_ids, projetos, vendedores
    )
    pedidos_faturados_anteriores = _query_pedidos_faturados(
        inicio_anterior, fim_anterior, empresas_ids, projetos, vendedores
    )
    ordens_emitidas = _query_ordens_emitidas(inicio, fim, empresas_ids, vendedores)
    ordens_faturadas = _query_ordens_faturadas(inicio, fim, empresas_ids, vendedores)
    ordens_faturadas_anteriores = _query_ordens_faturadas(
        inicio_anterior, fim_anterior, empresas_ids, vendedores
    )

    produtos_componentes_mes = _componentes_produtos_por_mes(pedidos_faturados)
    produtos_componentes_anteriores = _componentes_produtos_por_mes(
        pedidos_faturados_anteriores
    )
    impostos_servicos_mes = _impostos_servicos_por_mes(ordens_faturadas)
    impostos_servicos_anteriores = _impostos_servicos_por_mes(
        ordens_faturadas_anteriores
    )
    total_produtos = _decimal(
        pedidos_faturados.aggregate(total=Sum("valor_total_pedido"))["total"]
    )
    total_impostos_produtos = sum(
        produtos_componentes_mes["impostos"].values(),
        Decimal("0"),
    )
    total_impostos_servicos = sum(impostos_servicos_mes.values(), Decimal("0"))
    total_servicos = _decimal(
        ordens_faturadas.aggregate(total=Sum("valor_total"))["total"]
    )
    total_faturado = Decimal("0")
    if "impostos" in tipos:
        total_faturado = total_impostos_produtos + total_impostos_servicos
    elif "produtos" in tipos:
        total_faturado += total_produtos
    if "impostos" not in tipos and "servicos" in tipos:
        total_faturado += total_servicos

    total_emitido = Decimal("0")
    quantidade_emitida = 0
    if "produtos" in tipos and "impostos" not in tipos:
        total_emitido += _decimal(
            pedidos_emitidos.aggregate(total=Sum("valor_total_pedido"))["total"]
        )
        quantidade_emitida += pedidos_emitidos.aggregate(total=Count("id"))["total"]
    if "servicos" in tipos and "impostos" not in tipos:
        total_emitido += _decimal(
            ordens_emitidas.aggregate(total=Sum("valor_total"))["total"]
        )
        quantidade_emitida += ordens_emitidas.aggregate(total=Count("id"))["total"]
    if "impostos" in tipos:
        quantidade_emitida = pedidos_faturados.count() + ordens_faturadas.count()

    produtos_mes = _totais_por_mes(
        pedidos_faturados,
        "data_faturamento",
        "valor_total_pedido",
    )
    servicos_mes = _totais_por_mes(
        ordens_faturadas,
        "data_faturamento",
        "valor_total",
    )
    produtos_anterior = _decimal(
        pedidos_faturados_anteriores.aggregate(total=Sum("valor_total_pedido"))[
            "total"
        ]
    )
    servicos_anterior = _decimal(
        ordens_faturadas_anteriores.aggregate(total=Sum("valor_total"))["total"]
    )
    total_anterior = Decimal("0")
    if "impostos" in tipos:
        total_anterior += sum(
            produtos_componentes_anteriores["impostos"].values(),
            Decimal("0"),
        )
        total_anterior += sum(impostos_servicos_anteriores.values(), Decimal("0"))
    elif "produtos" in tipos:
        total_anterior += produtos_anterior
    if "impostos" not in tipos and "servicos" in tipos:
        total_anterior += servicos_anterior
    media_anterior = total_anterior / Decimal(len(meses) or 1)
    metas_mes = _metas_por_mes(empresas_ids, vendedores, meses)
    meta_periodo = sum((metas_mes[item["chave"]] for item in meses), Decimal("0"))

    acumulado = []
    for item in meses:
        valor_mes = Decimal("0")
        if "impostos" in tipos:
            valor_mes += produtos_componentes_mes["impostos"][item["chave"]]
            valor_mes += impostos_servicos_mes[item["chave"]]
        elif "produtos" in tipos:
            valor_mes += (
                produtos_componentes_mes["mercadorias"][item["chave"]]
                + produtos_componentes_mes["frete_despesas"][item["chave"]]
            )
        if "impostos" not in tipos and "servicos" in tipos:
            valor_mes += servicos_mes[item["chave"]]
        acumulado.append(float(valor_mes))

    ranking = []
    if "produtos" in tipos and "impostos" not in tipos:
        ranking.extend(
            _ranking_produtos(
                pedidos_faturados,
                pedidos_faturados_anteriores,
                total_faturado,
            )
        )
    if "servicos" in tipos and "impostos" not in tipos:
        ranking.extend(
            _ranking_servicos(
                ordens_faturadas,
                ordens_faturadas_anteriores,
                total_faturado,
            )
        )
    ranking = sorted(
        ranking,
        key=lambda item: Decimal(str(item["participacao"])),
        reverse=True,
    )[:5]

    return {
        "indicadores": [
            {
                "titulo": "Faturado",
                "valor": _formatar_moeda_curta(total_faturado),
                "valor_completo": _formatar_moeda(total_faturado),
                "icone": "bi-receipt-cutoff",
                "tom": "positive",
            },
            {
                "titulo": "Meta do periodo",
                "valor": _formatar_moeda_curta(meta_periodo),
                "valor_completo": _formatar_moeda(meta_periodo),
                "icone": "bi-bullseye",
                "tom": "neutral",
            },
            {
                "titulo": "Pedidos emitidos",
                "valor": _formatar_numero(Decimal(quantidade_emitida)),
                "valor_completo": _formatar_numero(Decimal(quantidade_emitida)),
                "icone": "bi-clipboard-check",
                "tom": "positive",
            },
            {
                "titulo": "Ticket medio",
                "valor": _formatar_moeda_curta(
                    total_emitido / Decimal(quantidade_emitida or 1)
                ),
                "valor_completo": _formatar_moeda(
                    total_emitido / Decimal(quantidade_emitida or 1)
                ),
                "icone": "bi-ticket-perforated",
                "tom": "positive",
            },
        ],
        "labels": [item["rotulo"] for item in meses],
        "produtos": [
            float(produtos_mes[item["chave"]]) if "produtos" in tipos else 0
            for item in meses
        ],
        "produtos_mercadorias": [
            float(produtos_componentes_mes["mercadorias"][item["chave"]])
            if "produtos" in tipos
            else 0
            for item in meses
        ],
        "produtos_frete_despesas": [
            float(produtos_componentes_mes["frete_despesas"][item["chave"]])
            if "produtos" in tipos
            else 0
            for item in meses
        ],
        "produtos_impostos": [
            float(produtos_componentes_mes["impostos"][item["chave"]])
            if "impostos" in tipos
            else 0
            for item in meses
        ],
        "servicos_impostos": [
            float(impostos_servicos_mes[item["chave"]])
            if "impostos" in tipos
            else 0
            for item in meses
        ],
        "servicos": [
            float(servicos_mes[item["chave"]]) if "servicos" in tipos else 0
            for item in meses
        ],
        "media_anterior": [float(media_anterior) for _ in meses],
        "acumulado": acumulado,
        "meta": [float(metas_mes[item["chave"]]) for item in meses],
        "ranking": ranking,
        "tipos": tipos,
        "grafico_titulo": (
            "Impostos de produtos e servicos"
            if "impostos" in tipos
            else "Produtos, servicos e faturado do periodo"
        ),
    }
