from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .auditoria import registrar_acao
from .models import AcaoUsuarioLog
from .white_label_forms import AmbienteWhiteLabelForm, EmpresaWhiteLabelForm
from .white_label_services import ambientes_administraveis


@login_required
@require_http_methods(["GET"])
def lista(request):
    ambientes = ambientes_administraveis(request.user)
    if not request.user.is_superuser and not ambientes.exists():
        raise PermissionDenied
    busca = (request.GET.get("q") or "").strip()[:120]
    if busca:
        encontrados = ambientes.filter(Q(nome__icontains=busca) | Q(empresas__cnpj__icontains=busca) | Q(empresas__nome_fantasia__icontains=busca)).values("pk")
        ambientes = ambientes.filter(pk__in=encontrados)
    ambientes = ambientes.annotate(total_cnpjs=Count("empresas", distinct=True), total_administradores=Count("administradores", distinct=True))
    return render(request, "empresas/white_label_lista.html", {"ambientes": ambientes, "busca": busca})


@login_required
@require_http_methods(["GET", "POST"])
def cadastro(request, slug=None):
    if slug is None and not request.user.is_superuser:
        raise PermissionDenied
    ambiente = get_object_or_404(ambientes_administraveis(request.user), slug=slug) if slug else None
    form = AmbienteWhiteLabelForm(request.POST or None, instance=ambiente, operador=request.user)
    if request.method == "POST":
        try:
            with transaction.atomic():
                if ambiente:
                    ambiente = get_object_or_404(ambientes_administraveis(request.user).select_for_update(), pk=ambiente.pk)
                anterior = None if not ambiente else {
                        "nome": ambiente.nome, "empresas": list(ambiente.empresas.values_list("pk", flat=True)),
                        "administradores": list(ambiente.administradores.values_list("pk", flat=True)),
                    }
                form = AmbienteWhiteLabelForm(request.POST, instance=ambiente, operador=request.user)
                if form.is_valid():
                    salvo = form.save()
                    registrar_acao(usuario=request.user, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
                        descricao=f"Salvou ambiente White Label: {salvo.nome}", request=request,
                        dados={"ambiente_id": salvo.pk, "anterior": anterior,
                            "empresas": list(salvo.empresas.values_list("pk", flat=True)),
                            "administradores": list(salvo.administradores.values_list("pk", flat=True))})
                    messages.success(request, "Ambiente White Label salvo.")
                    return redirect("empresas:white_label_editar", slug=salvo.slug)
        except IntegrityError:
            form.add_error(None, "Não foi possível salvar. Confira o identificador e atualize a página.")
    empresas = ambiente.empresas.order_by("nome_fantasia", "pk") if ambiente else []
    return render(request, "empresas/white_label_form.html", {"form": form, "ambiente": ambiente, "empresas_vinculadas": empresas})


@login_required
@require_http_methods(["GET", "POST"])
def cadastrar_cnpj(request, slug):
    ambiente = get_object_or_404(ambientes_administraveis(request.user), slug=slug)
    if not ambiente.ativa:
        raise PermissionDenied
    form = EmpresaWhiteLabelForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                ambiente = get_object_or_404(ambientes_administraveis(request.user).select_for_update(), pk=ambiente.pk, ativa=True)
                empresa = form.save()
                ambiente.empresas.add(empresa)
                registrar_acao(usuario=request.user, empresa=empresa, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
                    descricao=f"Cadastrou CNPJ no White Label: {ambiente.nome}", request=request,
                    dados={"ambiente_id": ambiente.pk, "empresa_id": empresa.pk})
            messages.success(request, "CNPJ cadastrado e vinculado ao ambiente.")
            return redirect("empresas:white_label_editar", slug=ambiente.slug)
        except IntegrityError:
            form.add_error("cnpj", "Este CNPJ já foi cadastrado. Atualize a página e vincule a empresa existente.")
    return render(request, "empresas/white_label_cnpj.html", {"form": form, "ambiente": ambiente})
