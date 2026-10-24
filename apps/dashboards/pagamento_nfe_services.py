from collections import defaultdict

from django.urls import reverse

from apps.empresas.models import RecebimentoNfeTituloOmie


def notas_das_contas(contas):
    if not contas:
        return {}
    candidatos = defaultdict(list)
    vinculos = RecebimentoNfeTituloOmie.objects.filter(
        recebimento__empresa_id__in={conta.empresa_id for conta in contas},
        codigo_lancamento_omie__in={conta.codigo_lancamento_omie for conta in contas},
        recebimento__ativo_omie=True,
    ).select_related("recebimento")
    for vinculo in vinculos:
        nota = vinculo.recebimento
        candidatos[(nota.empresa_id, vinculo.codigo_lancamento_omie)].append(nota)
    notas = {}
    for conta in contas:
        encontrados = candidatos[(conta.empresa_id, conta.codigo_lancamento_omie)]
        # Ambiguous titles must never open an arbitrary invoice.
        if len(encontrados) != 1:
            continue
        nota = encontrados[0]
        if nota.codigo_fornecedor and conta.codigo_cliente_fornecedor and nota.codigo_fornecedor != conta.codigo_cliente_fornecedor:
            continue
        notas[conta.pk] = nota
    return notas


def dados_link_nota(conta, nota):
    return {
        "numero_nf": (nota.numero_nfe if nota else "") or conta.numero_documento_fiscal or "-",
        "url_nf": reverse("dashboards:nota_pagamento", kwargs={
            "empresa_slug": conta.empresa.slug, "conta_id": conta.pk,
        }) if nota else "",
    }
