from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.empresas.models import ContaPagarOmie
from apps.empresas.services import obter_empresa_permitida, usuario_pode_acessar_dashboard
from .finance_filters import registros_com_conta_visivel_financeiro
from .pagamento_nfe_services import notas_das_contas


@login_required
@require_GET
def nota_pagamento(request, empresa_slug, conta_id):
    empresa = obter_empresa_permitida(request.user, empresa_slug)
    if not settings.ENABLE_PAYMENT_APPROVAL_DASHBOARD or not usuario_pode_acessar_dashboard(
        request.user, empresa, "financeiro", "aprovacao-de-pagamentos",
    ):
        raise Http404("Nota nao encontrada.")
    contas = registros_com_conta_visivel_financeiro(
        ContaPagarOmie.objects.filter(empresa=empresa, ativo_omie=True), "id_conta_corrente",
    )
    conta = get_object_or_404(contas, pk=conta_id)
    nota = notas_das_contas([conta]).get(conta.pk)
    if nota is None:
        raise Http404("Nota nao encontrada ou vinculo indisponivel.")
    parcelas = nota.parcelas.get("parcelasLista", []) if isinstance(nota.parcelas, dict) else []
    cabec = nota.cabec if isinstance(nota.cabec, dict) else {}
    response = render(request, "dashboards/nota_pagamento.html", {
        "empresa": empresa, "nota": nota, "conta": conta,
        "fornecedor_nome": cabec.get("cRazaoSocial") or cabec.get("cNome") or "Nao informado",
        "itens": nota.itens.filter(ativo_omie=True).order_by("sequencia"),
        "parcelas": [p for p in parcelas if isinstance(p, dict)] if isinstance(parcelas, list) else [],
    })
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
