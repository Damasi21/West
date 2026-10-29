from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AcaoUsuarioLog, AmbienteWhiteLabel, Empresa, EmpresaUsuario
from .services import empresas_permitidas, usuario_admin_empresa, usuario_pode_acessar_dashboard, usuario_pode_personalizar_marca
from .white_label_forms import AmbienteWhiteLabelForm


class AmbienteWhiteLabelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_user(username="super-wl", is_superuser=True, is_staff=True)
        self.adm = User.objects.create_user(username="adm-wl", email="adm@example.com")
        self.outro = User.objects.create_user(username="outro-wl", email="outro@example.com")
        self.gestor = User.objects.create_user(username="gestor-wl")
        self.lider = User.objects.create_user(username="lider-wl")
        self.simples = User.objects.create_user(username="simples-wl")
        self.empresa = Empresa.objects.create(nome="Empresa Ambiente", nome_fantasia="Empresa Ambiente", cnpj="12.345.678/0001-90", grupo="Original")
        self.outra_empresa = Empresa.objects.create(nome="Outra Empresa", nome_fantasia="Outra Empresa", cnpj="23.456.789/0001-90")
        self.ambiente = AmbienteWhiteLabel.objects.create(nome="Marca Alfa", slug="marca-alfa")
        self.ambiente.empresas.add(self.empresa)
        self.ambiente.administradores.add(self.adm)
        self.outra_marca = AmbienteWhiteLabel.objects.create(nome="Marca Beta", slug="marca-beta", tipo="parceiro")
        self.outra_marca.empresas.add(self.outra_empresa)
        self.outra_marca.administradores.add(self.outro)
        for usuario, papel in [(self.gestor, "gestor"), (self.lider, "lider"), (self.simples, "viewer")]:
            EmpresaUsuario.objects.create(empresa=self.empresa, usuario=usuario, papel=papel)
        self.lista = reverse("empresas:white_label")
        self.novo = reverse("empresas:white_label_novo")
        self.editar = reverse("empresas:white_label_editar", args=[self.ambiente.slug])
        self.cnpj = reverse("empresas:white_label_cnpj_novo", args=[self.ambiente.slug])

    def dados(self, **extra):
        dados = dict(nome="Nova Marca", slug="nova-marca", tipo="grupo", ativa="on", administradores=[str(self.adm.pk)], empresas=[str(self.empresa.pk)])
        dados.update(extra)
        return dados

    def dados_cnpj(self, **extra):
        dados = dict(nome="Novo CNPJ Ltda", nome_fantasia="Novo CNPJ", cnpj="34.567.890/0001-12", grupo="", ativa="on")
        dados.update(extra)
        return dados

    def test_super_cadastra_ambiente_com_marca_administrador_e_empresas(self):
        self.client.force_login(self.superuser)
        response = self.client.post(self.novo, self.dados())
        self.assertRedirects(response, reverse("empresas:white_label_editar", args=["nova-marca"]))
        marca = AmbienteWhiteLabel.objects.get(slug="nova-marca")
        self.assertEqual(list(marca.empresas.all()), [self.empresa])
        self.assertEqual(list(marca.administradores.all()), [self.adm])
        self.assertTrue(AcaoUsuarioLog.objects.filter(dados__ambiente_id=marca.pk).exists())

    def test_lista_super_todas_adm_somente_suas_marcas(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.lista)
        self.assertContains(response, "Marca Alfa")
        self.assertContains(response, "Marca Beta")
        self.client.force_login(self.adm)
        response = self.client.get(self.lista)
        self.assertContains(response, "Marca Alfa")
        self.assertNotContains(response, "Marca Beta")
        self.assertNotContains(response, self.novo)

    def test_gestor_lider_simples_staff_nao_gerenciam_ambientes(self):
        staff = get_user_model().objects.create_user(username="staff-wl", is_staff=True)
        for usuario in (self.gestor, self.lider, self.simples, staff):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.lista).status_code, 403)
            self.assertEqual(self.client.post(self.novo, self.dados()).status_code, 403)
            self.assertEqual(self.client.get(self.editar).status_code, 404)
            self.assertEqual(self.client.post(self.cnpj, self.dados_cnpj()).status_code, 404)

    def test_adm_nao_acessa_outra_marca_por_url_ou_post(self):
        self.client.force_login(self.adm)
        url = reverse("empresas:white_label_editar", args=[self.outra_marca.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.dados()).status_code, 404)
        url = reverse("empresas:white_label_cnpj_novo", args=[self.outra_marca.slug])
        self.assertEqual(self.client.post(url, self.dados_cnpj()).status_code, 404)

    def test_adm_edita_marca_mas_nao_responsaveis_slug_status(self):
        self.client.force_login(self.adm)
        response = self.client.post(self.editar, self.dados(nome="Marca Alterada", slug="troca-host", administradores=[self.outro.pk], ativa=""))
        self.assertRedirects(response, self.editar)
        self.ambiente.refresh_from_db()
        self.assertEqual(self.ambiente.nome, "Marca Alterada")
        self.assertEqual(self.ambiente.slug, "marca-alfa")
        self.assertTrue(self.ambiente.ativa)
        self.assertEqual(list(self.ambiente.administradores.all()), [self.adm])
        self.assertFalse(usuario_admin_empresa(self.outro, self.empresa))

    def test_adm_nao_injeta_cnpj_de_outro_ambiente(self):
        self.client.force_login(self.adm)
        response = self.client.post(self.editar, self.dados(empresas=[self.empresa.pk, self.outra_empresa.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(self.ambiente.empresas.filter(pk=self.outra_empresa.pk).exists())

    def test_adm_pode_vincular_cnpj_com_perfil_white_label_direto(self):
        EmpresaUsuario.objects.create(empresa=self.outra_empresa, usuario=self.adm, papel="white_label")
        self.client.force_login(self.adm)
        self.assertRedirects(self.client.post(self.editar, self.dados(empresas=[self.empresa.pk, self.outra_empresa.pk])), self.editar)
        self.assertEqual(self.ambiente.empresas.count(), 2)

    def test_administrador_herda_gestao_apenas_cnpjs_do_ambiente(self):
        self.assertTrue(usuario_admin_empresa(self.adm, self.empresa))
        self.assertTrue(usuario_pode_personalizar_marca(self.adm, self.empresa))
        self.assertTrue(usuario_pode_acessar_dashboard(self.adm, self.empresa, "financeiro", "contas-a-pagar"))
        self.assertFalse(usuario_admin_empresa(self.adm, self.outra_empresa))
        self.assertEqual(list(empresas_permitidas(self.adm)), [self.empresa])
        self.client.force_login(self.adm)
        response = self.client.get(reverse("dashboards:usuarios", args=[self.empresa.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="gestor"')
        self.assertFalse(EmpresaUsuario.objects.filter(usuario=self.adm, empresa=self.empresa).exists())

    def test_papel_direto_restrito_nao_limita_administrador_do_ambiente(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.adm, papel="lider", areas_permitidas=["comercial"])
        self.assertTrue(usuario_pode_acessar_dashboard(self.adm, self.empresa, "financeiro", "contas-a-pagar"))
        self.client.force_login(self.adm)
        response = self.client.get(reverse("dashboards:usuarios", args=[self.empresa.slug]))
        self.assertContains(response, 'value="gestor"')

    def test_desativar_remover_administrador_ou_cnpj_revoga_gestao(self):
        self.ambiente.ativa = False
        self.ambiente.save()
        self.assertFalse(usuario_admin_empresa(self.adm, self.empresa))
        self.assertFalse(empresas_permitidas(self.adm).exists())
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get(self.editar).status_code, 404)
        self.ambiente.ativa = True
        self.ambiente.save()
        self.ambiente.administradores.remove(self.adm)
        self.assertFalse(usuario_admin_empresa(self.adm, self.empresa))
        self.ambiente.administradores.add(self.adm)
        self.ambiente.empresas.clear()
        self.assertFalse(usuario_admin_empresa(self.adm, self.empresa))

    def test_usuario_inativo_nao_administra_ambiente(self):
        self.adm.is_active = False
        self.adm.save()
        self.assertFalse(usuario_admin_empresa(self.adm, self.empresa))

    def test_mesmo_cnpj_em_duas_marcas_sem_duplicar_empresa(self):
        self.outra_marca.empresas.add(self.empresa)
        self.assertEqual(Empresa.objects.count(), 2)
        self.assertTrue(usuario_admin_empresa(self.outro, self.empresa))
        self.ambiente.empresas.remove(self.empresa)
        self.assertTrue(usuario_admin_empresa(self.outro, self.empresa))
        self.assertFalse(usuario_admin_empresa(self.adm, self.empresa))
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.grupo, "Original")

    def test_remover_vinculo_nao_exclui_empresa_ou_usuarios(self):
        self.client.force_login(self.adm)
        self.assertRedirects(self.client.post(self.editar, self.dados(empresas=[])), self.editar)
        self.assertTrue(Empresa.objects.filter(pk=self.empresa.pk).exists())
        self.assertTrue(EmpresaUsuario.objects.filter(usuario=self.gestor, empresa=self.empresa).exists())
        self.assertTrue(usuario_admin_empresa(self.gestor, self.empresa))

    def test_cadastra_cnpj_no_ambiente_sem_criar_sincronizacao(self):
        self.client.force_login(self.adm)
        self.assertRedirects(self.client.post(self.cnpj, self.dados_cnpj()), self.editar)
        empresa = Empresa.objects.get(cnpj="34.567.890/0001-12")
        self.assertTrue(self.ambiente.empresas.filter(pk=empresa.pk).exists())
        self.assertTrue(usuario_admin_empresa(self.adm, empresa))
        self.assertFalse(self.outra_marca.empresas.filter(pk=empresa.pk).exists())

    def test_novo_cnpj_rejeita_duplicidade_com_ou_sem_mascara(self):
        self.client.force_login(self.adm)
        for cnpj in (self.empresa.cnpj, "12345678000190", "123"):
            response = self.client.post(self.cnpj, self.dados_cnpj(cnpj=cnpj))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(Empresa.objects.count(), 2)

    def test_campos_invalidos_e_identificador_duplicado(self):
        self.client.force_login(self.superuser)
        for extra in (dict(nome=""), dict(administradores=[]), dict(slug="marca-alfa"), dict(slug="Domínio Inválido"), dict(email_suporte="invalido")):
            response = self.client.post(self.novo, self.dados(**extra))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(AmbienteWhiteLabel.objects.count(), 2)

    def test_busca_e_contagem_sem_duplicidade(self):
        self.ambiente.administradores.add(self.superuser)
        self.ambiente.empresas.add(self.outra_empresa)
        self.client.force_login(self.superuser)
        response = self.client.get(self.lista, {"q": self.empresa.cnpj})
        self.assertContains(response, "Marca Alfa")
        self.assertNotContains(response, "Marca Beta")
        ambiente = list(response.context["ambientes"])[0]
        self.assertEqual(ambiente.total_cnpjs, 2)
        self.assertEqual(ambiente.total_administradores, 2)

    def test_menu_principal_super_e_responsavel_sem_empresa_selecionada(self):
        for usuario in (self.superuser, self.adm):
            self.client.force_login(usuario)
            self.assertContains(self.client.get(reverse("empresas:lista")), self.lista)
        self.client.force_login(self.gestor)
        self.assertNotContains(self.client.get(reverse("empresas:lista")), self.lista)

    def test_campos_privilegiados_ausentes_no_formulario_do_responsavel(self):
        form = AmbienteWhiteLabelForm(instance=self.ambiente, operador=self.adm)
        for nome in ("administradores", "slug", "ativa"):
            self.assertNotIn(nome, form.fields)
        self.assertEqual(list(form.fields["empresas"].queryset), [self.empresa])

    def test_login_csrf_e_metodos(self):
        self.assertEqual(self.client.get(self.lista).status_code, 302)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.superuser)
        self.assertEqual(csrf.post(self.novo, self.dados()).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.delete(self.editar).status_code, 405)
        self.assertEqual(self.client.post(self.lista).status_code, 405)

    def test_administrador_de_ambiente_pode_assumir_caso_do_auditor(self):
        from apps.auditor.models import CasoAuditoria, ExecucaoAuditoria
        execucao = ExecucaoAuditoria.objects.create(empresa=self.empresa, status="concluida")
        caso = CasoAuditoria.objects.create(empresa=self.empresa, identidade="white-label-qa", regra="valor_atipico",
            titulo="Validar lançamento", severidade="atencao", recomendacao="Conferir documento",
            ultima_deteccao=timezone.now(), ultima_execucao=execucao)
        self.client.force_login(self.adm)
        url = reverse("auditor:detalhe", args=[self.empresa.slug, caso.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        usuarios = response.context["form"].fields["responsavel"].queryset
        self.assertTrue(usuarios.filter(pk=self.adm.pk).exists())
        self.assertFalse(usuarios.filter(pk=self.outro.pk).exists())
        response = self.client.post(url, {"status": "analise", "responsavel": self.adm.pk, "comentario": "Em conferência pelo responsável da marca."})
        self.assertEqual(response.status_code, 302)
        caso.refresh_from_db()
        self.assertEqual(caso.responsavel_id, self.adm.pk)
