from django.urls import path
from . import views

app_name = "auditor"
urlpatterns = [
    path("", views.visao_geral, name="visao_geral"),
    path("visao-geral/", views.visao_geral, name="visao_geral_dashboard"),
    path("alertas/", views.alertas, name="alertas"),
    path("alertas/<int:caso_id>/", views.detalhe, name="detalhe"),
    path("regras/", views.regras, name="regras"),
    path("executar/", views.executar, name="executar"),
    path("execucoes/<int:execucao_id>/encerrar-espera/", views.encerrar_espera, name="encerrar_espera"),
]
