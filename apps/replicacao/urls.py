from django.urls import path
from . import views

app_name = "replicacao"
urlpatterns = [
    path("", views.lista, name="lista"),
    path("nova/", views.novo, name="novo"),
    path("<int:plano_id>/", views.detalhe, name="detalhe"),
    path("<int:plano_id>/comparar/", views.comparar, name="comparar"),
    path("<int:plano_id>/situacao/", views.alternar, name="alternar"),
    path("<int:plano_id>/comparacoes/<int:comparacao_id>/enviar/", views.enviar, name="enviar"),
    path("<int:plano_id>/comparacoes/<int:comparacao_id>/atualizar/", views.atualizar_situacao, name="atualizar_situacao"),
    path("<int:plano_id>/itens/<int:item_id>/resolver/", views.resolver, name="resolver"),
    path("<int:plano_id>/itens/<int:item_id>/verificar/", views.verificar, name="verificar"),
]
