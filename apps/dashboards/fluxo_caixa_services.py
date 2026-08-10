"""Calculos do dashboard Fluxo de Caixa."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from apps.dashboards.finance_filters import (
    contas_correntes_visiveis_financeiro,
    registros_com_conta_visivel_financeiro,
)
from apps.dashboards.dre_services import (
    _formatar_moeda,
    _intervalo_periodo,
    _meses_do_intervalo,
    _normalizar_filtro_composto,
)
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    Empresa,
    LancamentoContaCorrenteOmie,
    MovimentoFinanceiroOmie,
)


STATUS_FECHADOS_RECEBER = {"RECEBIDO", "LIQUIDADO", "BAIXADO", "CANCELADO"}
STATUS_FECHADOS_PAGAR = {"PAGO", "LIQUIDADO", "BAIXADO", "CANCELADO"}
CHAVES_RETENCOES_RECEBER = (
    "valor_iss",
    "valor_pis",
    "valor_cofins",
    "valor_csll",
    "valor_ir",
    "valor_inss",
    "valor_outras_retencoes",
)


def _decimal(valor):
    if valor is None or valor == "":
        return Decimal("0")
    return Decimal(str(valor))


def _query_receber_aberto(inicio, fim, empresas_ids, projetos):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
    ).exclude(status_titulo__in=STATUS_FECHADOS_RECEBER)
    if inicio:
        queryset = queryset.filter(data_vencimento__gte=inicio)
    if fim:
        queryset = queryset.filter(data_vencimento__lte=fim)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_pagar_aberto(inicio, fim, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
    ).exclude(status_titulo__in=STATUS_FECHADOS_PAGAR)
    if inicio:
        queryset = queryset.filter(data_previsao__gte=inicio)
    if fim:
        queryset = queryset.filter(data_previsao__lte=fim)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_pagar_aberto_por_vencimento(inicio, fim, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
    ).exclude(status_titulo__in=STATUS_FECHADOS_PAGAR)
    if inicio:
        queryset = queryset.filter(data_vencimento__gte=inicio)
    if fim:
        queryset = queryset.filter(data_vencimento__lte=fim)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_receber_previsto_omie(hoje, empresas_ids, projetos):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_previsao__lte=hoje,
    ).exclude(status_titulo__in=STATUS_FECHADOS_RECEBER)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_pagar_previsto_omie(hoje, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_vencimento__lte=hoje,
    ).exclude(status_titulo__in=STATUS_FECHADOS_PAGAR)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_movimentos_pagar_previstos_omie(hoje, empresas_ids, projetos):
    queryset = MovimentoFinanceiroOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        grupo="CONTA_A_PAGAR",
        natureza="P",
        liquidado=False,
        data_vencimento__lte=hoje,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return queryset


def _query_lancamentos(inicio, fim, empresas_ids, projetos, natureza):
    queryset = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_lancamento__gte=inicio,
        data_lancamento__lte=fim,
        natureza=natureza,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "codigo_conta_corrente")


def _saldo_contas_correntes(empresas_ids):
    return _decimal(
        contas_correntes_visiveis_financeiro(
            ContaCorrenteOmie.objects.filter(
                empresa_id__in=empresas_ids,
                ativo_omie=True,
                inativo=False,
                saldo_atual__isnull=False,
            )
        ).aggregate(total=Sum("saldo_atual"))["total"]
    )


def _total_resumo_financeiro_omie(empresas_ids, chave):
    total = Decimal("0")
    encontrou_resumo = False
    for resumo in Empresa.objects.filter(id__in=empresas_ids).values_list(
        "resumo_financeiro_omie",
        flat=True,
    ):
        dados_chave = (resumo or {}).get(chave) or {}
        if "vTotal" not in dados_chave:
            continue
        encontrou_resumo = True
        total += _decimal(dados_chave.get("vTotal"))
    return total if encontrou_resumo else None


def _saldo_abertura_extrato_contas_correntes(empresas_ids, inicio):
    contas = contas_correntes_visiveis_financeiro(
        ContaCorrenteOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            inativo=False,
        )
    )
    data_inicio = inicio.strftime("%d/%m/%Y")
    saldo = Decimal("0")
    contas_com_extrato = 0
    total_contas = 0
    for conta in contas:
        total_contas += 1
        extrato = (conta.dados_originais or {}).get("extrato") or {}
        if extrato.get("dPeriodoInicial") != data_inicio:
            continue
        saldo += _decimal(extrato.get("nSaldoAnterior"))
        contas_com_extrato += 1
    if total_contas and contas_com_extrato == total_contas:
        return saldo
    return None


def _movimento_lancamentos(lancamentos):
    return abs(
        _decimal(lancamentos.aggregate(total=Sum("valor_lancamento"))["total"])
    )


def _saldo_abertura_por_movimentos(saldo_atual, inicio, hoje, empresas_ids, projetos):
    if inicio > hoje:
        return saldo_atual
    entradas_ate_hoje = _movimento_lancamentos(
        _query_lancamentos(inicio, hoje, empresas_ids, projetos, "R")
    )
    saidas_ate_hoje = _movimento_lancamentos(
        _query_lancamentos(inicio, hoje, empresas_ids, projetos, "P")
    )
    return saldo_atual - entradas_ate_hoje + saidas_ate_hoje


def _valor_liquido_receber(conta):
    valor = _decimal(conta.valor_a_receber or conta.valor_documento)
    dados = conta.dados_originais or {}
    retencoes = sum(_decimal(dados.get(chave)) for chave in CHAVES_RETENCOES_RECEBER)
    return max(valor - retencoes, Decimal("0"))


def _total_liquido_receber(queryset):
    return sum((_valor_liquido_receber(conta) for conta in queryset), Decimal("0"))


def _totais_por_mes(queryset, data_field, valor_field):
    totais = defaultdict(Decimal)
    linhas = (
        queryset.annotate(
            ano=ExtractYear(data_field),
            mes=ExtractMonth(data_field),
        )
        .values("ano", "mes")
        .annotate(total=Sum(valor_field))
    )
    for item in linhas:
        totais[f"{item['ano']}-{item['mes']:02d}"] = abs(_decimal(item["total"]))
    return totais


def _formatar_data_curta(valor):
    return valor.strftime("%d/%m") if valor else "-"


def _periodos_horizontais(inicio, fim):
    mes_inicio = date(inicio.year, inicio.month, 1)
    mes_fim = date(inicio.year, inicio.month, monthrange(inicio.year, inicio.month)[1])

    dias = [
        {
            "chave": f"dia-{dia.day:02d}",
            "rotulo": dia.strftime("%d/%m"),
            "inicio": dia,
            "fim": dia,
        }
        for dia in (date(inicio.year, inicio.month, numero) for numero in range(1, mes_fim.day + 1))
    ]

    semanas = []
    atual = mes_inicio
    indice = 1
    while atual <= mes_fim:
        fim_semana = min(atual + timedelta(days=6 - atual.weekday()), mes_fim)
        semanas.append(
            {
                "chave": f"semana-{indice}",
                "rotulo": f"Sem {indice}",
                "subrotulo": f"{_formatar_data_curta(atual)} a {_formatar_data_curta(fim_semana)}",
                "inicio": atual,
                "fim": fim_semana,
            }
        )
        if fim_semana >= mes_fim:
            break
        atual = fim_semana + timedelta(days=1)
        indice += 1

    meses = [
        {
            "chave": item["chave"],
            "rotulo": item["rotulo"],
            "inicio": date(item["ano"], item["mes"], 1),
            "fim": date(item["ano"], item["mes"], monthrange(item["ano"], item["mes"])[1]),
        }
        for item in _meses_do_intervalo(inicio, fim)
    ]
    return {"diario": dias, "semanal": semanas, "mensal": meses}


def _somar_por_periodo(queryset, periodos, data_field, valor_fn):
    totais = {item["chave"]: Decimal("0") for item in periodos}
    for registro in queryset:
        data = data_field(registro) if callable(data_field) else getattr(registro, data_field, None)
        if not data:
            continue
        for periodo in periodos:
            if periodo["inicio"] <= data <= periodo["fim"]:
                totais[periodo["chave"]] += abs(valor_fn(registro))
                break
    return totais


def _valor_pagar(conta):
    return _decimal(conta.valor_a_pagar or conta.valor_documento)


def _valor_lancamento(lancamento):
    return _decimal(lancamento.valor_lancamento)


def _data_previsao_titulo(conta):
    return conta.data_previsao or conta.data_vencimento


def _saldo_inicial_conta(conta, inicio, hoje):
    data_inicio = inicio.strftime("%d/%m/%Y")
    extrato = (conta.dados_originais or {}).get("extrato") or {}
    if extrato.get("dPeriodoInicial") == data_inicio:
        return _decimal(extrato.get("nSaldoAnterior"))
    saldo = _decimal(conta.saldo_atual)
    if inicio > hoje:
        return saldo
    lancamentos = LancamentoContaCorrenteOmie.objects.filter(
        empresa=conta.empresa,
        ativo_omie=True,
        codigo_conta_corrente=conta.codigo_omie,
        data_lancamento__gte=inicio,
        data_lancamento__lte=hoje,
    )
    lancamentos = registros_com_conta_visivel_financeiro(
        lancamentos,
        "codigo_conta_corrente",
    )
    entradas = _movimento_lancamentos(lancamentos.filter(natureza="R"))
    saidas = _movimento_lancamentos(lancamentos.filter(natureza="P"))
    return saldo - entradas + saidas


def _valores_horizontais(totais, periodos):
    return [
        {
            "previsao": _formatar_moeda(totais["previsao"].get(periodo["chave"], Decimal("0"))),
            "realizado": _formatar_moeda(totais["realizado"].get(periodo["chave"], Decimal("0"))),
        }
        for periodo in periodos
    ]


def _fluxo_horizontal(inicio, fim, empresas_ids, projetos):
    hoje = date.today()
    periodos_por_modo = _periodos_horizontais(inicio, fim)
    contas = list(
        contas_correntes_visiveis_financeiro(
            ContaCorrenteOmie.objects.filter(
                empresa_id__in=empresas_ids,
                ativo_omie=True,
                inativo=False,
            )
        ).order_by("descricao", "codigo_omie")
    )
    receber = _query_receber_aberto(None, None, empresas_ids, projetos)
    pagar = _query_pagar_aberto(None, None, empresas_ids, projetos)
    lanc_recebidos = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        natureza="R",
    )
    lanc_pagos = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        natureza="P",
    )
    if projetos:
        lanc_recebidos = lanc_recebidos.filter(codigo_projeto__in=projetos)
        lanc_pagos = lanc_pagos.filter(codigo_projeto__in=projetos)
    lanc_recebidos = registros_com_conta_visivel_financeiro(
        lanc_recebidos,
        "codigo_conta_corrente",
    )
    lanc_pagos = registros_com_conta_visivel_financeiro(
        lanc_pagos,
        "codigo_conta_corrente",
    )

    modos = {}
    for modo, periodos in periodos_por_modo.items():
        inicio_modo = periodos[0]["inicio"]
        fim_modo = periodos[-1]["fim"]
        receber_periodo = receber
        pagar_periodo = pagar
        recebidos_periodo = lanc_recebidos.filter(data_lancamento__gte=inicio_modo, data_lancamento__lte=fim_modo)
        pagos_periodo = lanc_pagos.filter(data_lancamento__gte=inicio_modo, data_lancamento__lte=fim_modo)

        receitas = {
            "previsao": _somar_por_periodo(receber_periodo, periodos, _data_previsao_titulo, _valor_liquido_receber),
            "realizado": _somar_por_periodo(recebidos_periodo, periodos, "data_lancamento", _valor_lancamento),
        }
        despesas = {
            "previsao": _somar_por_periodo(pagar_periodo, periodos, _data_previsao_titulo, _valor_pagar),
            "realizado": _somar_por_periodo(pagos_periodo, periodos, "data_lancamento", _valor_lancamento),
        }
        saldo_inicial_total = {"previsao": {}, "realizado": {}}
        saldo_rows = []
        for conta in contas:
            valores = {"previsao": {}, "realizado": {}}
            for periodo in periodos:
                saldo = _saldo_inicial_conta(conta, periodo["inicio"], hoje)
                valores["previsao"][periodo["chave"]] = saldo
                valores["realizado"][periodo["chave"]] = saldo
                saldo_inicial_total["previsao"][periodo["chave"]] = (
                    saldo_inicial_total["previsao"].get(periodo["chave"], Decimal("0")) + saldo
                )
                saldo_inicial_total["realizado"][periodo["chave"]] = (
                    saldo_inicial_total["realizado"].get(periodo["chave"], Decimal("0")) + saldo
                )
            saldo_rows.append(
                {
                    "nome": conta.descricao or str(conta.codigo_omie),
                    "valores": _valores_horizontais(valores, periodos),
                }
            )

        resultado = {"previsao": {}, "realizado": {}}
        for periodo in periodos:
            chave = periodo["chave"]
            for tipo in ("previsao", "realizado"):
                resultado[tipo][chave] = (
                    saldo_inicial_total[tipo].get(chave, Decimal("0"))
                    + receitas[tipo].get(chave, Decimal("0"))
                    - despesas[tipo].get(chave, Decimal("0"))
                )

        modos[modo] = {
            "periodos": periodos,
            "colspan": (len(periodos) * 2) + 1,
            "saldo_contas": saldo_rows,
            "receitas": _valores_horizontais(receitas, periodos),
            "despesas": _valores_horizontais(despesas, periodos),
            "resultado": _valores_horizontais(resultado, periodos),
            "limite_rotulo": (
                f"{meses_nome(inicio_modo.month)} de {inicio_modo.year}"
                if modo in {"diario", "semanal"}
                else f"{_formatar_data_curta(inicio_modo)} a {_formatar_data_curta(fim_modo)}"
            ),
        }
    return modos


def meses_nome(numero):
    nomes = (
        "Janeiro",
        "Fevereiro",
        "Marco",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro",
    )
    return nomes[numero - 1]


def _composicao(queryset, valor_field):
    linhas = (
        queryset.values("categoria_principal__descricao", "codigo_categoria")
        .annotate(total=Sum(valor_field))
        .order_by("-total")
    )
    principais = []
    outros = Decimal("0")
    for indice, item in enumerate(linhas):
        total = abs(_decimal(item["total"]))
        if not total:
            continue
        nome = (
            item["categoria_principal__descricao"]
            or item["codigo_categoria"]
            or "Sem categoria"
        )
        if indice < 4:
            principais.append({"nome": nome, "valor": float(total)})
        else:
            outros += total
    if outros:
        principais.append({"nome": "Outros", "valor": float(outros)})
    return principais


def _nome_cliente_fornecedor(lancamento):
    cadastro = lancamento.cliente_fornecedor
    return (
        getattr(cadastro, "nome_fantasia", "")
        or getattr(cadastro, "razao_social", "")
        or lancamento.observacao
        or "Nao informado"
    )


def _categoria_lancamento(lancamento):
    return (
        getattr(lancamento.categoria_principal, "descricao", "")
        or lancamento.codigo_categoria
        or "Sem categoria"
    )


def _detalhes_lancamentos_por_mes(lancamentos, meses):
    detalhes = {
        item["chave"]: {
            "rotulo": item["rotulo"],
            "entradas": [],
            "saidas": [],
        }
        for item in meses
    }
    for lancamento in lancamentos.select_related(
        "cliente_fornecedor",
        "categoria_principal",
    ).order_by("data_lancamento", "codigo_lancamento_omie"):
        if not lancamento.data_lancamento:
            continue
        chave = f"{lancamento.data_lancamento.year}-{lancamento.data_lancamento.month:02d}"
        if chave not in detalhes:
            continue
        tipo = "entradas" if lancamento.natureza == "R" else "saidas"
        valor = abs(_decimal(lancamento.valor_lancamento))
        detalhes[chave][tipo].append(
            {
                "data": lancamento.data_lancamento.strftime("%d/%m/%Y"),
                "nome": _nome_cliente_fornecedor(lancamento),
                "categoria": _categoria_lancamento(lancamento),
                "valor": float(valor),
                "valor_fmt": _formatar_moeda(valor),
            }
        )
    return detalhes


def _prazo_medio_pagamento(pagar):
    prazos = []
    for conta in pagar.exclude(data_entrada__isnull=True).exclude(
        data_vencimento__isnull=True
    ):
        prazos.append((conta.data_vencimento - conta.data_entrada).days)
    if not prazos:
        return "0 dias"
    media = round(sum(prazos) / len(prazos))
    return f"{media} dias"


def _criticos(receber, pagar):
    hoje = date.today()
    itens = []
    for conta in receber.filter(data_vencimento__lt=hoje).select_related(
        "cliente", "categoria_principal"
    ):
        valor = abs(_valor_liquido_receber(conta))
        itens.append(
            {
                "nome": (
                    getattr(conta.cliente, "nome_fantasia", "")
                    or getattr(conta.cliente, "razao_social", "")
                    or "Cliente nao informado"
                ),
                "vencimento": conta.data_vencimento,
                "vencimento_fmt": conta.data_vencimento.strftime("%d/%m/%Y"),
                "valor": valor,
                "valor_fmt": _formatar_moeda(valor),
                "dias": (hoje - conta.data_vencimento).days,
            }
        )
    for conta in pagar.filter(data_vencimento__lt=hoje).select_related(
        "fornecedor", "categoria_principal"
    ):
        valor = abs(_decimal(conta.valor_a_pagar or conta.valor_documento))
        itens.append(
            {
                "nome": (
                    getattr(conta.fornecedor, "nome_fantasia", "")
                    or getattr(conta.fornecedor, "razao_social", "")
                    or "Fornecedor nao informado"
                ),
                "vencimento": conta.data_vencimento,
                "vencimento_fmt": conta.data_vencimento.strftime("%d/%m/%Y"),
                "valor": valor,
                "valor_fmt": _formatar_moeda(valor),
                "dias": (hoje - conta.data_vencimento).days,
            }
        )
    return sorted(itens, key=lambda item: (item["dias"], item["valor"]), reverse=True)[:5]


def fluxo_de_caixa(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])

    hoje = date.today()
    saldo_atual = _saldo_contas_correntes(empresas_ids)
    saldo_abertura_extrato = _saldo_abertura_extrato_contas_correntes(
        empresas_ids,
        inicio,
    )
    lanc_recebidos = _query_lancamentos(inicio, fim, empresas_ids, projetos, "R")
    lanc_pagos = _query_lancamentos(inicio, fim, empresas_ids, projetos, "P")
    receber_aberto = _query_receber_aberto(inicio, fim, empresas_ids, projetos)
    pagar_aberto = _query_pagar_aberto(inicio, fim, empresas_ids, projetos)
    receber_previsto = _query_receber_previsto_omie(hoje, empresas_ids, projetos)
    pagar_previsto = _query_pagar_previsto_omie(hoje, empresas_ids, projetos)
    movimentos_pagar_previsto = _query_movimentos_pagar_previstos_omie(
        hoje,
        empresas_ids,
        projetos,
    )

    entradas_realizadas = abs(
        _decimal(lanc_recebidos.aggregate(total=Sum("valor_lancamento"))["total"])
    )
    saidas_realizadas = abs(
        _decimal(lanc_pagos.aggregate(total=Sum("valor_lancamento"))["total"])
    )
    entradas_previstas_resumo = None
    saidas_previstas_resumo = None
    if not projetos:
        entradas_previstas_resumo = _total_resumo_financeiro_omie(
            empresas_ids,
            "contaReceber",
        )
        saidas_previstas_resumo = _total_resumo_financeiro_omie(
            empresas_ids,
            "contaPagar",
        )

    entradas_previstas = abs(_total_liquido_receber(receber_previsto))
    if entradas_previstas_resumo is not None:
        entradas_previstas = abs(entradas_previstas_resumo)

    saidas_previstas = abs(
        _decimal(movimentos_pagar_previsto.aggregate(total=Sum("valor_aberto"))["total"])
    )
    if not movimentos_pagar_previsto.exists():
        saidas_previstas = abs(
            _decimal(pagar_previsto.aggregate(total=Sum("valor_a_pagar"))["total"])
        )
    if saidas_previstas_resumo is not None:
        saidas_previstas = abs(saidas_previstas_resumo)
    saldo_abertura_periodo = saldo_abertura_extrato
    if saldo_abertura_periodo is None:
        saldo_abertura_periodo = _saldo_abertura_por_movimentos(
            saldo_atual,
            inicio,
            hoje,
            empresas_ids,
            projetos,
        )
    saldo_periodo = entradas_realizadas - saidas_realizadas
    saldo_projetado = (
        saldo_abertura_periodo
        + saldo_periodo
        + entradas_previstas
        - saidas_previstas
    )

    entradas_realizadas_mes = _totais_por_mes(
        lanc_recebidos,
        "data_lancamento",
        "valor_lancamento",
    )
    saidas_realizadas_mes = _totais_por_mes(
        lanc_pagos,
        "data_lancamento",
        "valor_lancamento",
    )

    entradas = []
    saidas = []
    saldo_acumulado = []
    saldo_corrente = saldo_abertura_periodo
    for item in meses:
        chave = item["chave"]
        entrada = entradas_realizadas_mes[chave]
        saida = saidas_realizadas_mes[chave]
        entradas.append(float(entrada))
        saidas.append(float(saida))
        saldo_acumulado.append(float(saldo_corrente))
        saldo_corrente += entrada - saida

    detalhes_lancamentos = _detalhes_lancamentos_por_mes(
        lanc_recebidos | lanc_pagos,
        meses,
    )

    return {
        "indicadores": [
            {
                "titulo": "Saldo atual",
                "valor": _formatar_moeda_curta(saldo_atual),
                "valor_completo": _formatar_moeda(saldo_atual),
                "icone": "bi-bank",
                "tom": "positive" if saldo_atual >= 0 else "negative",
            },
            {
                "titulo": "Entradas previstas",
                "valor": _formatar_moeda_curta(entradas_previstas),
                "valor_completo": _formatar_moeda(entradas_previstas),
                "icone": "bi-arrow-down-left-circle",
                "tom": "positive",
            },
            {
                "titulo": "Saidas previstas",
                "valor": _formatar_moeda_curta(saidas_previstas),
                "valor_completo": _formatar_moeda(saidas_previstas),
                "icone": "bi-arrow-up-right-circle",
                "tom": "negative",
            },
            {
                "titulo": "Saldo projetado",
                "valor": _formatar_moeda_curta(saldo_projetado),
                "valor_completo": _formatar_moeda(saldo_projetado),
                "icone": "bi-graph-up",
                "tom": "positive" if saldo_projetado >= 0 else "negative",
            },
            {
                "titulo": "Prazo medio de pagamento",
                "valor": _prazo_medio_pagamento(pagar_aberto),
                "valor_completo": _prazo_medio_pagamento(pagar_aberto),
                "icone": "bi-clock-history",
                "tom": "neutral",
            },
        ],
        "labels": [item["rotulo"] for item in meses],
        "entradas": entradas,
        "saidas": saidas,
        "saldo_acumulado": saldo_acumulado,
        "detalhes_lancamentos": detalhes_lancamentos,
        "criticos": _criticos(receber_aberto, pagar_aberto),
        "composicao_entradas": _composicao(lanc_recebidos, "valor_lancamento"),
        "composicao_saidas": _composicao(lanc_pagos, "valor_lancamento"),
        "horizontal": _fluxo_horizontal(inicio, fim, empresas_ids, projetos),
    }
