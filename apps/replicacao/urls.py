from django.urls import path
from . import views

app_name = "replicacao"
urlpatterns = [
    path("<int:plano_id>/padronizar/", views.padronizar, name="padronizar"),
    path("<int:plano_id>/cadastros/<int:cadastro_id>/confirmar-padronizacao/", views.confirmar_padronizacao, name="confirmar_padronizacao"),
    path("", views.lista, name="lista"),
    path("nova/", views.novo, name="novo"),
    path("<int:plano_id>/", views.detalhe, name="detalhe"),
    path("<int:plano_id>/excluir/", views.excluir, name="excluir"),
    path("<int:plano_id>/categorias/nova/", views.cadastrar, name="cadastrar"),
    path("<int:plano_id>/categorias/<int:categoria_id>/situacao/", views.situacao_categoria, name="situacao_categoria"),
    path("<int:plano_id>/cadastros/<int:cadastro_id>/confirmar-situacao/", views.confirmar_situacao, name="confirmar_situacao"),
    path("<int:plano_id>/categorias/atualizar/", views.atualizar_arvore, name="atualizar_arvore"),
    path("<int:plano_id>/cadastros/<int:cadastro_id>/progresso/", views.progresso_cadastro, name="progresso_cadastro"),
    path("<int:plano_id>/cadastros/<int:cadastro_id>/resolver/", views.resolver_cadastro, name="resolver_cadastro"),
    path("<int:plano_id>/cadastros/<int:cadastro_id>/retomar/", views.retomar_cadastro, name="retomar_cadastro"),
    path("<int:plano_id>/cadastros/empresas/<int:empresa_id>/verificar/", views.verificar_cadastro, name="verificar_cadastro"),
    path("<int:plano_id>/comparar/", views.comparar, name="comparar"),
    path("<int:plano_id>/situacao/", views.alternar, name="alternar"),
    path("<int:plano_id>/comparacoes/<int:comparacao_id>/enviar/", views.enviar, name="enviar"),
    path("<int:plano_id>/comparacoes/<int:comparacao_id>/atualizar/", views.atualizar_situacao, name="atualizar_situacao"),
    path("<int:plano_id>/itens/<int:item_id>/resolver/", views.resolver, name="resolver"),
    path("<int:plano_id>/itens/<int:item_id>/verificar/", views.verificar, name="verificar"),
]
