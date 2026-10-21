from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.empresas.models import Empresa, EmpresaUsuario, PreCadastroUsuario
from .models import ConfirmacaoCadastro
from .registration import cadastrar_pelo_sistema, vincular_pre_cadastros_sistema


@override_settings(CADASTRO_EXIGIR_CONFIRMACAO_EMAIL=False)
class CadastroSistemaTests(TestCase):
    senha = "MinhaSenhaNovaSegura2026!"
    email = "pessoa@empresa.com.br"

    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Autorizada", cnpj="00.000.000/0001-81")
        self.convite = PreCadastroUsuario.objects.create(
            empresa=self.empresa, nome="Pessoa", email=self.email,
            papel="viewer", areas_permitidas=["financeiro"], dashboards_permitidos=["financeiro:visao-geral"],
        )

    def cadastrar(self, **extra):
        dados = dict(email=self.email.upper(), first_name="Pessoa", password1=self.senha, password2=self.senha)
        dados.update(extra)
        return self.client.post(reverse("accounts:cadastro"), dados)

    @patch("apps.accounts.registration.send_mail", side_effect=AssertionError("SMTP nao deve ser usado"))
    def test_cria_conta_e_vincula_permissoes_sem_email(self, envio):
        self.assertRedirects(self.cadastrar(papel="admin", is_superuser="True"), reverse("empresas:lista"))
        usuario = get_user_model().objects.get(email=self.email)
        self.assertTrue(usuario.check_password(self.senha))
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(int(self.client.session["_auth_user_id"]), usuario.pk)
        vinculo = EmpresaUsuario.objects.get(usuario=usuario)
        self.assertEqual(vinculo.papel, "viewer")
        self.assertEqual(vinculo.areas_permitidas, ["financeiro"])
        self.assertEqual(vinculo.dashboards_permitidos, ["financeiro:visao-geral"])
        self.convite.refresh_from_db()
        self.assertEqual(self.convite.utilizado_por, usuario)
        self.assertIsNone(ConfirmacaoCadastro.objects.get().email_verificado_em)
        envio.assert_not_called()

    def test_sem_pre_cadastro_nao_cria_conta(self):
        self.assertEqual(self.cadastrar(email="desconhecido@empresa.com.br").status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

    def test_convite_cancelado_ou_empresa_inativa_nao_autorizam(self):
        self.convite.ativo = False
        self.convite.save()
        self.assertEqual(self.cadastrar().status_code, 200)
        self.convite.ativo = True
        self.convite.save()
        self.empresa.ativa = False
        self.empresa.save()
        self.assertEqual(self.cadastrar().status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

    def test_conta_existente_nao_tem_senha_ou_nome_substituidos(self):
        usuario = get_user_model().objects.create_user(username="original", email=self.email, first_name="Original", password=self.senha)
        self.assertEqual(self.cadastrar(password1="OutraSenhaNova2026!", password2="OutraSenhaNova2026!").status_code, 200)
        self.assertFalse(EmpresaUsuario.objects.exists())
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(self.senha))
        self.assertEqual(usuario.first_name, "Original")
        self.assertEqual(get_user_model().objects.count(), 1)

    @patch("apps.accounts.registration.send_mail", side_effect=AssertionError("SMTP nao deve ser usado"))
    def test_login_existente_vincula_convites_sem_email(self, envio):
        usuario = get_user_model().objects.create_user(username="legado", email=self.email, password=self.senha)
        self.assertRedirects(self.client.post(reverse("accounts:login"), {"username": self.email, "password": self.senha}), reverse("empresas:lista"))
        self.assertTrue(EmpresaUsuario.objects.filter(usuario=usuario, empresa=self.empresa).exists())
        envio.assert_not_called()

    def test_login_errado_nao_vincula(self):
        get_user_model().objects.create_user(username="legado", email=self.email, password=self.senha)
        self.client.post(reverse("accounts:login"), {"username": self.email, "password": "incorreta"})
        self.assertFalse(EmpresaUsuario.objects.exists())

    def test_nao_reativa_acesso_revogado(self):
        usuario = get_user_model().objects.create_user(username="legado", email=self.email, password=self.senha)
        vinculo = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=usuario, ativo=False, papel="gestor")
        vincular_pre_cadastros_sistema(usuario)
        vinculo.refresh_from_db()
        self.assertFalse(vinculo.ativo)
        self.assertEqual(vinculo.papel, "gestor")

    def test_email_duplicado_ou_conta_inativa_nao_recebem_vinculo(self):
        usuario = get_user_model().objects.create_user(username="legado", email=self.email, is_active=False)
        self.assertEqual(vincular_pre_cadastros_sistema(usuario), 0)
        usuario.is_active = True
        usuario.save()
        get_user_model().objects.create_user(username="duplicado", email=self.email.upper())
        self.assertEqual(vincular_pre_cadastros_sistema(usuario), 0)
        self.assertFalse(EmpresaUsuario.objects.exists())

    def test_senha_fraca_ou_diferente_nao_cria_conta(self):
        self.assertEqual(self.cadastrar(password1="123", password2="123").status_code, 200)
        self.assertEqual(self.cadastrar(password2="OutraSenha2026!").status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

    def test_servico_revalida_autorizacao_e_impede_reutilizacao(self):
        usuario = cadastrar_pelo_sistema(self.email, "Pessoa", self.senha)
        with self.assertRaises(ValidationError):
            cadastrar_pelo_sistema(self.email, "Outra", self.senha)
        self.assertEqual(EmpresaUsuario.objects.filter(usuario=usuario).count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_varias_empresas_somente_as_autorizadas(self):
        outra = Empresa.objects.create(nome="Segunda Autorizada", cnpj="00.000.000/0001-82")
        PreCadastroUsuario.objects.create(empresa=outra, nome="Pessoa", email=self.email)
        Empresa.objects.create(nome="Sem Autorizacao", cnpj="00.000.000/0001-83")
        self.cadastrar()
        usuario = get_user_model().objects.get(email=self.email)
        self.assertEqual(set(EmpresaUsuario.objects.filter(usuario=usuario).values_list("empresa_id", flat=True)), {self.empresa.pk, outra.pk})

    def test_tela_sem_codigo_e_exige_csrf(self):
        response = self.client.get(reverse("accounts:cadastro"))
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, "Criar minha conta")
        self.assertNotContains(response, "Enviar codigo")
        self.assertRedirects(self.client.get(reverse("accounts:confirmar_cadastro")), reverse("accounts:cadastro"))
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse("accounts:cadastro"), {}).status_code, 403)
