"""Calculos do dashboard Fluxo de Caixa."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
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
    CategoriaOmie,
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    Empresa,
    LancamentoContaCorrenteOmie,
    MovimentoFinanceiroOmie,
)


STATUS_FECHADOS_RECEBER = {"RECEBIDO", "PAGO", "LIQUIDADO", "BAIXADO", "CANCELADO"}
STATUS_FECHADOS_PAGAR = {"PAGO", "LIQUIDADO", "BAIXADO", "CANCELADO"}
STATUS_MOVIMENTO_PAGO = {"PAGO", "LIQUIDADO", "BAIXADO", "RECEBIDO"}
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


def _excluir_status_fechados(queryset, campo, status_fechados):
    filtros = Q()
    for status in status_fechados:
        filtros |= Q(**{f"{campo}__iexact": status})
    return queryset.exclude(filtros) if filtros else queryset


def _query_receber_aberto(inicio, fim, empresas_ids, projetos):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
    )
    queryset = _excluir_status_fechados(
        queryset,
        "status_titulo",
        STATUS_FECHADOS_RECEBER,
    )
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
    )
    queryset = _excluir_status_fechados(
        queryset,
        "status_titulo",
        STATUS_FECHADOS_PAGAR,
    )
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
    )
    queryset = _excluir_status_fechados(
        queryset,
        "status_titulo",
        STATUS_FECHADOS_PAGAR,
    )
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
    )
    queryset = _excluir_status_fechados(
        queryset,
        "status_titulo",
        STATUS_FECHADOS_RECEBER,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_pagar_previsto_omie(hoje, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        data_previsao__lte=hoje,
    )
    queryset = _excluir_status_fechados(
        queryset,
        "status_titulo",
        STATUS_FECHADOS_PAGAR,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")


def _query_movimentos_previstos_omie(hoje, empresas_ids, projetos, natureza):
    grupo = "CONTA_A_RECEBER" if natureza == "R" else "CONTA_A_PAGAR"
    queryset = MovimentoFinanceiroOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        grupo=grupo,
        natureza=natureza,
        valor_aberto__gt=0,
        data_previsao__lte=hoje,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(queryset, "codigo_conta_corrente")


def _query_movimentos_financeiros(empresas_ids, projetos, natureza, inicio=None, fim=None):
    queryset = MovimentoFinanceiroOmie.objects.filter(
        empresa_id__in=empresas_ids,
        ativo_omie=True,
        natureza=natureza,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    if inicio and fim:
        queryset = queryset.filter(
            Q(data_previsao__gte=inicio, data_previsao__lte=fim)
            | Q(status__in=STATUS_MOVIMENTO_PAGO, data_pagamento__gte=inicio, data_pagamento__lte=fim)
            | Q(status__in=STATUS_MOVIMENTO_PAGO, data_pagamento__isnull=True, data_vencimento__gte=inicio, data_vencimento__lte=fim)
        )
    return registros_com_conta_visivel_financeiro(queryset, "codigo_conta_corrente")


def _movimento_pago(movimento):
    return str(movimento.status or "").upper() in STATUS_MOVIMENTO_PAGO


def _data_realizado_movimento(movimento):
    if not _movimento_pago(movimento):
        return None
    return movimento.data_pagamento or movimento.data_vencimento


def _valor_previsto_movimento(movimento):
    return _decimal(movimento.valor_aberto or movimento.valor_liquido or movimento.valor_titulo)


def _valor_realizado_movimento(movimento):
    return _decimal(
        movimento.valor_pago
        or movimento.valor_liquido
        or movimento.valor_titulo
    )


def _codigo_titulo_movimento(movimento):
    return movimento.codigo_titulo


def _total_previsto_movimentos(movimentos):
    total = Decimal("0")
    codigos = set()
    for movimento in movimentos:
        codigo = _codigo_titulo_movimento(movimento)
        if codigo and codigo in codigos:
            continue
        total += abs(_valor_previsto_movimento(movimento))
        if codigo:
            codigos.add(codigo)
    return total, codigos


def _total_receber_aberto_sem_movimento(queryset, codigos_movimentos):
    total = Decimal("0")
    for conta in queryset:
        if conta.codigo_lancamento_omie in codigos_movimentos:
            continue
        total += _valor_liquido_receber(conta)
    return total


def _total_pagar_aberto_sem_movimento(queryset, codigos_movimentos):
    total = Decimal("0")
    for conta in queryset:
        if conta.codigo_lancamento_omie in codigos_movimentos:
            continue
        total += _valor_pagar(conta)
    return total


def _linha_prevista_movimento(movimento):
    data = movimento.data_previsao or movimento.data_vencimento
    valor = abs(_valor_previsto_movimento(movimento))
    return {
        "data": data.strftime("%d/%m/%Y") if data else "",
        "nome": _nome_cliente_fornecedor(movimento),
        "categoria": _categoria_lancamento(movimento),
        "valor": float(valor),
        "valor_fmt": _formatar_moeda(valor),
    }


def _nome_conta_receber(conta):
    return (
        getattr(conta.cliente, "nome_fantasia", "")
        or getattr(conta.cliente, "razao_social", "")
        or "Cliente nao informado"
    )


def _nome_conta_pagar(conta):
    return (
        getattr(conta.fornecedor, "nome_fantasia", "")
        or getattr(conta.fornecedor, "razao_social", "")
        or "Fornecedor nao informado"
    )


def _categoria_conta(conta):
    return (
        getattr(conta.categoria_principal, "descricao", "")
        or conta.codigo_categoria
        or "Sem categoria"
    )


def _linha_prevista_conta_receber(conta):
    data = conta.data_previsao or conta.data_vencimento
    valor = abs(_valor_liquido_receber(conta))
    return {
        "data": data.strftime("%d/%m/%Y") if data else "",
        "nome": _nome_conta_receber(conta),
        "categoria": _categoria_conta(conta),
        "valor": float(valor),
        "valor_fmt": _formatar_moeda(valor),
    }


def _linha_prevista_conta_pagar(conta):
    data = conta.data_previsao or conta.data_vencimento
    valor = abs(_valor_pagar(conta))
    return {
        "data": data.strftime("%d/%m/%Y") if data else "",
        "nome": _nome_conta_pagar(conta),
        "categoria": _categoria_conta(conta),
        "valor": float(valor),
        "valor_fmt": _formatar_moeda(valor),
    }


def _detalhes_previstos(
    movimentos_receber,
    movimentos_pagar,
    receber_aberto,
    pagar_aberto,
    codigos_receber_movimentos,
    codigos_pagar_movimentos,
):
    entradas = [
        _linha_prevista_movimento(movimento)
        for movimento in movimentos_receber
    ]
    entradas.extend(
        _linha_prevista_conta_receber(conta)
        for conta in receber_aberto.select_related("cliente", "categoria_principal")
        if conta.codigo_lancamento_omie not in codigos_receber_movimentos
    )
    saidas = [
        _linha_prevista_movimento(movimento)
        for movimento in movimentos_pagar
    ]
    saidas.extend(
        _linha_prevista_conta_pagar(conta)
        for conta in pagar_aberto.select_related("fornecedor", "categoria_principal")
        if conta.codigo_lancamento_omie not in codigos_pagar_movimentos
    )

    def ordenar(item):
        data = item["data"].split("/")
        data_ordenacao = f"{data[2]}-{data[1]}-{data[0]}" if len(data) == 3 else ""
        return data_ordenacao, -item["valor"]

    return {
        "entradas": sorted(entradas, key=ordenar),
        "saidas": sorted(saidas, key=ordenar),
    }


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
    return {"diario": dias, "semanal": semanas, "anual": meses}


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


def _periodos_mensais_para_fluxo(meses):
    return [
        {
            "chave": item["chave"],
            "rotulo": item["rotulo"],
            "inicio": date(item["ano"], item["mes"], 1),
            "fim": date(item["ano"], item["mes"], monthrange(item["ano"], item["mes"])[1]),
        }
        for item in meses
    ]


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


def _chave_periodo_data(data, periodos):
    if not data:
        return ""
    for periodo in periodos:
        if periodo["inicio"] <= data <= periodo["fim"]:
            return periodo["chave"]
    return ""


def _codigo_categoria_item(item):
    codigo = str(getattr(item, "codigo_categoria", "") or "").strip()
    categoria = getattr(item, "categoria_principal", None)
    if not codigo and categoria:
        codigo = str(categoria.codigo or "").strip()
    return codigo or "sem_categoria"


def _nome_categoria_item(item):
    categoria = getattr(item, "categoria_principal", None)
    return (
        getattr(categoria, "descricao", "")
        or getattr(item, "codigo_categoria", "")
        or "Sem categoria"
    )


def _somar_categorias_por_periodo(
    queryset,
    periodos,
    data_accessor,
    valor_accessor,
    tipo,
):
    totais = defaultdict(lambda: {"previsao": defaultdict(Decimal), "realizado": defaultdict(Decimal)})
    nomes = {}
    codigos = set()
    if hasattr(queryset, "select_related"):
        queryset = queryset.select_related("categoria_principal")
    for item in queryset:
        data = data_accessor(item) if callable(data_accessor) else getattr(item, data_accessor)
        chave_periodo = _chave_periodo_data(data, periodos)
        if not chave_periodo:
            continue
        codigo = _codigo_categoria_item(item)
        valor = abs(_decimal(valor_accessor(item) if callable(valor_accessor) else getattr(item, valor_accessor)))
        if not valor:
            continue
        totais[codigo][tipo][chave_periodo] += valor
        nomes.setdefault(codigo, _nome_categoria_item(item))
        if codigo != "sem_categoria":
            codigos.add(codigo)
    return totais, nomes, codigos


def _linhas_categorias_horizontais(
    empresas_ids,
    periodos,
    previstos,
    realizados,
):
    totais = defaultdict(lambda: {"previsao": defaultdict(Decimal), "realizado": defaultdict(Decimal)})
    nomes = {}
    codigos = set()
    for origem, tipo in ((previstos, "previsao"), (realizados, "realizado")):
        origem_totais, origem_nomes, origem_codigos = origem
        codigos.update(origem_codigos)
        nomes.update(origem_nomes)
        for codigo, dados in origem_totais.items():
            for chave, valor in dados[tipo].items():
                totais[codigo][tipo][chave] += valor

    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa_id__in=empresas_ids,
            ativo_omie=True,
            codigo__in=codigos,
        )
    }
    pendentes = set(codigos)
    while pendentes:
        superiores = {
            categoria.categoria_superior
            for codigo, categoria in categorias.items()
            if codigo in pendentes and categoria.categoria_superior
        }
        superiores -= set(categorias)
        superiores.discard("0")
        superiores.discard("")
        if not superiores:
            break
        novos = {
            categoria.codigo: categoria
            for categoria in CategoriaOmie.objects.filter(
                empresa_id__in=empresas_ids,
                ativo_omie=True,
                codigo__in=superiores,
            )
        }
        if not novos:
            break
        categorias.update(novos)
        pendentes = set(novos)

    filhos = defaultdict(list)
    for codigo, categoria in categorias.items():
        pai = categoria.categoria_superior or ""
        if pai and pai in categorias:
            filhos[pai].append(codigo)

    for codigo, categoria in categorias.items():
        nomes.setdefault(codigo, categoria.descricao or codigo)
        totais.setdefault(codigo, {"previsao": defaultdict(Decimal), "realizado": defaultdict(Decimal)})

    totais_diretos = totais
    totais_agregados = defaultdict(
        lambda: {"previsao": defaultdict(Decimal), "realizado": defaultdict(Decimal)}
    )

    def agregar(codigo):
        if codigo in totais_agregados:
            return totais_agregados[codigo]
        for tipo in ("previsao", "realizado"):
            for chave, valor in totais_diretos[codigo][tipo].items():
                totais_agregados[codigo][tipo][chave] += valor
        for filho in filhos.get(codigo, []):
            totais_filho = agregar(filho)
            for tipo in ("previsao", "realizado"):
                for chave, valor in totais_filho[tipo].items():
                    totais_agregados[codigo][tipo][chave] += valor
        return totais_agregados[codigo]

    for codigo in list(totais_diretos):
        agregar(codigo)
    totais = totais_agregados

    roots = []
    for codigo in totais:
        if codigo == "sem_categoria":
            roots.append(codigo)
            continue
        categoria = categorias.get(codigo)
        if not categoria or not categoria.categoria_superior or categoria.categoria_superior not in categorias:
            roots.append(codigo)

    def valor_total(codigo):
        return sum(
            (
                totais[codigo][tipo].get(periodo["chave"], Decimal("0"))
                for tipo in ("previsao", "realizado")
                for periodo in periodos
            ),
            Decimal("0"),
        )

    def row_id(prefixo, codigo):
        seguro = "".join(char if char.isalnum() else "-" for char in str(codigo))
        return f"{prefixo}-{seguro}"

    linhas = []

    def adicionar(codigo, nivel, parent_id=""):
        children = sorted(filhos.get(codigo, []), key=lambda item: nomes.get(item, item))
        if codigo == "sem_categoria":
            children = []
        linha_id = row_id("cat", codigo)
        linhas.append(
            {
                "id": linha_id,
                "parent_id": parent_id,
                "nivel": nivel,
                "nome": nomes.get(codigo, codigo),
                "tem_filhos": bool(children),
                "oculta": bool(parent_id),
                "valores": _valores_horizontais(totais[codigo], periodos),
            }
        )
        for filho in children:
            adicionar(filho, nivel + 1, linha_id)

    for codigo in sorted(roots, key=lambda item: nomes.get(item, item)):
        if valor_total(codigo):
            adicionar(codigo, 0)
    return linhas


def _fluxo_horizontal(inicio, fim, empresas_ids, projetos, modos_selecionados=None):
    hoje = date.today()
    periodos_por_modo = _periodos_horizontais(inicio, fim)
    if modos_selecionados:
        permitidos = set(modos_selecionados)
        periodos_por_modo = {
            modo: periodos
            for modo, periodos in periodos_por_modo.items()
            if modo in permitidos
        }
    contas = list(
        contas_correntes_visiveis_financeiro(
            ContaCorrenteOmie.objects.filter(
                empresa_id__in=empresas_ids,
                ativo_omie=True,
                inativo=False,
            )
        ).order_by("descricao", "codigo_omie")
    )
    movimentos_receber = list(
        _query_movimentos_financeiros(
            empresas_ids,
            projetos,
            "R",
            inicio,
            fim,
        ).select_related("categoria_principal")
    )
    movimentos_pagar = list(
        _query_movimentos_financeiros(
            empresas_ids,
            projetos,
            "P",
            inicio,
            fim,
        ).select_related("categoria_principal")
    )

    modos = {}
    for modo, periodos in periodos_por_modo.items():
        inicio_modo = periodos[0]["inicio"]
        fim_modo = periodos[-1]["fim"]
        receber_periodo = movimentos_receber
        pagar_periodo = movimentos_pagar

        receitas = {
            "previsao": _somar_por_periodo(receber_periodo, periodos, "data_previsao", _valor_previsto_movimento),
            "realizado": _somar_por_periodo(receber_periodo, periodos, _data_realizado_movimento, _valor_realizado_movimento),
        }
        despesas = {
            "previsao": _somar_por_periodo(pagar_periodo, periodos, "data_previsao", _valor_previsto_movimento),
            "realizado": _somar_por_periodo(pagar_periodo, periodos, _data_realizado_movimento, _valor_realizado_movimento),
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
            "receitas_categorias": _linhas_categorias_horizontais(
                empresas_ids,
                periodos,
                _somar_categorias_por_periodo(receber_periodo, periodos, "data_previsao", _valor_previsto_movimento, "previsao"),
                _somar_categorias_por_periodo(receber_periodo, periodos, _data_realizado_movimento, _valor_realizado_movimento, "realizado"),
            ),
            "despesas_categorias": _linhas_categorias_horizontais(
                empresas_ids,
                periodos,
                _somar_categorias_por_periodo(pagar_periodo, periodos, "data_previsao", _valor_previsto_movimento, "previsao"),
                _somar_categorias_por_periodo(pagar_periodo, periodos, _data_realizado_movimento, _valor_realizado_movimento, "realizado"),
            ),
            "resultado": _valores_horizontais(resultado, periodos),
            "limite_rotulo": (
                f"{meses_nome(inicio_modo.month)} de {inicio_modo.year}"
                if modo in {"diario", "semanal"}
                else f"{_formatar_data_curta(inicio_modo)} a {_formatar_data_curta(fim_modo)}"
            ),
        }
        modos[modo]["saldo_inicial"] = _valores_horizontais(
            saldo_inicial_total,
            periodos,
        )
    return modos


def fluxo_de_caixa_horizontal(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    modo=None,
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    return {
        "modos": _fluxo_horizontal(
            inicio,
            fim,
            empresas_ids,
            projetos,
            [modo] if modo else None,
        ),
        "periodo_inicio": inicio,
        "periodo_fim": fim,
    }


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
        or getattr(lancamento, "observacao", "")
        or getattr(lancamento, "numero_titulo", "")
        or "Nao informado"
    )


def _categoria_lancamento(lancamento):
    return (
        getattr(lancamento.categoria_principal, "descricao", "")
        or lancamento.codigo_categoria
        or "Sem categoria"
    )


def _detalhes_lancamentos_por_mes(lancamentos, meses, data_accessor, valor_accessor):
    detalhes = {
        item["chave"]: {
            "rotulo": item["rotulo"],
            "entradas": [],
            "saidas": [],
        }
        for item in meses
    }
    if hasattr(lancamentos, "select_related"):
        lancamentos = lancamentos.select_related(
            "cliente_fornecedor",
            "categoria_principal",
        ).order_by("data_vencimento", "codigo_titulo")
    for lancamento in lancamentos:
        data = data_accessor(lancamento) if callable(data_accessor) else getattr(lancamento, data_accessor, None)
        if not data:
            continue
        chave = f"{data.year}-{data.month:02d}"
        if chave not in detalhes:
            continue
        tipo = "entradas" if lancamento.natureza == "R" else "saidas"
        valor = abs(valor_accessor(lancamento) if callable(valor_accessor) else _decimal(getattr(lancamento, valor_accessor)))
        detalhes[chave][tipo].append(
            {
                "data": data.strftime("%d/%m/%Y"),
                "nome": _nome_cliente_fornecedor(lancamento),
                "categoria": _categoria_lancamento(lancamento),
                "valor": float(valor),
                "valor_fmt": _formatar_moeda(valor),
            }
        )
    return detalhes


def _composicao_movimentos(queryset, data_accessor, valor_accessor):
    totais = defaultdict(Decimal)
    nomes = {}
    if hasattr(queryset, "select_related"):
        queryset = queryset.select_related("categoria_principal")
    for movimento in queryset:
        data = data_accessor(movimento) if callable(data_accessor) else getattr(movimento, data_accessor, None)
        if not data:
            continue
        codigo = _codigo_categoria_item(movimento)
        valor = abs(valor_accessor(movimento) if callable(valor_accessor) else _decimal(getattr(movimento, valor_accessor)))
        if not valor:
            continue
        totais[codigo] += valor
        nomes.setdefault(codigo, _nome_categoria_item(movimento))

    principais = []
    outros = Decimal("0")
    for indice, codigo in enumerate(sorted(totais, key=lambda item: totais[item], reverse=True)):
        total = totais[codigo]
        if indice < 4:
            principais.append({"nome": nomes.get(codigo, codigo), "valor": float(total)})
        else:
            outros += total
    if outros:
        principais.append({"nome": "Outros", "valor": float(outros)})
    return principais


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
    movimentos_receber = _query_movimentos_financeiros(
        empresas_ids,
        projetos,
        "R",
        inicio,
        fim,
    )
    movimentos_pagar = _query_movimentos_financeiros(
        empresas_ids,
        projetos,
        "P",
        inicio,
        fim,
    )
    movimentos_receber_lista = list(
        movimentos_receber.select_related("cliente_fornecedor", "categoria_principal")
    )
    movimentos_pagar_lista = list(
        movimentos_pagar.select_related("cliente_fornecedor", "categoria_principal")
    )
    receber_aberto = _query_receber_aberto(inicio, fim, empresas_ids, projetos)
    pagar_aberto = _query_pagar_aberto(inicio, fim, empresas_ids, projetos)
    periodos_mensais = _periodos_mensais_para_fluxo(meses)

    entradas_realizadas_mes = _somar_por_periodo(
        movimentos_receber_lista,
        periodos_mensais,
        _data_realizado_movimento,
        _valor_realizado_movimento,
    )
    saidas_realizadas_mes = _somar_por_periodo(
        movimentos_pagar_lista,
        periodos_mensais,
        _data_realizado_movimento,
        _valor_realizado_movimento,
    )
    entradas_realizadas = sum(entradas_realizadas_mes.values(), Decimal("0"))
    saidas_realizadas = sum(saidas_realizadas_mes.values(), Decimal("0"))
    movimentos_receber_previstos = list(
        _query_movimentos_previstos_omie(hoje, empresas_ids, projetos, "R")
    )
    movimentos_pagar_previstos = list(
        _query_movimentos_previstos_omie(hoje, empresas_ids, projetos, "P")
    )
    entradas_previstas, codigos_receber_movimentos = _total_previsto_movimentos(
        movimentos_receber_previstos
    )
    saidas_previstas, codigos_pagar_movimentos = _total_previsto_movimentos(
        movimentos_pagar_previstos
    )
    entradas_previstas += _total_receber_aberto_sem_movimento(
        _query_receber_previsto_omie(hoje, empresas_ids, projetos),
        codigos_receber_movimentos,
    )
    saidas_previstas += _total_pagar_aberto_sem_movimento(
        _query_pagar_previsto_omie(hoje, empresas_ids, projetos),
        codigos_pagar_movimentos,
    )
    detalhes_previstos = _detalhes_previstos(
        movimentos_receber_previstos,
        movimentos_pagar_previstos,
        _query_receber_previsto_omie(hoje, empresas_ids, projetos),
        _query_pagar_previsto_omie(hoje, empresas_ids, projetos),
        codigos_receber_movimentos,
        codigos_pagar_movimentos,
    )
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

    movimentos_realizados = [
        movimento
        for movimento in movimentos_receber_lista + movimentos_pagar_lista
        if inicio <= (_data_realizado_movimento(movimento) or date.min) <= fim
    ]
    detalhes_lancamentos = _detalhes_lancamentos_por_mes(
        movimentos_realizados,
        meses,
        _data_realizado_movimento,
        _valor_realizado_movimento,
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
                "detalhe_tipo": "entradas",
            },
            {
                "titulo": "Saidas previstas",
                "valor": _formatar_moeda_curta(saidas_previstas),
                "valor_completo": _formatar_moeda(saidas_previstas),
                "icone": "bi-arrow-up-right-circle",
                "tom": "negative",
                "detalhe_tipo": "saidas",
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
        "detalhes_previstos": detalhes_previstos,
        "criticos": _criticos(receber_aberto, pagar_aberto),
        "composicao_entradas": _composicao_movimentos(
            [
                movimento
                for movimento in movimentos_receber_lista
                if inicio <= (_data_realizado_movimento(movimento) or date.min) <= fim
            ],
            _data_realizado_movimento,
            _valor_realizado_movimento,
        ),
        "composicao_saidas": _composicao_movimentos(
            [
                movimento
                for movimento in movimentos_pagar_lista
                if inicio <= (_data_realizado_movimento(movimento) or date.min) <= fim
            ],
            _data_realizado_movimento,
            _valor_realizado_movimento,
        ),
    }
