"""Score de fornecedores baseado em pedidos de compra OMIE."""

from collections import defaultdict
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils.dateparse import parse_date

from apps.empresas.models import PedidoCompraItemOmie, RecebimentoNfeItemOmie


ETAPAS_PEDIDO_SCORE = ("10", "15")


def _percentual(valor):
    return f"{Decimal(str(valor)).quantize(Decimal('1'))}%"


def _numero(valor):
    return Decimal(str(valor or 0))


def _media(valores):
    valores = [Decimal(str(valor)) for valor in valores if valor is not None]
    if not valores:
        return Decimal("0")
    return sum(valores, Decimal("0")) / Decimal(len(valores))


def _inteiro(valor):
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _classe_score(score):
    if score >= 90:
        return "a", "A-excelente", "success"
    if score >= 80:
        return "b", "B - Muito bom", "primary"
    if score >= 70:
        return "c", "C - Bom", "warning"
    return "d", "D- Atencao", "danger"


def _sigla(nome):
    partes = [parte for parte in nome.replace("&", " ").split() if parte]
    if not partes:
        return "SN"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return "".join(parte[0] for parte in partes[:2]).upper()


def _nome_fornecedor(pedido):
    fornecedor = pedido.fornecedor
    if fornecedor:
        return (
            fornecedor.razao_social
            or fornecedor.nome_fantasia
            or str(pedido.codigo_fornecedor or "")
        )
    return str(pedido.codigo_fornecedor or "Fornecedor nao informado")


def _data_real_recebimento(item, recebimento=None):
    if recebimento and recebimento.data_recebimento:
        return recebimento.data_recebimento
    dados = item.dados_originais or {}
    pedido_dados = item.pedido.dados_originais or {}
    for origem in (
        dados,
        dados.get("recebimento") or {},
        pedido_dados,
        pedido_dados.get("recebimento") or {},
    ):
        data = origem.get("dRec") or origem.get("data_recebimento")
        if data:
            if hasattr(data, "year"):
                return data
            data_texto = str(data)
            data_parseada = parse_date(data_texto)
            if data_parseada:
                return data_parseada
            try:
                return datetime.strptime(data_texto, "%d/%m/%Y").date()
            except ValueError:
                return None
    return None


def _pontuar_otd(data_prevista, data_real):
    if not data_prevista or not data_real:
        return None
    atraso = (data_real - data_prevista).days
    if atraso <= 0:
        return Decimal("100")
    if atraso == 1:
        return Decimal("80")
    if atraso == 2:
        return Decimal("60")
    if atraso <= 5:
        return Decimal("20")
    return Decimal("0")


def _pontuar_nf(quantidade_pedida, quantidade_recebida):
    pedida = _numero(quantidade_pedida)
    recebida = _numero(quantidade_recebida)
    if pedida <= 0 or recebida <= 0:
        return None
    percentual = recebida / pedida * Decimal("100")
    return min(percentual, Decimal("100"))


def _chave_produto(item):
    return item.codigo_produto or item.codigo_produto_texto


def _pontuar_preco(item, historico_por_produto):
    chave = _chave_produto(item)
    preco_atual = _numero(item.valor_unitario)
    if not chave or preco_atual <= 0:
        return Decimal("100")

    anteriores = [
        anterior
        for anterior in historico_por_produto.get(chave, [])
        if anterior.pk != item.pk
        and (_ordem_item(anterior), anterior.pk) < (_ordem_item(item), item.pk)
        and _numero(anterior.valor_unitario) > 0
    ]
    if not anteriores:
        return Decimal("100")

    anterior = anteriores[-1]
    preco_anterior = _numero(anterior.valor_unitario)
    if preco_anterior <= 0 or preco_atual == preco_anterior:
        return Decimal("100")

    diferenca = abs(preco_atual - preco_anterior) / preco_anterior * Decimal("100")
    if preco_atual < preco_anterior:
        return Decimal("100") + diferenca
    return max(Decimal("0"), Decimal("100") - diferenca)


def _query_itens(data_inicio, data_fim, empresas_ids, projetos):
    queryset = (
        PedidoCompraItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            pedido__ativo_omie=True,
            pedido__etapa__in=ETAPAS_PEDIDO_SCORE,
        )
        .select_related("pedido", "pedido__fornecedor")
        .order_by("pedido__data_inclusao", "pedido__data_previsao", "pk")
    )
    if data_inicio and data_fim:
        queryset = queryset.filter(pedido__data_previsao__range=(data_inicio, data_fim))
    if projetos:
        queryset = queryset.filter(pedido__projeto__in=projetos)
    return list(queryset)


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


def _ordem_item(item):
    return item.pedido.data_inclusao or item.pedido.data_previsao or date.min


def _historico_produtos(empresas_ids):
    historico = defaultdict(list)
    itens = (
        PedidoCompraItemOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            pedido__ativo_omie=True,
            pedido__etapa__in=ETAPAS_PEDIDO_SCORE,
        )
        .select_related("pedido")
        .order_by("pedido__data_inclusao", "pedido__data_previsao", "pk")
    )
    for item in itens:
        chave = _chave_produto(item)
        if chave:
            historico[chave].append(item)
    return historico


def _recebimentos_por_pedido_produto(empresas_ids, data_inicio, data_fim):
    queryset = RecebimentoNfeItemOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
    ).order_by("data_recebimento", "pk")
    if data_inicio and data_fim:
        queryset = queryset.filter(data_recebimento__range=(data_inicio, data_fim))

    recebimentos = defaultdict(list)
    for recebimento in queryset:
        chave = (
            str(recebimento.numero_pedido_compra or "").strip(),
            str(recebimento.codigo_produto_texto or "").strip(),
        )
        if chave[0] and chave[1]:
            recebimentos[chave].append(recebimento)
    return recebimentos


def _recebimento_do_item(item, recebimentos):
    chaves_produto = [
        str(item.codigo_produto_texto or "").strip(),
        str(item.codigo_produto or "").strip(),
    ]
    numero_pedido = str(item.pedido.numero_pedido or "").strip()
    for codigo_produto in chaves_produto:
        if not codigo_produto:
            continue
        encontrados = recebimentos.get((numero_pedido, codigo_produto))
        if encontrados:
            return encontrados[-1]
    return None


def _montar_fornecedor(codigo_fornecedor, dados):
    otd = _inteiro(_media(dados["otd"]) if dados["otd"] else Decimal("0"))
    nf = _inteiro(_media(dados["nf"]) if dados["nf"] else Decimal("0"))
    preco = _inteiro(_media(dados["preco"]) if dados["preco"] else Decimal("100"))
    score = _inteiro(_media([otd, nf, preco]))
    classe_slug, classe_rotulo, classe_tom = _classe_score(score)
    nome = dados["nome"]
    return {
        "codigo_fornecedor": codigo_fornecedor,
        "sigla": _sigla(nome),
        "nome": nome,
        "score": score,
        "score_fmt": str(score),
        "classe": classe_rotulo,
        "classe_slug": classe_slug,
        "tom": classe_tom,
        "otd": otd,
        "otd_fmt": _percentual(otd),
        "conformidade_nf": nf,
        "conformidade_nf_fmt": _percentual(nf),
        "estabilidade_preco": preco,
        "estabilidade_preco_fmt": _percentual(preco),
        "lead_time": otd,
        "lead_time_fmt": _percentual(otd),
        "pedidos": len(dados["pedidos"]),
        "itens": dados["itens"],
    }


def score_fornecedores_compras(
    empresa,
    periodo_selecionado,
    data_inicio,
    data_fim,
    empresas_ids,
    projetos,
):
    data_inicio, data_fim = _resolver_datas(
        periodo_selecionado,
        data_inicio,
        data_fim,
    )
    itens = _query_itens(data_inicio, data_fim, empresas_ids, projetos)
    historico = _historico_produtos(empresas_ids)
    recebimentos = _recebimentos_por_pedido_produto(empresas_ids, data_inicio, data_fim)
    agregados = {}

    for item in itens:
        pedido = item.pedido
        codigo_fornecedor = pedido.codigo_fornecedor or 0
        dados = agregados.setdefault(
            codigo_fornecedor,
            {
                "nome": _nome_fornecedor(pedido),
                "otd": [],
                "nf": [],
                "preco": [],
                "pedidos": set(),
                "itens": 0,
            },
        )
        dados["pedidos"].add(pedido.pk)
        dados["itens"] += 1
        recebimento = _recebimento_do_item(item, recebimentos)
        quantidade_recebida = (
            recebimento.quantidade_nfe if recebimento else item.quantidade_recebida
        )
        dados["nf"].append(_pontuar_nf(item.quantidade, quantidade_recebida))
        dados["preco"].append(_pontuar_preco(item, historico))
        dados["otd"].append(
            _pontuar_otd(pedido.data_previsao, _data_real_recebimento(item, recebimento))
        )

    fornecedores = [
        _montar_fornecedor(codigo, dados) for codigo, dados in agregados.items()
    ]
    ranking = sorted(fornecedores, key=lambda item: item["score"], reverse=True)
    classificacoes = []
    for slug, rotulo, tom in (
        ("a", "A-excelente", "success"),
        ("b", "B - Muito bom", "primary"),
        ("c", "C - Bom", "warning"),
        ("d", "D- Atencao", "danger"),
    ):
        grupo = [item for item in ranking if item["classe_slug"] == slug]
        classificacoes.append(
            {
                "slug": slug,
                "rotulo": rotulo,
                "tom": tom,
                "fornecedores": grupo[:3],
                "total": len(grupo),
            }
        )

    if ranking:
        melhor_fornecedor = ranking[0]
        requer_atencao = min(ranking, key=lambda item: item["score"])
        score_medio = _inteiro(_media(item["score"] for item in ranking))
        otd_medio = _inteiro(_media(item["otd"] for item in ranking))
    else:
        melhor_fornecedor = {
            "nome": "Sem fornecedores",
            "score_fmt": "0",
            "classe": "Sem dados",
        }
        requer_atencao = melhor_fornecedor
        score_medio = 0
        otd_medio = 0

    return {
        "score_medio": score_medio,
        "score_medio_fmt": str(score_medio),
        "total_fornecedores": len(fornecedores),
        "melhor_fornecedor": melhor_fornecedor,
        "otd_medio": otd_medio,
        "otd_medio_fmt": _percentual(otd_medio),
        "requer_atencao": requer_atencao,
        "classificacoes": classificacoes,
        "fornecedores": fornecedores,
        "ranking": ranking[:10],
    }
