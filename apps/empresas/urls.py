from django.urls import path

from . import views
from . import white_label_views


app_name = "empresas"

urlpatterns = [
    path("configuracoes/white-label/", white_label_views.lista, name="white_label"),
    path("configuracoes/white-label/novo/", white_label_views.cadastro, name="white_label_novo"),
    path("configuracoes/white-label/<slug:slug>/", white_label_views.cadastro, name="white_label_editar"),
    path("configuracoes/white-label/<slug:slug>/identidade/", white_label_views.identidade, name="white_label_identidade"),
    path("configuracoes/white-label/<slug:slug>/previa-login/", white_label_views.previa_login, name="white_label_previa_login"),
    path("configuracoes/white-label/<slug:slug>/cnpjs/novo/", white_label_views.cadastrar_cnpj, name="white_label_cnpj_novo"),
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
