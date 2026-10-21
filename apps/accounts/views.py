import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView, LogoutView
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import (
    CadastroForm,
    ConfirmarCadastroForm,
    LoginForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
)
from .models import PasswordResetCode, ConfirmacaoCadastro
from .registration import confirmar_cadastro, enviar_codigo_cadastro, vincular_email_verificado


class EntrarView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        usuario = form.get_user()
        vincular_email_verificado(usuario)
        from apps.empresas.models import PreCadastroUsuario
        if usuario.email and PreCadastroUsuario.objects.filter(email__iexact=usuario.email.strip(), ativo=True, utilizado_em__isnull=True, empresa__ativa=True).exists():
            try:
                registro = enviar_codigo_cadastro(usuario.email, usuario.first_name or usuario.username)
            except ValidationError as erro:
                messages.warning(self.request, " ".join(erro.messages))
                registro = ConfirmacaoCadastro.objects.filter(email=usuario.email.strip().lower(), expira_em__gt=timezone.now(), consumida_em__isnull=True, tentativas__lt=5).first()
            if registro:
                self.request.session["cadastro_confirmacao_id"] = registro.pk
                response = redirect("accounts:confirmar_cadastro")
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


@require_http_methods(["GET", "POST"])
def cadastrar(request):
    form = CadastroForm(request.POST or None)
    if request.user.is_authenticated:
        if not request.user.email:
            messages.error(request, "Solicite ao administrador a regularizacao do e-mail da sua conta.")
            return redirect("empresas:lista")
        form.fields["email"].disabled = True
        form.initial.update(email=request.user.email, first_name=request.user.first_name)
    if request.method == "POST" and form.is_valid():
        try:
            registro = enviar_codigo_cadastro(form.cleaned_data["email"], form.cleaned_data["first_name"])
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            request.session["cadastro_confirmacao_id"] = registro.pk
            return redirect("accounts:confirmar_cadastro")

    return render(request, "accounts/cadastro.html", {"form": form})


@require_http_methods(["GET", "POST"])
def confirmar_email_cadastro(request):
    registro = ConfirmacaoCadastro.objects.filter(pk=request.session.get("cadastro_confirmacao_id")).first()
    if not registro:
        return redirect("accounts:cadastro")
    existentes = list(get_user_model().objects.filter(email__iexact=registro.email)[:2])
    precisa_login = bool(existentes and (not request.user.is_authenticated or len(existentes) != 1 or request.user.pk != existentes[0].pk))
    form = ConfirmarCadastroForm(request.POST or None, registro=registro, existente=bool(existentes))
    if request.method == "POST" and not precisa_login and form.is_valid():
        usuario, erro = confirmar_cadastro(registro.pk, form.cleaned_data["code"], form.cleaned_data.get("password1"), request.user)
        if erro:
            form.add_error("code", erro)
        else:
            request.session.pop("cadastro_confirmacao_id", None)
            login(request, usuario)
            messages.success(request, "E-mail confirmado. Os acessos autorizados para voce foram vinculados.")
            return redirect("empresas:lista")
    response = render(request, "accounts/cadastro.html", {
        "form": form, "etapa_confirmacao": True, "email_destino": registro.email,
        "precisa_login": precisa_login, "conta_existente": bool(existentes),
        "login_confirmacao": reverse("accounts:login") + "?next=" + reverse("accounts:confirmar_cadastro"),
    })
    response["Cache-Control"] = "no-store"
    return response


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
