"""Calculos do dashboard financeiro Visao Geral."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.dashboards.finance_filters import (
    filtrar_por_categorias_financeiras,
    registros_com_conta_visivel_financeiro,
)
from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
)
from apps.empresas.models import (
    ContaPagarOmie,
    ContaReceberOmie,
    LancamentoContaCorrenteOmie,
)


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_moeda_curta(valor):
    valor = _decimal(valor)
    absoluto = abs(valor)
    if absoluto >= Decimal("1000000"):
        texto = f"{valor / Decimal('1000000'):.2f}"
        return f"R$ {texto} Mi"
    if absoluto >= Decimal("1000"):
        texto = f"{valor / Decimal('1000'):.2f}"
        return f"R$ {texto} Mil"
    return _formatar_moeda(valor)


def _media(total, quantidade):
    if not quantidade:
        return Decimal("0")
    return total / Decimal(quantidade)


def _query_receber(inicio, fim, empresas_ids, projetos, categorias):
    queryset = ContaReceberOmie.objects.annotate(
        data_referencia=Coalesce("data_registro", "data_previsao", "data_emissao"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = filtrar_por_categorias_financeiras(queryset, categorias)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_pagar(inicio, fim, empresas_ids, projetos, categorias):
    queryset = ContaPagarOmie.objects.annotate(
        data_referencia=Coalesce("data_entrada", "data_previsao", "data_vencimento"),
    ).filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_referencia__gte=inicio,
        data_referencia__lte=fim,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = filtrar_por_categorias_financeiras(queryset, categorias)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_caixa(inicio, fim, empresas_ids, projetos, natureza, categorias):
    queryset = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_lancamento__gte=inicio,
        data_lancamento__lte=fim,
        natureza=natureza,
    ).annotate(data_referencia=Coalesce("data_lancamento", "data_conciliacao"))
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = filtrar_por_categorias_financeiras(queryset, categorias)
    return registros_com_conta_visivel_financeiro(queryset, "codigo_conta_corrente")


def _totais_por_mes(queryset, campo_valor):
    totais = defaultdict(Decimal)
    linhas = (
        queryset.annotate(
            ano=ExtractYear("data_referencia"),
            mes=ExtractMonth("data_referencia"),
        )
        .values("ano", "mes")
        .annotate(total=Sum(campo_valor))
    )
    for item in linhas:
        totais[f"{item['ano']}-{item['mes']:02d}"] = _decimal(item["total"])
    return totais


def _ranking(queryset, tipo):
    if tipo == "receita":
        valores = queryset.values(
            "cliente__nome_fantasia",
            "cliente__razao_social",
            "categoria_principal__descricao",
            "codigo_categoria",
        ).annotate(total=Sum("valor_documento"))
        nome_keys = ("cliente__nome_fantasia", "cliente__razao_social")
        pessoa_padrao = "Cliente nao informado"
    else:
        valores = queryset.values(
            "fornecedor__nome_fantasia",
            "fornecedor__razao_social",
            "categoria_principal__descricao",
            "codigo_categoria",
        ).annotate(total=Sum("valor_documento"))
        nome_keys = ("fornecedor__nome_fantasia", "fornecedor__razao_social")
        pessoa_padrao = "Fornecedor nao informado"

    itens = []
    for item in valores.order_by("-total")[:5]:
        pessoa = item.get(nome_keys[0]) or item.get(nome_keys[1]) or pessoa_padrao
        categoria = item.get("categoria_principal__descricao") or item.get("codigo_categoria") or "Sem categoria"
        total = _decimal(item["total"])
        itens.append(
            {
                "pessoa": pessoa,
                "categoria": categoria,
                "valor": total,
                "valor_fmt": _formatar_moeda(total),
            }
        )
    return itens


def _ranking_caixa(queryset, pessoa_padrao):
    valores = queryset.values(
        "cliente_fornecedor__nome_fantasia",
        "cliente_fornecedor__razao_social",
        "categoria_principal__descricao",
        "codigo_categoria",
    ).annotate(total=Sum("valor_lancamento"))
    itens = []
    for item in valores.order_by("-total")[:5]:
        pessoa = (
            item.get("cliente_fornecedor__nome_fantasia")
            or item.get("cliente_fornecedor__razao_social")
            or pessoa_padrao
        )
        categoria = (
            item.get("categoria_principal__descricao")
            or item.get("codigo_categoria")
            or "Sem categoria"
        )
        total = abs(_decimal(item["total"]))
        itens.append(
            {
                "pessoa": pessoa,
                "categoria": categoria,
                "valor": total,
                "valor_fmt": _formatar_moeda(total),
            }
        )
    return itens


def visao_geral_financeira(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    regime_financeiro="caixa",
    categorias_selecionadas=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    categorias = _normalizar_filtro_composto(categorias_selecionadas or [])
    if regime_financeiro == "competencia":
        receber = _query_receber(inicio, fim, empresas_ids, projetos, categorias)
        pagar = _query_pagar(inicio, fim, empresas_ids, projetos, categorias)
        campo_receber = "valor_documento"
        campo_pagar = "valor_documento"
        maiores_clientes = _ranking(receber, "receita")
        maiores_fornecedores = _ranking(pagar, "despesa")
    else:
        receber = _query_caixa(inicio, fim, empresas_ids, projetos, "R", categorias)
        pagar = _query_caixa(inicio, fim, empresas_ids, projetos, "P", categorias)
        campo_receber = "valor_lancamento"
        campo_pagar = "valor_lancamento"
        maiores_clientes = _ranking_caixa(receber, "Cliente nao informado")
        maiores_fornecedores = _ranking_caixa(pagar, "Fornecedor nao informado")

    recebimentos = abs(_decimal(receber.aggregate(total=Sum(campo_receber))["total"]))
    pagamentos = abs(_decimal(pagar.aggregate(total=Sum(campo_pagar))["total"]))
    resultado = recebimentos - pagamentos
    media_recebimento = _media(recebimentos, len(meses))
    media_resultado = _media(resultado, len(meses))

    recebimentos_mes = _totais_por_mes(receber, campo_receber)
    pagamentos_mes = _totais_por_mes(pagar, campo_pagar)
    for chave, valor in list(recebimentos_mes.items()):
        recebimentos_mes[chave] = abs(valor)
    for chave, valor in list(pagamentos_mes.items()):
        pagamentos_mes[chave] = abs(valor)
    resultado_mes = {
        item["chave"]: recebimentos_mes[item["chave"]] - pagamentos_mes[item["chave"]]
        for item in meses
    }
    margem_mes = {
        item["chave"]: (
            (resultado_mes[item["chave"]] / recebimentos_mes[item["chave"]])
            * Decimal("100")
            if recebimentos_mes[item["chave"]]
            else Decimal("0")
        )
        for item in meses
    }

    return {
        "indicadores": [
            {
                "titulo": "Recebimentos",
                "valor": _formatar_moeda_curta(recebimentos),
                "valor_completo": _formatar_moeda(recebimentos),
                "icone": "bi-cash-stack",
                "tom": "positive",
            },
            {
                "titulo": "Pagamentos",
                "valor": _formatar_moeda_curta(pagamentos),
                "valor_completo": _formatar_moeda(pagamentos),
                "icone": "bi-arrow-down",
                "tom": "negative",
            },
            {
                "titulo": "Resultado",
                "valor": _formatar_moeda_curta(resultado),
                "valor_completo": _formatar_moeda(resultado),
                "icone": "bi-graph-up-arrow",
                "tom": "positive" if resultado >= 0 else "negative",
            },
            {
                "titulo": "Media de recebimento mensal",
                "valor": _formatar_moeda_curta(media_recebimento),
                "valor_completo": _formatar_moeda(media_recebimento),
                "icone": "bi-calendar2-check",
                "tom": "positive",
            },
            {
                "titulo": "Media de resultado mensal",
                "valor": _formatar_moeda_curta(media_resultado),
                "valor_completo": _formatar_moeda(media_resultado),
                "icone": "bi-speedometer2",
                "tom": "positive" if media_resultado >= 0 else "negative",
            },
        ],
        "labels": [item["rotulo"] for item in meses],
        "recebimentos": [float(recebimentos_mes[item["chave"]]) for item in meses],
        "pagamentos": [float(pagamentos_mes[item["chave"]]) for item in meses],
        "margem": [float(margem_mes[item["chave"]]) for item in meses],
        "maiores_clientes": maiores_clientes,
        "maiores_fornecedores": maiores_fornecedores,
    }
