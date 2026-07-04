from django.urls import path

from .views import EntrarView, SairView, cadastrar


app_name = "accounts"

urlpatterns = [
    path("entrar/", EntrarView.as_view(), name="login"),
    path("cadastro/", cadastrar, name="cadastro"),
    path("sair/", SairView.as_view(), name="logout"),
]
