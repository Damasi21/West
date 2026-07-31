from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CadastroTests(TestCase):
    def test_tela_de_login_exibe_link_de_cadastro(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertContains(response, reverse("accounts:cadastro"))
        self.assertContains(response, "Criar uma conta")
        self.assertContains(response, "Insight Wise")
        self.assertContains(response, "/media/insight_wise_login.jpeg")

    def test_usuario_pode_criar_conta_e_fica_autenticado(self):
        response = self.client.post(
            reverse("accounts:cadastro"),
            {
                "first_name": "Maria",
                "username": "maria",
                "email": "maria@empresa.com.br",
                "password1": "UmaSenhaSegura2026!",
                "password2": "UmaSenhaSegura2026!",
            },
        )

        self.assertRedirects(response, reverse("empresas:lista"))
        usuario = get_user_model().objects.get(username="maria")
        self.assertEqual(usuario.first_name, "Maria")
        self.assertEqual(usuario.email, "maria@empresa.com.br")
        self.assertEqual(int(self.client.session["_auth_user_id"]), usuario.pk)

    def test_email_nao_pode_ser_reutilizado(self):
        get_user_model().objects.create_user(
            username="existente",
            email="cliente@empresa.com.br",
            password="UmaSenhaSegura2026!",
        )

        response = self.client.post(
            reverse("accounts:cadastro"),
            {
                "first_name": "Outro",
                "username": "outro",
                "email": "CLIENTE@empresa.com.br",
                "password1": "OutraSenhaSegura2026!",
                "password2": "OutraSenhaSegura2026!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Já existe uma conta com este e-mail.")
        self.assertFalse(get_user_model().objects.filter(username="outro").exists())
