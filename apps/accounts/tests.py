import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CadastroTests(TestCase):
    def test_tela_de_login_exibe_link_de_cadastro_e_recuperacao(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertContains(response, reverse("accounts:cadastro"))
        self.assertContains(response, reverse("accounts:password_reset"))
        self.assertContains(response, "Criar uma conta")
        self.assertContains(response, "Insight Wise")
        self.assertContains(response, "/media/insight_wise_login.jpeg")

    def test_usuario_pode_criar_conta_sem_informar_username(self):
        response = self.client.post(
            reverse("accounts:cadastro"),
            {
                "first_name": "Maria",
                "email": "maria@empresa.com.br",
                "password1": "UmaSenhaSegura2026!",
                "password2": "UmaSenhaSegura2026!",
            },
        )

        self.assertRedirects(response, reverse("empresas:lista"))
        usuario = get_user_model().objects.get(email="maria@empresa.com.br")
        self.assertEqual(usuario.username, "maria@empresa.com.br")
        self.assertEqual(usuario.first_name, "Maria")
        self.assertEqual(int(self.client.session["_auth_user_id"]), usuario.pk)

    def test_login_usa_email_cadastrado(self):
        get_user_model().objects.create_user(
            username="codigo-antigo",
            email="cliente@empresa.com.br",
            password="UmaSenhaSegura2026!",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "cliente@empresa.com.br",
                "password": "UmaSenhaSegura2026!",
            },
        )

        self.assertRedirects(response, reverse("empresas:lista"))

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
                "email": "CLIENTE@empresa.com.br",
                "password1": "OutraSenhaSegura2026!",
                "password2": "OutraSenhaSegura2026!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ja existe uma conta com este e-mail.")
        self.assertFalse(get_user_model().objects.filter(username="outro").exists())

    def test_recuperacao_de_senha_envia_codigo_e_redefine_senha(self):
        usuario = get_user_model().objects.create_user(
            username="cliente",
            email="cliente@empresa.com.br",
            password="SenhaAntiga2026!",
        )

        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "cliente@empresa.com.br"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_confirm"))
        self.assertEqual(len(mail.outbox), 1)
        codigo = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)

        response = self.client.post(
            reverse("accounts:password_reset_confirm"),
            {
                "email": "cliente@empresa.com.br",
                "code": codigo,
                "password1": "SenhaNova2026!",
                "password2": "SenhaNova2026!",
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password("SenhaNova2026!"))
