from django.urls import path

from apps.compras import views as compras_views
from apps.empresas import views as empresas_views

from . import views


app_name = "dashboards"

urlpatterns = [
    path("", views.home, name="home"),
    path("parametros/", empresas_views.parametros, name="parametros"),
    path(
        "parametros/dre-categorias/",
        empresas_views.dre_categorias,
        name="dre_categorias",
    ),
    path(
        "parametros/categorias/",
        empresas_views.categorias,
        name="categorias",
    ),
    path(
        "parametros/metas/",
        empresas_views.metas,
        name="metas",
    ),
    path(
        "parametros/usuarios/",
        empresas_views.usuarios,
        name="usuarios",
    ),
    path(
        "parametros/sincronizacao/",
        empresas_views.sincronizacao_omie,
        name="sincronizacao_omie",
    ),
    path(
        "parametros/budget/",
        compras_views.parametros_budget,
        name="budget",
    ),
    path(
        "parametros/dre-categorias/planilha/exportar/",
        empresas_views.exportar_planilha_dre,
        name="exportar_planilha_dre",
    ),
    path(
        "parametros/dre-categorias/planilha/importar/",
        empresas_views.importar_planilha_dre,
        name="importar_planilha_dre",
    ),
    path(
        "parametros/categorias/planilha/exportar/",
        empresas_views.exportar_planilha_categorias,
        name="exportar_planilha_categorias",
    ),
    path(
        "parametros/categorias/planilha/importar/",
        empresas_views.importar_planilha_categorias,
        name="importar_planilha_categorias",
    ),
    path(
        "parametros/dre-categorias/reordenar/",
        empresas_views.reordenar_contas_dre,
        name="reordenar_contas_dre",
    ),
    path(
        "parametros/dre-categorias/<int:conta_id>/excluir/",
        empresas_views.excluir_conta_dre,
        name="excluir_conta_dre",
    ),
    path(
        "parametros/omie/sincronizar-clientes/",
        empresas_views.sincronizar_clientes_omie,
        name="sincronizar_clientes_omie",
    ),
    path(
        "parametros/omie/sincronizacoes/<int:sincronizacao_id>/",
        empresas_views.status_sincronizacao_omie,
        name="status_sincronizacao_omie",
    ),
    path("<slug:area_slug>/", views.area, name="area"),
    path(
        "<slug:area_slug>/<slug:dashboard_slug>/",
        views.dashboard,
        name="dashboard",
    ),
]
