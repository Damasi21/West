"""Filtros compartilhados dos dashboards financeiros."""

from django.db.models import Exists, OuterRef, Q

from apps.empresas.categorias import filtro_categorias_transferencia
from apps.empresas.models import CategoriaOmie, ContaCorrenteOmie

CONTAS_CORRENTES_FORA_DRE = (
    "Adiantamento ao Fornecedor",
    " Adiantamento ao Fornecedor",
    "Adiantamento ao Fornecedor ",
    " Adiantamento ao Fornecedor ",
    "Adiantamento de Cliente",
    " Adiantamento de Cliente",
    "Adiantamento de Cliente ",
    " Adiantamento de Cliente ",
)


def contas_correntes_visiveis_financeiro(queryset):
    return queryset.exclude(nao_fluxo=True, nao_resumo=True)


def registros_com_conta_visivel_financeiro(
    queryset,
    codigo_field,
    codigo_categoria_field="codigo_categoria",
):
    conta_omitida = ContaCorrenteOmie.objects.filter(
        empresa_id=OuterRef("empresa_id"),
        ativo_omie=True,
        codigo_omie=OuterRef(codigo_field),
        nao_fluxo=True,
        nao_resumo=True,
    )
    categoria_transferencia = CategoriaOmie.objects.filter(
        filtro_categorias_transferencia(),
        empresa_id=OuterRef("empresa_id"),
        ativo_omie=True,
        codigo=OuterRef(codigo_categoria_field),
    )
    return (
        queryset.exclude(conta_corrente__nao_fluxo=True, conta_corrente__nao_resumo=True)
        .exclude(filtro_categorias_transferencia("categoria_principal__"))
        .annotate(_conta_corrente_omie_omitida=Exists(conta_omitida))
        .annotate(_categoria_omie_transferencia=Exists(categoria_transferencia))
        .exclude(_conta_corrente_omie_omitida=True)
        .exclude(_categoria_omie_transferencia=True)
    )


def filtro_contas_correntes_fora_dre(prefixo=""):
    filtro = Q()
    for descricao in CONTAS_CORRENTES_FORA_DRE:
        filtro |= Q(**{f"{prefixo}descricao__iexact": descricao})
    return filtro


def registros_com_conta_visivel_dre(
    queryset,
    codigo_field,
    codigo_categoria_field="codigo_categoria",
):
    conta_adiantamento = ContaCorrenteOmie.objects.filter(
        filtro_contas_correntes_fora_dre(),
        empresa_id=OuterRef("empresa_id"),
        ativo_omie=True,
        codigo_omie=OuterRef(codigo_field),
    )
    return (
        registros_com_conta_visivel_financeiro(
            queryset,
            codigo_field,
            codigo_categoria_field,
        )
        .exclude(filtro_contas_correntes_fora_dre("conta_corrente__"))
        .annotate(_conta_corrente_omie_fora_dre=Exists(conta_adiantamento))
        .exclude(_conta_corrente_omie_fora_dre=True)
    )
