from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.accounts.registration import _vincular_pre_cadastros
from apps.dashboards.views import areas_habilitadas
from .forms import EmpresaUsuarioForm
from .models import Empresa, EmpresaUsuario, PreCadastroUsuario
from .services import (
    empresas_permitidas, empresas_permitidas_no_grupo, usuario_admin_empresa, usuario_pode_acessar_area,
    usuario_pode_acessar_dashboard, usuario_pode_gerenciar_vinculo,
    usuario_pode_personalizar_marca,
)


class HierarquiaPerfisTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Hierarquia", nome_fantasia="Hierarquia", cnpj="00123456000101")
        self.outra = Empresa.objects.create(nome="Outra", nome_fantasia="Outra", cnpj="00123456000102")
        self.usuarios, self.vinculos = {}, {}
        for papel in EmpresaUsuario.Papel.values:
            usuario = get_user_model().objects.create_user(username=papel, email=f"{papel}@teste.com")
            self.usuarios[papel] = usuario
            self.vinculos[papel] = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=usuario, papel=papel)
        self.lider = self.usuarios["lider"]
        self.vinculos["lider"].areas_permitidas = ["comercial"]
        self.vinculos["lider"].dashboards_permitidos = ["comercial:faturamento"]
        self.vinculos["lider"].save()
        self.superuser = get_user_model().objects.create_superuser(username="super", email="super@teste.com", password="test-only")
        self.url = reverse("dashboards:usuarios", args=[self.empresa.slug])

    def form(self, usuario=None, **dados):
        base = dict(email="novo@teste.com", first_name="Novo", papel="viewer")
        base.update(dados)
        return EmpresaUsuarioForm(base, empresa=self.empresa, operador=usuario or self.lider, areas=areas_habilitadas())

    def convidar(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def vincular(self, convite):
        usuario = get_user_model().objects.create_user(username="convidado", email=convite.email)
        from django.db import transaction
        with transaction.atomic():
            _vincular_pre_cadastros(usuario)
        return usuario

    def test_quatro_perfis_e_rotulos(self):
        self.assertEqual(dict(EmpresaUsuario.Papel.choices), {
            "white_label": "Adm White Label", "gestor": "Gestor", "lider": "Líder", "viewer": "Usuário simples",
        })

    def test_masters_administram_empresa_e_apenas_white_label_personaliza(self):
        for papel in ("white_label", "gestor"):
            usuario = self.usuarios[papel]
            self.assertTrue(usuario_admin_empresa(usuario, self.empresa))
            self.assertTrue(usuario_pode_acessar_dashboard(usuario, self.empresa, "financeiro", "contas-a-pagar"))
        self.assertTrue(usuario_pode_personalizar_marca(self.usuarios["white_label"], self.empresa))
        self.assertFalse(usuario_pode_personalizar_marca(self.usuarios["gestor"], self.empresa))
        for papel in ("lider", "viewer"):
            self.assertFalse(usuario_admin_empresa(self.usuarios[papel], self.empresa))
            self.assertFalse(usuario_pode_personalizar_marca(self.usuarios[papel], self.empresa))

    def test_superuser_global_staff_nao_e_perfil_master(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.assertEqual(empresas_permitidas(staff).count(), 0)
        self.assertFalse(usuario_admin_empresa(staff, self.empresa))
        self.assertFalse(usuario_pode_personalizar_marca(staff, self.empresa))
        self.assertEqual(empresas_permitidas(self.superuser).count(), 2)
        self.assertTrue(usuario_pode_personalizar_marca(self.superuser, self.outra))

    def test_masters_nao_acessam_outra_empresa_sem_vinculo(self):
        for papel in ("white_label", "gestor"):
            self.assertFalse(usuario_admin_empresa(self.usuarios[papel], self.outra))
            self.assertFalse(usuario_pode_acessar_dashboard(self.usuarios[papel], self.outra, "comercial", "faturamento"))

    def test_perfis_disponiveis_por_operador(self):
        for operador, esperados in [
            (self.superuser, {"white_label", "gestor", "lider", "viewer"}),
            (self.usuarios["white_label"], {"white_label", "gestor", "lider", "viewer"}),
            (self.usuarios["gestor"], {"gestor", "lider", "viewer"}),
            (self.lider, {"viewer"}),
        ]:
            self.assertEqual({v for v, _ in self.form(operador).fields["papel"].choices}, esperados)

    def test_lider_ve_apenas_opcoes_que_pode_delegar(self):
        form = self.form()
        self.assertEqual([v for v, _ in form.fields["areas_permitidas"].choices], ["comercial"])
        self.assertEqual([v for v, _ in form.fields["dashboards_permitidos"].choices], ["comercial:faturamento"])

    def test_lider_vazio_materializa_permissoes_e_registra_origem(self):
        convite = self.convidar()
        self.assertEqual(convite.areas_permitidas, ["comercial"])
        self.assertEqual(convite.dashboards_permitidos, ["comercial:faturamento"])
        self.assertEqual(convite.delegado_por, self.vinculos["lider"])
        self.assertEqual(convite.criado_por, self.lider)

    def test_lider_nao_eleva_papel_nem_injeta_modulo_dashboard(self):
        for extra in [dict(papel="gestor"), dict(papel="lider"), dict(papel="white_label"),
                      dict(areas_permitidas=["financeiro"]),
                      dict(dashboards_permitidos=["comercial:desempenho-de-vendedores"]),
                      dict(dashboards_permitidos=["financeiro:contas-a-pagar"])]:
            form = self.form(**extra)
            self.assertFalse(form.is_valid(), extra)
        self.assertEqual(PreCadastroUsuario.objects.count(), 0)

    def test_gestor_convida_lider_mas_nao_white_label(self):
        form = self.form(self.usuarios["gestor"], papel="lider", areas_permitidas=["comercial"])
        self.assertTrue(form.is_valid(), form.errors)
        convite = form.save()
        self.assertIsNone(convite.delegado_por)
        self.assertFalse(self.form(self.usuarios["gestor"], email="outro@teste.com", papel="white_label").is_valid())

    def test_simples_nao_gerencia_e_lider_nao_edita_master_ou_simples_alheio(self):
        self.assertFalse(usuario_pode_gerenciar_vinculo(self.usuarios["viewer"], self.empresa))
        for papel in EmpresaUsuario.Papel.values:
            self.assertFalse(usuario_pode_gerenciar_vinculo(self.lider, self.empresa, self.vinculos[papel]))
        convite = self.convidar()
        self.assertTrue(usuario_pode_gerenciar_vinculo(self.lider, self.empresa, convite))

    def test_cadastro_preserva_delegacao_e_revogacao_imediata(self):
        usuario = self.vincular(self.convidar())
        self.assertTrue(usuario_pode_acessar_dashboard(usuario, self.empresa, "comercial", "faturamento"))
        self.assertFalse(usuario_pode_acessar_dashboard(usuario, self.empresa, "financeiro", "contas-a-pagar"))
        lider = self.vinculos["lider"]
        lider.areas_permitidas = ["financeiro"]
        lider.save()
        self.assertFalse(usuario_pode_acessar_dashboard(usuario, self.empresa, "comercial", "faturamento"))
        lider.ativo = False
        lider.save()
        self.assertFalse(usuario_pode_acessar_area(usuario, self.empresa, "comercial"))

    def test_lider_desativado_apos_convite_nao_libera_acesso_no_cadastro(self):
        convite = self.convidar()
        self.vinculos["lider"].ativo = False
        self.vinculos["lider"].save()
        usuario = self.vincular(convite)
        self.assertFalse(usuario_pode_acessar_dashboard(usuario, self.empresa, "comercial", "faturamento"))

    def test_revalida_revogacao_entre_validar_e_salvar(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        EmpresaUsuario.objects.filter(pk=self.vinculos["lider"].pk).update(ativo=False)
        with self.assertRaises(ValidationError):
            form.save()
        self.assertEqual(PreCadastroUsuario.objects.count(), 0)

    def test_revalida_escopo_reduzido_entre_validar_e_salvar(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        EmpresaUsuario.objects.filter(pk=self.vinculos["lider"].pk).update(areas_permitidas=["financeiro"])
        with self.assertRaises(ValidationError):
            form.save()

    def test_master_reassume_delegado_sem_limite_do_lider(self):
        usuario = self.vincular(self.convidar())
        vinculo = EmpresaUsuario.objects.get(usuario=usuario, empresa=self.empresa)
        form = EmpresaUsuarioForm(dict(papel="viewer", ativo="on", areas_permitidas=["financeiro"], dashboards_permitidos=["financeiro:contas-a-pagar"]),
                                empresa=self.empresa, operador=self.usuarios["gestor"], areas=areas_habilitadas(), vinculo=vinculo)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(usuario_pode_acessar_dashboard(usuario, self.empresa, "financeiro", "contas-a-pagar"))
        self.assertFalse(usuario_pode_gerenciar_vinculo(self.lider, self.empresa, EmpresaUsuario.objects.get(pk=vinculo.pk)))

    def test_nao_edita_proprio_perfil_nem_superuser(self):
        for papel in ("gestor", "white_label"):
            self.assertFalse(usuario_pode_gerenciar_vinculo(self.usuarios[papel], self.empresa, self.vinculos[papel]))
        superior = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.superuser, papel="viewer")
        self.assertFalse(usuario_pode_gerenciar_vinculo(self.usuarios["white_label"], self.empresa, superior))

    def test_lider_tela_convite_e_menu_sem_parametros(self):
        self.client.force_login(self.lider)
        response = self.client.get(self.url)
        self.assertContains(response, "Usuários")
        self.assertContains(response, 'value="viewer"')
        self.assertNotContains(response, 'value="gestor"')
        self.assertNotContains(response, reverse("dashboards:area", args=[self.empresa.slug, "financeiro"]))
        self.assertEqual(self.client.get(reverse("dashboards:parametros", args=[self.empresa.slug])).status_code, 403)
        response = self.client.get(reverse("dashboards:home", args=[self.empresa.slug]))
        self.assertContains(response, self.url)

    def test_lider_nao_edita_por_url_e_post_alvos_de_outra_pessoa(self):
        self.client.force_login(self.lider)
        for papel in ("gestor", "white_label", "viewer"):
            self.assertEqual(self.client.get(self.url, {"editar": self.vinculos[papel].pk}).status_code, 403)
        convite = PreCadastroUsuario.objects.create(empresa=self.empresa, nome="Outro", email="outro@teste.com")
        self.assertEqual(self.client.post(self.url, {"convite_id": convite.pk, "acao": "cancelar_pre_cadastro"}).status_code, 403)
        self.client.force_login(self.usuarios["viewer"])
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_migracao_admin_para_lider_preserva_escopo_e_outros_perfis(self):
        EmpresaUsuario.objects.filter(pk=self.vinculos["lider"].pk).update(papel="admin")
        convite = PreCadastroUsuario.objects.create(empresa=self.empresa, nome="Legado", email="legado@teste.com", papel="admin", areas_permitidas=["comercial"])
        migration = import_module("apps.empresas.migrations.0055_hierarquia_perfis")
        with connection.schema_editor() as editor:
            migration.converter_administradores(apps, editor)
        self.vinculos["lider"].refresh_from_db()
        convite.refresh_from_db()
        self.assertEqual(self.vinculos["lider"].papel, "lider")
        self.assertEqual(self.vinculos["lider"].dashboards_permitidos, ["comercial:faturamento"])
        self.assertEqual(convite.papel, "lider")
        self.assertEqual(convite.areas_permitidas, ["comercial"])
        self.vinculos["gestor"].refresh_from_db()
        self.assertEqual(self.vinculos["gestor"].papel, "gestor")

    def test_consolidacao_respeita_dashboard_por_cnpj(self):
        self.empresa.grupo = self.outra.grupo = "Grupo QA"
        self.empresa.save()
        self.outra.save()
        EmpresaUsuario.objects.create(empresa=self.outra, usuario=self.lider, papel="viewer", areas_permitidas=["financeiro"])
        self.assertEqual(set(empresas_permitidas_no_grupo(self.lider, self.empresa).values_list("pk", flat=True)), {self.empresa.pk, self.outra.pk})
        permitidas = empresas_permitidas_no_grupo(self.lider, self.empresa, "comercial", "faturamento")
        self.assertEqual(list(permitidas.values_list("pk", flat=True)), [self.empresa.pk])
        self.client.force_login(self.lider)
        response = self.client.get(reverse("dashboards:dashboard", args=[self.empresa.slug, "comercial", "faturamento"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([e.pk for e in response.context["empresas_filtro"]], [self.empresa.pk])

    def test_ampliar_lider_nao_amplia_usuario_ja_convidado(self):
        usuario = self.vincular(self.convidar())
        EmpresaUsuario.objects.filter(pk=self.vinculos["lider"].pk).update(areas_permitidas=[], dashboards_permitidos=[])
        self.assertTrue(usuario_pode_acessar_dashboard(usuario, self.empresa, "comercial", "faturamento"))
        self.assertFalse(usuario_pode_acessar_dashboard(usuario, self.empresa, "financeiro", "contas-a-pagar"))

    def test_masters_acessam_parametros_simples_nao_acessa(self):
        url = reverse("dashboards:parametros", args=[self.empresa.slug])
        for papel in ("gestor", "white_label"):
            self.client.force_login(self.usuarios[papel])
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.usuarios["viewer"])
        self.assertEqual(self.client.get(url).status_code, 403)
