"""Filtros compartilhados dos dashboards financeiros."""

from django.db.models import Exists, OuterRef, Q

from apps.empresas.models import CategoriaOmie, ContaCorrenteOmie


CATEGORIAS_TRANSFERENCIA_OMIE = (
    "Entrada de Transferencia",
    "Entrada de Transferência",
    "Saida de Transferencia",
    "Saída de Transferência",
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
        codigo_omie=OuterRef(codigo_field),
        nao_fluxo=True,
        nao_resumo=True,
    )
    categoria_transferencia = CategoriaOmie.objects.filter(
        Q(transferencia=True) | Q(descricao__in=CATEGORIAS_TRANSFERENCIA_OMIE),
        empresa_id=OuterRef("empresa_id"),
        codigo=OuterRef(codigo_categoria_field),
    )
    return (
        queryset.exclude(conta_corrente__nao_fluxo=True, conta_corrente__nao_resumo=True)
        .exclude(
            Q(categoria_principal__transferencia=True)
            | Q(categoria_principal__descricao__in=CATEGORIAS_TRANSFERENCIA_OMIE)
        )
        .annotate(_conta_corrente_omie_omitida=Exists(conta_omitida))
        .annotate(_categoria_omie_transferencia=Exists(categoria_transferencia))
        .exclude(_conta_corrente_omie_omitida=True)
        .exclude(_categoria_omie_transferencia=True)
    )
