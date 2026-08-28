import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView, LogoutView
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import (
    CadastroForm,
    LoginForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
)
from .models import PasswordResetCode


class EntrarView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        from apps.empresas.auditoria import registrar_acao
        from apps.empresas.models import AcaoUsuarioLog

        registrar_acao(
            usuario=form.get_user(),
            tipo=AcaoUsuarioLog.Tipo.LOGIN,
            descricao="Login realizado",
            request=self.request,
        )
        return response

    def form_invalid(self, form):
        response = super().form_invalid(form)
        from apps.empresas.auditoria import registrar_acao
        from apps.empresas.models import AcaoUsuarioLog

        registrar_acao(
            tipo=AcaoUsuarioLog.Tipo.ERRO_LOGIN,
            descricao="Tentativa de login sem sucesso",
            request=self.request,
            dados={"username": self.request.POST.get("username", "")[:150]},
        )
        return response


class SairView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            from apps.empresas.auditoria import registrar_acao
            from apps.empresas.models import AcaoUsuarioLog

            registrar_acao(
                usuario=request.user,
                tipo=AcaoUsuarioLog.Tipo.LOGOUT,
                descricao="Logout realizado",
                request=request,
            )
        return super().dispatch(request, *args, **kwargs)


def cadastrar(request):
    if request.user.is_authenticated:
        return redirect("empresas:lista")

    form = CadastroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        login(request, usuario)
        messages.success(
            request,
            "Conta criada com sucesso. Solicite ao administrador o acesso à sua empresa.",
        )
        return redirect("empresas:lista")

    return render(request, "accounts/cadastro.html", {"form": form})


def solicitar_redefinicao_senha(request):
    if request.user.is_authenticated:
        return redirect("empresas:lista")

    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        usuario = (
            get_user_model()
            .objects.filter(email__iexact=email, is_active=True)
            .first()
        )
        if usuario:
            codigo = f"{secrets.randbelow(1000000):06d}"
            PasswordResetCode.objects.create(
                user=usuario,
                code_hash=make_password(codigo),
            )
            send_mail(
                "Codigo para redefinir sua senha",
                (
                    "Use este codigo para redefinir sua senha no WEST:\n\n"
                    f"{codigo}\n\n"
                    "O codigo expira em 15 minutos. Se voce nao solicitou esta troca, ignore este e-mail."
                ),
                getattr(settings, "DEFAULT_FROM_EMAIL", None),
                [usuario.email],
                fail_silently=False,
            )
        request.session["password_reset_email"] = email
        messages.success(
            request,
            "Se este e-mail estiver cadastrado, enviamos um codigo para redefinir a senha.",
        )
        return redirect("accounts:password_reset_confirm")

    return render(request, "accounts/password_reset_request.html", {"form": form})


def confirmar_redefinicao_senha(request):
    if request.user.is_authenticated:
        return redirect("empresas:lista")

    initial = {"email": request.session.get("password_reset_email", "")}
    usuario = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        usuario = (
            get_user_model()
            .objects.filter(email__iexact=email, is_active=True)
            .first()
        )
    form = PasswordResetConfirmForm(request.POST or None, initial=initial, user=usuario)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        codigo = form.cleaned_data["code"]
        usuario = (
            get_user_model()
            .objects.filter(email__iexact=email, is_active=True)
            .first()
        )
        reset_code = None
        if usuario:
            reset_codes = PasswordResetCode.objects.filter(
                user=usuario,
                used_at__isnull=True,
            )
            for candidate in reset_codes:
                if candidate.is_valid() and check_password(codigo, candidate.code_hash):
                    reset_code = candidate
                    break
        if not reset_code:
            form.add_error("code", "Codigo invalido ou expirado.")
        else:
            usuario.set_password(form.cleaned_data["password1"])
            usuario.save(update_fields=["password"])
            reset_code.used_at = timezone.now()
            reset_code.save(update_fields=["used_at"])
            PasswordResetCode.objects.filter(user=usuario, used_at__isnull=True).exclude(
                pk=reset_code.pk
            ).update(used_at=timezone.now())
            request.session.pop("password_reset_email", None)
            messages.success(request, "Senha redefinida com sucesso. Entre com seu e-mail.")
            return redirect("accounts:login")

    return render(request, "accounts/password_reset_confirm.html", {"form": form})
