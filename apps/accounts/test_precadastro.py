import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa, EmpresaUsuario, PreCadastroUsuario
from .models import ConfirmacaoCadastro
from .registration import confirmar_cadastro, enviar_codigo_cadastro, vincular_email_verificado


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PreCadastroTests(TestCase):
    senha = "SenhaForteConfirmada2026!"

    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Acesso Novo", cnpj="00.000.000/0001-61")
        self.outra = Empresa.objects.create(nome="Outra Empresa Acesso", cnpj="00.000.000/0001-62")
        self.admin = get_user_model().objects.create_user(username="gestor-acesso", password=self.senha)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.admin, papel="admin")
        self.url = reverse("dashboards:usuarios", args=[self.empresa.slug])

    def convite(self, email="pessoa@empresa.com.br", **kwargs):
        return PreCadastroUsuario.objects.create(empresa=self.empresa, email=email, nome="Pessoa", **kwargs)

    def iniciar(self, email="pessoa@empresa.com.br"):
        response = self.client.post(reverse("accounts:cadastro"), {"email": email, "first_name": "Pessoa"})
        self.assertEqual(response.status_code, 302)
        return re.search(r"\b([0-9]{8})\b", mail.outbox[-1].body).group(1)

    def confirmar(self, codigo):
        return self.client.post(reverse("accounts:confirmar_cadastro"), {"code": codigo, "password1": self.senha, "password2": self.senha})

    def test_admin_informa_apenas_nome_email_sem_criar_usuario_ou_senha(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {"email": "PESSOA@empresa.com.br ", "first_name": "Pessoa"})
        self.assertRedirects(r, self.url)
        convite = PreCadastroUsuario.objects.get()
        self.assertEqual(convite.email, "pessoa@empresa.com.br")
        self.assertEqual(convite.papel, "viewer")
        self.assertTrue(convite.ativo)
        self.assertFalse(get_user_model().objects.filter(email=convite.email).exists())
        self.assertContains(self.client.get(self.url), "Pendente")
        self.assertNotContains(self.client.get(self.url), 'name="password"')
        self.assertNotContains(self.client.get(self.url), 'name="username"')

    def test_confirma_e_vincula_somente_empresas_previamente_autorizadas(self):
        convite = self.convite(areas_permitidas=["financeiro"], dashboards_permitidos=["financeiro:visao-geral"])
        codigo = self.iniciar("PESSOA@EMPRESA.COM.BR")
        self.assertFalse(EmpresaUsuario.objects.filter(empresa=self.empresa, usuario__email__iexact=convite.email).exists())
        self.assertRedirects(self.confirmar(codigo), reverse("empresas:lista"))
        usuario = get_user_model().objects.get(email=convite.email)
        self.assertTrue(usuario.check_password(self.senha))
        self.assertFalse(usuario.is_staff)
        vinculo = EmpresaUsuario.objects.get(usuario=usuario)
        self.assertEqual(vinculo.empresa, self.empresa)
        self.assertEqual(vinculo.papel, "viewer")
        self.assertEqual(vinculo.areas_permitidas, ["financeiro"])
        self.assertEqual(vinculo.dashboards_permitidos, ["financeiro:visao-geral"])
        self.assertFalse(EmpresaUsuario.objects.filter(usuario=usuario, empresa=self.outra).exists())
        convite.refresh_from_db()
        self.assertEqual(convite.utilizado_por, usuario)

    def test_mesmo_email_pode_ser_autorizado_em_duas_empresas(self):
        self.convite()
        PreCadastroUsuario.objects.create(empresa=self.outra, email="pessoa@empresa.com.br", nome="Pessoa", papel="gestor")
        self.confirmar(self.iniciar())
        u = get_user_model().objects.get(email="pessoa@empresa.com.br")
        self.assertEqual(EmpresaUsuario.objects.filter(usuario=u).count(), 2)

    def test_codigo_errado_e_limite_de_tentativas_nao_liberam_acesso(self):
        self.convite()
        codigo = self.iniciar()
        errado = "00000000" if codigo != "00000000" else "11111111"
        for _ in range(5):
            self.assertEqual(self.confirmar(errado).status_code, 200)
        self.confirmar(codigo)
        self.assertFalse(get_user_model().objects.filter(email="pessoa@empresa.com.br").exists())
        self.assertEqual(ConfirmacaoCadastro.objects.get().tentativas, 5)

    def test_expiracao_e_reutilizacao_do_codigo(self):
        self.convite()
        codigo = self.iniciar()
        registro = ConfirmacaoCadastro.objects.get()
        ConfirmacaoCadastro.objects.filter(pk=registro.pk).update(expira_em=timezone.now() - timedelta(seconds=1))
        self.confirmar(codigo)
        self.assertFalse(get_user_model().objects.filter(email=registro.email).exists())
        ConfirmacaoCadastro.objects.filter(pk=registro.pk).update(expira_em=timezone.now() + timedelta(minutes=1))
        self.confirmar(codigo)
        u, erro = confirmar_cadastro(registro.pk, codigo, self.senha)
        self.assertIsNone(u)
        self.assertTrue(erro)

    def test_cancelamento_antes_da_confirmacao_impede_vinculo(self):
        convite = self.convite()
        codigo = self.iniciar()
        self.client.force_login(self.admin)
        self.client.post(self.url, {"convite_id": convite.pk, "acao": "cancelar_pre_cadastro"})
        self.client.logout()
        # A new browser cannot claim the other browser's confirmation session.
        sessao = self.client.session
        sessao["cadastro_confirmacao_id"] = ConfirmacaoCadastro.objects.get().pk
        sessao.save()
        self.confirmar(codigo)
        self.assertFalse(EmpresaUsuario.objects.filter(usuario__email="pessoa@empresa.com.br").exists())

    def test_pessoa_existente_deve_entrar_sem_sobrescrever_nome_ou_senha(self):
        u = get_user_model().objects.create_user(username="original", email="pessoa@empresa.com.br", first_name="Original", password=self.senha)
        self.convite()
        codigo = self.iniciar()
        self.assertContains(self.client.get(reverse("accounts:confirmar_cadastro")), "Entre com sua senha atual")
        self.confirmar(codigo)
        self.assertFalse(EmpresaUsuario.objects.filter(usuario=u).exists())
        self.client.post(reverse("accounts:login"), {"username": u.email, "password": self.senha})
        self.assertRedirects(self.confirmar(codigo), reverse("empresas:lista"))
        u.refresh_from_db()
        self.assertTrue(u.check_password(self.senha))
        self.assertEqual(u.first_name, "Original")
        self.assertEqual(get_user_model().objects.filter(email=u.email).count(), 1)

    def test_link_existente_revogado_nao_e_reativado_pelo_pre_cadastro(self):
        u = get_user_model().objects.create_user(username="original", email="pessoa@empresa.com.br", password=self.senha)
        EmpresaUsuario.objects.create(usuario=u, empresa=self.empresa, ativo=False, papel="viewer", areas_permitidas=["comercial"])
        self.convite(papel="admin")
        registro = enviar_codigo_cadastro(u.email, "Nome")
        codigo = re.search(r"\b([0-9]{8})\b", mail.outbox[-1].body).group(1)
        confirmar_cadastro(registro.pk, codigo, None, u)
        vinculo = EmpresaUsuario.objects.get(usuario=u)
        self.assertFalse(vinculo.ativo)
        self.assertEqual(vinculo.papel, "viewer")
        self.assertEqual(vinculo.areas_permitidas, ["comercial"])

    def test_vinculo_posterior_so_e_automatico_para_email_comprovado(self):
        self.confirmar(self.iniciar())
        u = get_user_model().objects.get(email="pessoa@empresa.com.br")
        self.convite()
        self.assertEqual(vincular_email_verificado(u), 1)
        self.assertEqual(vincular_email_verificado(u), 0)
        falso = get_user_model().objects.create_user(username="falso", email="outro@empresa.com.br")
        self.convite(email=falso.email)
        self.assertEqual(vincular_email_verificado(falso), 0)

    def test_edicao_de_permissoes_nao_altera_identidade_ou_senha_global(self):
        u = get_user_model().objects.create_user(username="original", email="original@empresa.com.br", first_name="Original", password=self.senha)
        vinculo = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=u)
        self.client.force_login(self.admin)
        self.client.post(self.url, {"vinculo_id": vinculo.pk, "first_name": "Invasor", "email": "outro@empresa.com.br", "password": "mudada", "papel": "gestor", "ativo": "on"})
        u.refresh_from_db()
        self.assertEqual(u.email, "original@empresa.com.br")
        self.assertEqual(u.first_name, "Original")
        self.assertTrue(u.check_password(self.senha))

    def test_gestor_nao_pode_elevar_perfil_ou_editar_outra_empresa(self):
        EmpresaUsuario.objects.filter(usuario=self.admin).update(papel="gestor")
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {"first_name": "Pessoa", "email": "pessoa@empresa.com.br", "papel": "admin"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PreCadastroUsuario.objects.exists())
        outro = PreCadastroUsuario.objects.create(empresa=self.outra, nome="Pessoa", email="pessoa@empresa.com.br")
        self.assertEqual(self.client.post(self.url, {"convite_id": outro.pk, "acao": "cancelar_pre_cadastro"}).status_code, 404)

    def test_duplicidade_de_email_na_mesma_empresa_e_case_insensitive(self):
        self.convite()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.convite(email="PESSOA@empresa.com.br")
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {"email": "PESSOA@empresa.com.br", "first_name": "Pessoa"})
        self.assertContains(r, "ja possui um pre-cadastro")

    def test_reenvio_limitado_e_codigo_anterior_invalidado(self):
        registro = enviar_codigo_cadastro("pessoa@empresa.com.br", "Pessoa")
        antigo = re.search(r"\b([0-9]{8})\b", mail.outbox[-1].body).group(1)
        with self.assertRaises(ValidationError):
            enviar_codigo_cadastro(registro.email, "Pessoa")
        for _ in range(4):
            ConfirmacaoCadastro.objects.filter(pk=registro.pk).update(enviada_em=timezone.now() - timedelta(minutes=2))
            enviar_codigo_cadastro(registro.email, "Pessoa")
        ConfirmacaoCadastro.objects.filter(pk=registro.pk).update(enviada_em=timezone.now() - timedelta(minutes=2))
        with self.assertRaises(ValidationError):
            enviar_codigo_cadastro(registro.email, "Pessoa")
        self.assertIsNone(confirmar_cadastro(registro.pk, antigo, self.senha)[0])

    @patch("apps.accounts.registration.send_mail", side_effect=ConnectionError)
    def test_falha_de_email_nao_cria_conta_ou_libera_acesso(self, envio):
        self.convite()
        r = self.client.post(reverse("accounts:cadastro"), {"email": "pessoa@empresa.com.br", "first_name": "Pessoa"})
        self.assertContains(r, "Nao foi possivel enviar")
        self.assertFalse(get_user_model().objects.filter(email="pessoa@empresa.com.br").exists())

    def test_confirmacao_exige_sessao_e_csrf(self):
        self.iniciar()
        outro = Client()
        self.assertRedirects(outro.get(reverse("accounts:confirmar_cadastro")), reverse("accounts:cadastro"))
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post(reverse("accounts:cadastro"), {"email": "x@empresa.com.br", "first_name": "X"}).status_code, 403)

    def test_senha_fraca_ou_divergente_nao_cria_usuario(self):
        codigo = self.iniciar()
        r = self.client.post(reverse("accounts:confirmar_cadastro"), {"code": codigo, "password1": "123", "password2": "123"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("accounts:confirmar_cadastro"), {"code": codigo, "password1": self.senha, "password2": "OutraSenha!"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email="pessoa@empresa.com.br").exists())

    def test_conta_desativada_na_origem_nao_recebe_novo_acesso(self):
        u = get_user_model().objects.create_user(username="desativado", email="pessoa@empresa.com.br", password=self.senha)
        self.convite()
        registro = enviar_codigo_cadastro(u.email, "Nome")
        codigo = re.search(r"\b([0-9]{8})\b", mail.outbox[-1].body).group(1)
        get_user_model().objects.filter(pk=u.pk).update(is_active=False)
        usuario, erro = confirmar_cadastro(registro.pk, codigo, None, u)
        self.assertIsNone(usuario)
        self.assertTrue(erro)
        self.assertFalse(EmpresaUsuario.objects.filter(usuario=u).exists())
