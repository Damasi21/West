"""Filtros compartilhados dos dashboards financeiros."""

from django.db.models import Exists, OuterRef

from apps.empresas.categorias import filtro_categorias_transferencia
from apps.empresas.models import CategoriaOmie, ContaCorrenteOmie


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
