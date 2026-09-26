from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa, EmpresaUsuario, IntegracaoOmie, SincronizacaoOmie


class TrialCadastroTests(TestCase):
    def test_trial_cria_empresa_usuario_integracao_e_sincronizacao(self):
        dados = {
            "nome_empresa": "Loja Trial",
            "razao_social": "Loja Trial LTDA",
            "cnpj": "12.345.678/0001-90",
            "responsavel": "Ana Trial",
            "email": "ana@trial.com.br",
            "telefone": "(11) 99999-0000",
            "app_key": "app-key",
            "app_secret": "app-secret",
            "password": "Senha-trial-2026",
        }

        response = self.client.post(reverse("empresas:trial"), dados)

        empresa = Empresa.objects.get(cnpj=dados["cnpj"])
        usuario = get_user_model().objects.get(email=dados["email"])
        integracao = IntegracaoOmie.objects.get(empresa=empresa)
        sincronizacao = SincronizacaoOmie.objects.get(empresa=empresa)

        self.assertRedirects(response, reverse("dashboards:home", kwargs={"empresa_slug": empresa.slug}))
        self.assertEqual(empresa.tipo_conta, Empresa.TipoConta.TRIAL)
        self.assertEqual(empresa.status_conta, Empresa.StatusConta.ATIVA)
        self.assertTrue(empresa.trial_ativo)
        self.assertEqual(empresa.trial_responsavel_nome, dados["responsavel"])
        self.assertEqual(usuario.first_name, dados["responsavel"])
        self.assertTrue(usuario.check_password(dados["password"]))
        self.assertTrue(
            EmpresaUsuario.objects.filter(
                empresa=empresa,
                usuario=usuario,
                papel=EmpresaUsuario.Papel.ADMINISTRADOR,
                ativo=True,
            ).exists()
        )
        self.assertEqual(integracao.app_key, dados["app_key"])
        self.assertEqual(integracao.obter_app_secret(), dados["app_secret"])
        self.assertEqual(sincronizacao.recurso, "completa")
        self.assertEqual(sincronizacao.status, SincronizacaoOmie.Status.PENDENTE)

    def test_trial_expirado_redireciona_dashboard(self):
        usuario = get_user_model().objects.create_user(
            username="trial@example.com",
            email="trial@example.com",
            password="senha",
        )
        empresa = Empresa.objects.create(
            nome="Empresa Expirada",
            nome_fantasia="Empresa Expirada",
            cnpj="12345678000191",
            tipo_conta=Empresa.TipoConta.TRIAL,
            status_conta=Empresa.StatusConta.ATIVA,
            trial_inicio=timezone.now() - timedelta(days=8),
            trial_expira_em=timezone.now() - timedelta(days=1),
        )
        EmpresaUsuario.objects.create(
            empresa=empresa,
            usuario=usuario,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR,
            ativo=True,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("dashboards:home", kwargs={"empresa_slug": empresa.slug}))

        self.assertRedirects(
            response,
            reverse("empresas:trial_expirado", kwargs={"empresa_slug": empresa.slug}),
        )
        empresa.refresh_from_db()
        self.assertEqual(empresa.status_conta, Empresa.StatusConta.EXPIRADA)
