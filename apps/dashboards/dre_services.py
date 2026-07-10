"""Calculos do dashboard DRE Gerencial."""

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear

from apps.empresas.models import (
    ContaDRE,
    ContaPagarOmie,
    ContaReceberOmie,
    LancamentoContaCorrenteOmie,
)


NOMES_MESES = (
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
)


def _decimal(valor):
    return valor or Decimal("0")


def _formatar_moeda(valor):
    valor = _decimal(valor).quantize(Decimal("0.01"))
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _formatar_percentual(valor):
    return f"{valor:.1f}%".replace(".", ",")


def _mes_anterior(ano, mes):
    if mes == 1:
        return ano - 1, 12
    return ano, mes - 1


def _intervalo_periodo(periodo, data_inicio="", data_fim=""):
    hoje = date.today()
    if periodo == "personalizado" and data_inicio and data_fim:
        inicio_partes = [int(parte) for parte in data_inicio.split("-")]
        fim_partes = [int(parte) for parte in data_fim.split("-")]
        return date(*inicio_partes), date(*fim_partes)

    partes = (periodo or f"ano-{hoje.year}").split("-")
    if partes[0] == "mes":
        ano = int(partes[1])
        mes = int(partes[2])
        return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    if partes[0] == "tri":
        ano = int(partes[1])
        mes_inicial = ((int(partes[2]) - 1) * 3) + 1
        mes_final = mes_inicial + 2
        return date(ano, mes_inicial, 1), date(
            ano,
            mes_final,
            monthrange(ano, mes_final)[1],
        )
    ano = int(partes[1]) if len(partes) > 1 else hoje.year
    return date(ano, 1, 1), date(ano, 12, 31)


def _meses_do_intervalo(inicio, fim):
    meses = []
    ano = inicio.year
    mes = inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        meses.append(
            {
                "ano": ano,
                "mes": mes,
                "chave": f"{ano}-{mes:02d}",
                "rotulo": f"{NOMES_MESES[mes - 1]}/{str(ano)[-2:]}",
            }
        )
        mes += 1
        if mes == 13:
            mes = 1
            ano += 1
    return meses


def _porcentagem(valor, base):
    valor = _decimal(valor)
    base = _decimal(base)
    if not base:
        return Decimal("0")
    return (valor / base) * Decimal("100")


def _variacao_percentual(valor, anterior):
    valor = _decimal(valor)
    anterior = _decimal(anterior)
    if not anterior:
        return Decimal("0")
    return ((valor - anterior) / abs(anterior)) * Decimal("100")


def _direcao(valor):
    if valor > 0:
        return "up"
    if valor < 0:
        return "down"
    return "flat"


def _meses_consulta(meses):
    consulta = set()
    for item in meses:
        consulta.add((item["ano"], item["mes"]))
        consulta.add(_mes_anterior(item["ano"], item["mes"]))
    return consulta


def _normalizar_filtro_composto(valores):
    normalizados = []
    for valor in valores:
        partes = str(valor).split(":", 1)
        normalizados.append(partes[1] if len(partes) == 2 else str(valor))
    return normalizados


def _mapa_lancamentos_caixa(fim, meses, empresas_ids, projetos):
    ano_primeiro, mes_primeiro = _mes_anterior(meses[0]["ano"], meses[0]["mes"])
    data_inicio_consulta = date(ano_primeiro, mes_primeiro, 1)
    queryset = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_lancamento__gte=data_inicio_consulta,
        data_lancamento__lte=fim,
        categoria_principal__conta_dre__isnull=False,
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    queryset = queryset.values(
        "categoria_principal__conta_dre_id",
        "data_lancamento__year",
        "data_lancamento__month",
    ).annotate(total=Sum("valor_lancamento"))

    totais = defaultdict(Decimal)
    for item in queryset:
        chave = (
            item["categoria_principal__conta_dre_id"],
            item["data_lancamento__year"],
            item["data_lancamento__month"],
        )
        totais[chave] += _decimal(item["total"])
    return totais


def _mapa_lancamentos_competencia(fim, meses, empresas_ids, projetos):
    ano_primeiro, mes_primeiro = _mes_anterior(meses[0]["ano"], meses[0]["mes"])
    data_inicio_consulta = date(ano_primeiro, mes_primeiro, 1)
    totais = defaultdict(Decimal)
    receber = ContaReceberOmie.objects.annotate(
        data_referencia=Coalesce("data_registro", "data_previsao", "data_emissao"),
    ).filter(
        empresa_id__in=empresas_ids,
        data_referencia__gte=data_inicio_consulta,
        data_referencia__lte=fim,
        categoria_principal__conta_dre__isnull=False,
    )
    pagar = ContaPagarOmie.objects.annotate(
        data_referencia=Coalesce("data_entrada", "data_previsao", "data_vencimento"),
    ).filter(
        empresa_id__in=empresas_ids,
        data_referencia__gte=data_inicio_consulta,
        data_referencia__lte=fim,
        categoria_principal__conta_dre__isnull=False,
    )
    if projetos:
        receber = receber.filter(codigo_projeto__in=projetos)
        pagar = pagar.filter(codigo_projeto__in=projetos)

    for queryset in (receber, pagar):
        linhas = (
            queryset.annotate(
                ano=ExtractYear("data_referencia"),
                mes=ExtractMonth("data_referencia"),
            )
            .values("categoria_principal__conta_dre_id", "ano", "mes")
            .annotate(total=Sum("valor_documento"))
        )
        for item in linhas:
            chave = (
                item["categoria_principal__conta_dre_id"],
                item["ano"],
                item["mes"],
            )
            totais[chave] += abs(_decimal(item["total"]))
    return totais


def _mapa_lancamentos(fim, meses, empresas_ids, projetos, regime_financeiro):
    if regime_financeiro == "competencia":
        return _mapa_lancamentos_competencia(fim, meses, empresas_ids, projetos)
    return _mapa_lancamentos_caixa(fim, meses, empresas_ids, projetos)


def _valor_conta(conta, totais_lancamentos, ano, mes):
    valor = _decimal(totais_lancamentos[(conta.pk, ano, mes)])
    if conta.sinal == ContaDRE.Sinal.SUBTRACAO:
        return abs(valor) * Decimal("-1")
    return abs(valor)


def _mes_formatado(valor_atual, valor_anterior, receita_mes):
    av = _porcentagem(valor_atual, receita_mes)
    ah = _variacao_percentual(valor_atual, valor_anterior)
    return {
        "realizado": valor_atual,
        "realizado_fmt": _formatar_moeda(valor_atual),
        "av": av,
        "av_fmt": _formatar_percentual(av),
        "ah": ah,
        "ah_fmt": _formatar_percentual(ah),
        "direcao": _direcao(ah),
    }


def _linha_base(conta, nivel, meses, valores_mes, receitas_mes, expandida=False):
    total = sum((_decimal(valores_mes[item["chave"]]) for item in meses), Decimal("0"))
    meses_formatados = {}
    for item in meses:
        ano_anterior, mes_anterior = _mes_anterior(item["ano"], item["mes"])
        atual = _decimal(valores_mes[item["chave"]])
        anterior = _decimal(valores_mes.get(f"{ano_anterior}-{mes_anterior:02d}"))
        meses_formatados[item["chave"]] = _mes_formatado(
            atual,
            anterior,
            receitas_mes[item["chave"]],
        )
    return {
        "id": f"conta-{conta.pk}",
        "parent_id": f"conta-{conta.conta_pai_id}" if conta.conta_pai_id else "",
        "nome": conta.nome,
        "nivel": nivel,
        "tipo": "conta",
        "expandida": expandida,
        "tem_filhos": False,
        "total": total,
        "total_fmt": _formatar_moeda(total),
        "meses": [meses_formatados[item["chave"]] for item in meses],
    }


def _classificar_indicadores(linhas_pai):
    def contem(nome, termos):
        nome = nome.lower()
        return any(termo in nome for termo in termos)

    receita = Decimal("0")
    variaveis = Decimal("0")
    fixos = Decimal("0")
    for linha in linhas_pai:
        nome = linha["nome"]
        total = _decimal(linha["total"])
        if contem(nome, ("receita", "faturamento")):
            receita += total
        elif contem(nome, ("variavel", "dedu", "custo")):
            variaveis += total
        elif contem(nome, ("fixo", "fixa", "administrativa", "pessoal")):
            fixos += total

    margem = receita + variaveis
    ebit = margem + fixos
    margem_percentual = _porcentagem(margem, receita)
    return [
        {
            "titulo": "Receita bruta",
            "valor": _formatar_moeda(receita),
            "tom": "positive" if receita >= 0 else "negative",
        },
        {
            "titulo": "Deducoes e gastos variaveis",
            "valor": _formatar_moeda(variaveis),
            "tom": "negative" if variaveis < 0 else "neutral",
        },
        {
            "titulo": "Margem de contribuicao",
            "valor": _formatar_percentual(margem_percentual),
            "tom": "positive" if margem_percentual >= 0 else "negative",
        },
        {
            "titulo": "Gastos fixos",
            "valor": _formatar_moeda(fixos),
            "tom": "negative" if fixos < 0 else "neutral",
        },
        {
            "titulo": "EBIT",
            "valor": _formatar_moeda(ebit),
            "tom": "positive" if ebit >= 0 else "negative",
        },
    ]


def _fornecedores_caixa(conta, inicio, fim, empresas_ids, receitas_mes, meses):
    base = LancamentoContaCorrenteOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_lancamento__gte=inicio,
        data_lancamento__lte=fim,
        categoria_principal__conta_dre=conta,
    )
    fornecedores = (
        base
        .values(
            "cliente_fornecedor__razao_social",
            "cliente_fornecedor__nome_fantasia",
        )
        .annotate(total=Sum("valor_lancamento"))
        .order_by("-total")[:8]
    )
    linhas = []
    for indice, fornecedor in enumerate(fornecedores, start=1):
        nome = (
            fornecedor["cliente_fornecedor__nome_fantasia"]
            or fornecedor["cliente_fornecedor__razao_social"]
            or "Fornecedor nao informado"
        )
        valor = _decimal(fornecedor["total"])
        if conta.sinal == ContaDRE.Sinal.SUBTRACAO:
            valor = abs(valor) * Decimal("-1")
        valores_mensais = defaultdict(Decimal)
        totais_mensais = (
            base.filter(
                cliente_fornecedor__razao_social=fornecedor[
                    "cliente_fornecedor__razao_social"
                ],
                cliente_fornecedor__nome_fantasia=fornecedor[
                    "cliente_fornecedor__nome_fantasia"
                ],
            )
            .values("data_lancamento__year", "data_lancamento__month")
            .annotate(total=Sum("valor_lancamento"))
        )
        for item in totais_mensais:
            valor_mes = _decimal(item["total"])
            if conta.sinal == ContaDRE.Sinal.SUBTRACAO:
                valor_mes = abs(valor_mes) * Decimal("-1")
            valores_mensais[
                f"{item['data_lancamento__year']}-{item['data_lancamento__month']:02d}"
            ] = valor_mes
        linhas.append(
            {
                "id": f"fornecedor-{conta.pk}-{indice}",
                "parent_id": f"conta-{conta.pk}",
                "nome": nome,
                "nivel": 3,
                "tipo": "fornecedor",
                "expandida": False,
                "tem_filhos": False,
                "total": valor,
                "total_fmt": _formatar_moeda(valor),
                "meses": [
                    _mes_formatado(
                        valores_mensais[item["chave"]],
                        Decimal("0"),
                        receitas_mes[item["chave"]],
                    )
                    for item in meses
                ],
            }
        )
    return linhas


def _pessoas_competencia(
    conta,
    inicio,
    fim,
    empresas_ids,
    receitas_mes,
    meses,
    projetos,
):
    bases = [
        (
            ContaReceberOmie.objects.annotate(
                data_referencia=Coalesce("data_registro", "data_previsao", "data_emissao"),
            ).filter(
                empresa_id__in=empresas_ids,
                data_referencia__gte=inicio,
                data_referencia__lte=fim,
                categoria_principal__conta_dre=conta,
            ),
            "cliente",
            "Cliente nao informado",
        ),
        (
            ContaPagarOmie.objects.annotate(
                data_referencia=Coalesce("data_entrada", "data_previsao", "data_vencimento"),
            ).filter(
                empresa_id__in=empresas_ids,
                data_referencia__gte=inicio,
                data_referencia__lte=fim,
                categoria_principal__conta_dre=conta,
            ),
            "fornecedor",
            "Fornecedor nao informado",
        ),
    ]
    linhas = []
    indice = 1
    for base, prefixo, padrao in bases:
        if projetos:
            base = base.filter(codigo_projeto__in=projetos)
        pessoas = (
            base.values(f"{prefixo}__razao_social", f"{prefixo}__nome_fantasia")
            .annotate(total=Sum("valor_documento"))
            .order_by("-total")[:8]
        )
        for pessoa in pessoas:
            nome = (
                pessoa[f"{prefixo}__nome_fantasia"]
                or pessoa[f"{prefixo}__razao_social"]
                or padrao
            )
            valor = abs(_decimal(pessoa["total"]))
            if conta.sinal == ContaDRE.Sinal.SUBTRACAO:
                valor = valor * Decimal("-1")
            linhas.append(
                {
                    "id": f"pessoa-{conta.pk}-{indice}",
                    "parent_id": f"conta-{conta.pk}",
                    "nome": nome,
                    "nivel": 3,
                    "tipo": "fornecedor",
                    "expandida": False,
                    "tem_filhos": False,
                    "total": valor,
                    "total_fmt": _formatar_moeda(valor),
                    "meses": [
                        _mes_formatado(Decimal("0"), Decimal("0"), receitas_mes[item["chave"]])
                        for item in meses
                    ],
                }
            )
            indice += 1
    return sorted(linhas, key=lambda item: abs(item["total"]), reverse=True)[:8]


def _fornecedores_da_conta(
    conta,
    inicio,
    fim,
    empresas_ids,
    receitas_mes,
    meses,
    regime_financeiro,
    projetos=None,
):
    if regime_financeiro == "competencia":
        return _pessoas_competencia(
            conta,
            inicio,
            fim,
            empresas_ids,
            receitas_mes,
            meses,
            projetos or [],
        )
    return _fornecedores_caixa(conta, inicio, fim, empresas_ids, receitas_mes, meses)


def dre_gerencial(
    empresa,
    periodo,
    data_inicio="",
    data_fim="",
    empresas_ids=None,
    projetos_selecionados=None,
    regime_financeiro="caixa",
):
    empresas_ids = empresas_ids or [empresa.pk]
    inicio, fim = _intervalo_periodo(periodo, data_inicio, data_fim)
    meses = _meses_do_intervalo(inicio, fim)
    projetos = _normalizar_filtro_composto(projetos_selecionados or [])
    totais_lancamentos = _mapa_lancamentos(
        fim,
        meses,
        empresas_ids,
        projetos,
        regime_financeiro,
    )
    contas = list(
        ContaDRE.objects.filter(empresa_id=empresa.pk)
        .prefetch_related("categorias_omie")
        .order_by("conta_pai_id", "ordem", "nome")
    )
    filhos_por_pai = defaultdict(list)
    pais = []
    for conta in contas:
        if conta.conta_pai_id:
            filhos_por_pai[conta.conta_pai_id].append(conta)
        else:
            pais.append(conta)

    valores_por_conta = {}
    for conta in contas:
        valores_por_conta[conta.pk] = {}
        for ano, mes in _meses_consulta(meses):
            valores_por_conta[conta.pk][f"{ano}-{mes:02d}"] = _valor_conta(
                conta,
                totais_lancamentos,
                ano,
                mes,
            )

    for pai in pais:
        for ano, mes in _meses_consulta(meses):
            chave = f"{ano}-{mes:02d}"
            soma_filhos = sum(
                (
                    _decimal(valores_por_conta[filho.pk][chave])
                    for filho in filhos_por_pai[pai.pk]
                ),
                Decimal("0"),
            )
            if soma_filhos:
                valores_por_conta[pai.pk][chave] = soma_filhos

    receitas_mes = defaultdict(Decimal)
    for pai in pais:
        if "receita" in pai.nome.lower() or "faturamento" in pai.nome.lower():
            for item in meses:
                receitas_mes[item["chave"]] += _decimal(
                    valores_por_conta[pai.pk][item["chave"]]
                )

    linhas = []
    linhas_pai = []
    for pai in pais:
        linha_pai = _linha_base(
            pai,
            1,
            meses,
            valores_por_conta[pai.pk],
            receitas_mes,
            expandida=True,
        )
        linha_pai["tem_filhos"] = bool(filhos_por_pai[pai.pk])
        linhas.append(linha_pai)
        linhas_pai.append(linha_pai)
        for filho in filhos_por_pai[pai.pk]:
            linha_filho = _linha_base(
                filho,
                2,
                meses,
                valores_por_conta[filho.pk],
                receitas_mes,
            )
            linha_filho["tem_filhos"] = filho.categorias_omie.exists()
            linhas.append(linha_filho)
            linhas.extend(
                _fornecedores_da_conta(
                    filho,
                    inicio,
                    fim,
                    empresas_ids,
                    receitas_mes,
                    meses,
                    regime_financeiro,
                    projetos,
                )
            )

    if not linhas:
        linhas.append(
            {
                "id": "sem-estrutura",
                "parent_id": "",
                "nome": "Estrutura DRE ainda nao configurada",
                "nivel": 1,
                "tipo": "aviso",
                "expandida": True,
                "tem_filhos": False,
                "total": Decimal("0"),
                "total_fmt": _formatar_moeda(Decimal("0")),
                "meses": [
                    _mes_formatado(Decimal("0"), Decimal("0"), Decimal("0"))
                    for _ in meses
                ],
            }
        )

    opcoes_grafico = [
        {"valor": linha["id"], "rotulo": linha["nome"]}
        for linha in linhas
        if linha["tipo"] == "conta"
    ] or [{"valor": linhas[0]["id"], "rotulo": linhas[0]["nome"]}]

    datasets = {}
    for linha in linhas:
        datasets[linha["id"]] = {
            "nome": linha["nome"],
            "valores": [float(item["realizado"]) for item in linha["meses"]],
            "ah": [float(item["ah"]) for item in linha["meses"]],
        }

    return {
        "indicadores": _classificar_indicadores(linhas_pai),
        "meses": meses,
        "linhas": linhas,
        "opcoes_grafico": opcoes_grafico,
        "grafico_labels": [item["rotulo"] for item in meses],
        "grafico_datasets": datasets,
    }
