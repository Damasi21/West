from django.urls import path

from .views import (
    EntrarView,
    SairView,
    cadastrar,
    confirmar_email_cadastro,
    confirmar_redefinicao_senha,
    solicitar_redefinicao_senha,
)


app_name = "accounts"

urlpatterns = [
    path("marca/<slug:marca_slug>/entrar/", EntrarView.as_view(), name="login_marca"),
    path("entrar/", EntrarView.as_view(), name="login"),
    path("cadastro/", cadastrar, name="cadastro"),
    path("confirmar-cadastro/", confirmar_email_cadastro, name="confirmar_cadastro"),
    path("recuperar-senha/", solicitar_redefinicao_senha, name="password_reset"),
    path(
        "redefinir-senha/",
        confirmar_redefinicao_senha,
        name="password_reset_confirm",
    ),
    path("sair/", SairView.as_view(), name="logout"),
]
