from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render

from .forms import CadastroForm, LoginForm


class EntrarView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class SairView(LogoutView):
    pass


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
