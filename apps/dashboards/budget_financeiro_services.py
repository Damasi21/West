"""Consumo financeiro do Budget a partir dos títulos locais de contas a pagar."""
from collections import defaultdict
from decimal import Decimal
from django.db.models import F, Sum, Subquery
from django.db.models.functions import Trim, Upper
from apps.empresas.models import ContaPagarOmie, MovimentoFinanceiroOmie, CategoriaOmie, DepartamentoOmie, ProjetoOmie
from .finance_filters import registros_com_conta_visivel_financeiro
from .titulos_financeiros_services import _decimal, _filtrar_codigos, _selecionado


# Keep the reference date explicit; shared by dashboard and previous-year cards.
DATA_REFERENCIA = "data_previsao"


def _rateio(itens, codigo_chave, percentual_chave, valor_chave, total):
    parcelas = defaultdict(Decimal)
    for item in itens if isinstance(itens, list) else []:
        if not isinstance(item, dict):
            continue
        codigo = str(item.get(codigo_chave) or "").strip()
        if not codigo:
            continue
        if item.get(percentual_chave) not in (None, ""):
            fracao = max(Decimal("0"), _decimal(item[percentual_chave])) / 100
        elif total > 0 and item.get(valor_chave) not in (None, ""):
            fracao = max(Decimal("0"), _decimal(item[valor_chave])) / total
        else:
            continue
        parcelas[codigo] += fracao
    soma = sum(parcelas.values(), Decimal("0"))
    if soma > 1:
        parcelas = {c: f / soma for c, f in parcelas.items()}
    return parcelas


def gastos_financeiros(inicio, fim, empresas_ids, dimensao, projetos=None, departamentos=None, categorias=None):
    queryset = ContaPagarOmie.objects.filter(empresa_id__in=empresas_ids, empresa__ativa=True, ativo_omie=True)
    queryset = queryset.annotate(data_budget=F(DATA_REFERENCIA), status_budget=Upper(Trim("status_titulo"))).filter(
        data_budget__range=(inicio, fim), valor_documento__gt=0,
    ).exclude(status_budget__in=["CANCELADO", "EXCLUIDO", "ESTORNADO"])
    queryset = registros_com_conta_visivel_financeiro(queryset, "id_conta_corrente")
    queryset = _filtrar_codigos(queryset, "codigo_projeto", projetos)
    departamentos, categorias = set(departamentos or []), set(categorias or [])
    nomes = {}
    modelo, codigo, descricao = {
        "projeto": (ProjetoOmie, "codigo", "nome"),
        "departamento": (DepartamentoOmie, "codigo", "descricao"),
        "categoria": (CategoriaOmie, "codigo", "descricao"),
    }[dimensao]
    for row in modelo.objects.filter(empresa_id__in=empresas_ids).values("empresa_id", codigo, descricao):
        nomes[(row["empresa_id"], str(row[codigo]))] = row[descricao]
    pagamentos = MovimentoFinanceiroOmie.objects.filter(
        empresa_id__in=empresas_ids, codigo_titulo__in=Subquery(queryset.values("codigo_lancamento_omie")),
        ativo_omie=True, natureza="P", valor_pago__gt=0, data_pagamento__isnull=False,
    ).annotate(status_budget=Upper(Trim("status"))).exclude(status_budget__in=["CANCELADO", "EXCLUIDO", "ESTORNADO"])
    pagamentos = registros_com_conta_visivel_financeiro(pagamentos, "codigo_conta_corrente")
    pagos = {(p["empresa_id"],p["codigo_titulo"]): p["total"] for p in pagamentos.values("empresa_id","codigo_titulo").annotate(total=Sum("valor_pago"))}
    gastos = defaultdict(Decimal)
    for conta in queryset.iterator(chunk_size=1000):
        pago = _decimal(pagos.get((conta.empresa_id,conta.codigo_lancamento_omie)))
        if pago <= 0:
            continue
        total = _decimal(conta.valor_documento)
        cats = _rateio(conta.categorias, "codigo_categoria", "percentual", "valor", total)
        if not cats and conta.codigo_categoria:
            cats = {str(conta.codigo_categoria): Decimal("1")}
        deps = _rateio(conta.distribuicao, "cCodDep", "nPerDep", "nValDep", total)
        cats = {c:f for c,f in cats.items() if not categorias or _selecionado(conta.empresa_id,c,categorias)}
        deps = {c:f for c,f in deps.items() if not departamentos or _selecionado(conta.empresa_id,c,departamentos)}
        fracao_cat = sum(cats.values(), Decimal("0")) if categorias else Decimal("1")
        fracao_dep = sum(deps.values(), Decimal("0")) if departamentos else Decimal("1")
        if dimensao == "projeto":
            if conta.codigo_projeto is not None:
                gastos[(conta.empresa_id, str(conta.codigo_projeto))] += pago * fracao_cat * fracao_dep
        elif dimensao == "categoria":
            for c,f in cats.items():
                gastos[(conta.empresa_id,c)] += pago * f * fracao_dep
        else:
            for c,f in deps.items():
                gastos[(conta.empresa_id,c)] += pago * f * fracao_cat
    return gastos, nomes
