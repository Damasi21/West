from django.urls import path

from . import views


app_name = "empresas"

urlpatterns = [
    path("trial/", views.trial_cadastro, name="trial"),
    path(
        "trial/<slug:empresa_slug>/expirado/",
        views.trial_expirado,
        name="trial_expirado",
    ),
    path(
        "configuracoes/empresas/",
        views.configuracoes_empresas,
        name="configuracoes",
    ),
    path(
        "configuracoes/empresas/nova/",
        views.cadastrar_empresa,
        name="cadastrar",
    ),
    path(
        "configuracoes/empresas/<int:empresa_id>/editar/",
        views.editar_empresa,
        name="editar",
    ),
    path("", views.lista_empresas, name="lista"),
]
