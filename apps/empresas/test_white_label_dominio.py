from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import AmbienteWhiteLabel, Empresa, EmpresaUsuario, PreCadastroUsuario
from .services import empresas_permitidas, empresas_permitidas_no_grupo
from .white_label_branding import SESSION_MARCA
from .white_label_domains import _marca_host, marca_host_atual, normalizar_dominio
from .white_label_forms import AmbienteWhiteLabelForm


@override_settings(
    ALLOWED_HOSTS=["testserver", "app.elevdata.com.br", "app.revee.elevdata.com.br", "outra.example.com", "sem-marca.example.com"],
    WHITE_LABEL_PRIMARY_HOSTS=["testserver", "app.elevdata.com.br"],
    CADASTRO_EXIGIR_CONFIRMACAO_EMAIL=False,
)
class DominioWhiteLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.superuser = User.objects.create_user(username="super-host", is_superuser=True, is_staff=True)
        cls.owner = User.objects.create_user(username="owner-host", email="owner@teste.com")
        cls.viewer = User.objects.create_user(username="viewer-host", email="viewer@teste.com")
        cls.empresa = Empresa.objects.create(nome="Empresa Revee", nome_fantasia="Empresa Revee", cnpj="11444777000101", grupo="Compartilhado")
        cls.outra_empresa = Empresa.objects.create(nome="Empresa Externa", nome_fantasia="Empresa Externa", cnpj="11444777000102", grupo="Compartilhado")
        cls.marca = AmbienteWhiteLabel.objects.create(nome="GRUPO REVEE", slug="grupo-revee", dominio="app.revee.elevdata.com.br", dominio_ativo=True)
        cls.marca.empresas.add(cls.empresa)
        cls.marca.administradores.add(cls.owner)
        cls.outra = AmbienteWhiteLabel.objects.create(nome="Marca Externa", slug="externa", dominio="outra.example.com", dominio_ativo=True)
        cls.outra.empresas.add(cls.outra_empresa)
        cls.outra.administradores.add(cls.owner)
        for empresa in (cls.empresa, cls.outra_empresa):
            EmpresaUsuario.objects.create(empresa=empresa, usuario=cls.viewer, papel="viewer")

    def setUp(self):
        self.client = Client(HTTP_HOST=self.marca.dominio)

    def dados(self, **extra):
        dados = dict(nome=self.marca.nome, tipo="grupo", ativa="on", dominio=self.marca.dominio,
                     dominio_ativo="on", administradores=[self.owner.pk], empresas=[self.empresa.pk])
        dados.update(extra)
        return dados

    def test_login_raiz_tem_identidade_sem_selecao_previa(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["white_label_marca"], self.marca)
        self.assertTrue(response.context["white_label_tema"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Host", response["Vary"])
        self.assertIsNone(marca_host_atual())

    def test_host_prevalece_sobre_sessao_e_url_de_outra_marca(self):
        session = self.client.session
        session[SESSION_MARCA] = self.outra.pk
        session.save()
        self.assertEqual(self.client.get(reverse("accounts:login")).context["white_label_marca"], self.marca)
        self.assertEqual(self.client.get(reverse("accounts:login_marca", args=[self.outra.slug])).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:login_marca", args=[self.outra.slug]), {}).status_code, 404)

    def test_host_desconhecido_nao_cai_no_login_principal(self):
        response = Client(HTTP_HOST="sem-marca.example.com").get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "GRUPO REVEE", status_code=404)

    def test_host_nao_permitido_e_forwarded_host_nao_contornam_validacao(self):
        self.assertEqual(Client(HTTP_HOST="intruso.example.com").get("/").status_code, 400)
        response = self.client.get(reverse("accounts:login"), HTTP_X_FORWARDED_HOST=self.outra.dominio)
        self.assertEqual(response.context["white_label_marca"], self.marca)

    def test_dominio_desativado_e_marca_inativa_falham_sem_fallback(self):
        for campo in ("dominio_ativo", "ativa"):
            AmbienteWhiteLabel.objects.filter(pk=self.marca.pk).update(**{campo: False})
            self.assertEqual(self.client.get(reverse("accounts:login")).status_code, 404)
            AmbienteWhiteLabel.objects.filter(pk=self.marca.pk).update(**{campo: True})

    def test_lista_empresas_limitada_inclusive_para_superuser(self):
        for usuario in (self.superuser, self.owner, self.viewer):
            self.client.force_login(usuario)
            response = self.client.get(reverse("empresas:lista"))
            self.assertEqual(list(response.context["empresas"]), [self.empresa])
            self.assertNotContains(response, self.outra_empresa.nome)

    def test_cnpj_externo_bloqueado_em_get_post_exports_e_anexos(self):
        self.client.force_login(self.superuser)
        urls = [
            reverse("dashboards:home", args=[self.outra_empresa.slug]),
            reverse("dashboards:usuarios", args=[self.outra_empresa.slug]),
            reverse("dashboards:baixar_anexo_conta_local", args=[self.outra_empresa.slug, 123]),
            reverse("dashboards:nota_pagamento", args=[self.outra_empresa.slug, 123]),
            reverse("auditor:visao_geral", args=[self.outra_empresa.slug]),
        ]
        for url in urls:
            for metodo in (self.client.get, self.client.post):
                with self.subTest(url=url, metodo=metodo):
                    self.assertEqual(metodo(url).status_code, 404)

    def test_consolidacao_e_superuser_nao_escapam_do_host(self):
        token = _marca_host.set(self.marca)
        try:
            for usuario in (self.superuser, self.owner, self.viewer):
                self.assertEqual(list(empresas_permitidas(usuario)), [self.empresa])
                self.assertEqual(list(empresas_permitidas_no_grupo(usuario, self.empresa)), [self.empresa])
        finally:
            _marca_host.reset(token)
        self.assertEqual(empresas_permitidas(self.superuser).count(), 2)

    def test_administracao_global_e_outras_marcas_bloqueadas(self):
        self.client.force_login(self.superuser)
        urls = [reverse("admin:index"), reverse("empresas:configuracoes"), reverse("empresas:cadastrar"),
                reverse("empresas:white_label_novo"), reverse("empresas:trial"),
                reverse("empresas:white_label_editar", args=[self.outra.slug]),
                reverse("empresas:white_label_identidade", args=[self.outra.slug]),
                reverse("empresas:white_label_previa_login", args=[self.outra.slug])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        response = self.client.get(reverse("empresas:white_label"))
        self.assertContains(response, self.marca.nome)
        self.assertNotContains(response, self.outra.nome)

    def test_acesso_ao_host_nao_cria_permissao_no_cnpj(self):
        usuario = get_user_model().objects.create_user(username="sem-acesso-host")
        self.client.force_login(usuario)
        self.assertEqual(list(self.client.get("/").context["empresas"]), [])
        self.assertEqual(self.client.get(reverse("dashboards:home", args=[self.empresa.slug])).status_code, 404)
        self.assertFalse(EmpresaUsuario.objects.filter(usuario=usuario).exists())

    def test_logout_permanece_no_login_do_dominio(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("accounts:login"))
        self.assertEqual(self.client.get(reverse("accounts:login")).context["white_label_marca"], self.marca)

    def test_contexto_nao_vaza_para_request_seguinte_ou_worker(self):
        self.client.get(reverse("accounts:login"))
        response = Client(HTTP_HOST="app.elevdata.com.br").get(reverse("accounts:login"))
        self.assertFalse(response.context.get("white_label_tema", False))
        self.assertIsNone(marca_host_atual())
        self.assertEqual(empresas_permitidas(self.superuser).count(), 2)

    def test_apenas_superusuario_altera_dominio_inclusive_post_forjado(self):
        url = reverse("empresas:white_label_editar", args=[self.marca.slug])
        self.client.force_login(self.owner)
        response = self.client.post(url, self.dados(dominio="sequestro.example.com", dominio_ativo=""))
        self.assertEqual(response.status_code, 302)
        self.marca.refresh_from_db()
        self.assertEqual(self.marca.dominio, "app.revee.elevdata.com.br")
        self.assertTrue(self.marca.dominio_ativo)
        self.assertNotIn("dominio", AmbienteWhiteLabelForm(instance=self.marca, operador=self.owner).fields)

    def test_normalizacao_dominio_unico_e_multiplas_marcas_sem_dominio(self):
        self.assertEqual(normalizar_dominio(" APP.REVEE.ELEVDATA.COM.BR. "), self.marca.dominio)
        self.assertIsNone(normalizar_dominio(""))
        form = AmbienteWhiteLabelForm(self.dados(dominio="APP.REVEE.ELEVDATA.COM.BR"), operador=self.superuser)
        self.assertFalse(form.is_valid())
        self.assertIn("dominio", form.errors)
        for i in range(2):
            AmbienteWhiteLabel.objects.create(nome=f"Sem dominio {i}", slug=f"sem-dominio-{i}")

    def test_rejeita_urls_portas_ips_wildcards_e_dominio_principal(self):
        for valor in ("https://marca.example.com", "marca.example.com/login", "marca.example.com:443", "*.example.com",
                      "127.0.0.1", "app.elevdata.com.br", "marca..com", "-marca.example.com", "marca.example.com?x=1"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                normalizar_dominio(valor)
        form = AmbienteWhiteLabelForm(self.dados(dominio=""), instance=self.marca, operador=self.superuser)
        self.assertFalse(form.is_valid())
        self.assertIn("dominio", form.errors)

    def test_cadastro_so_consume_convites_da_marca_acessada(self):
        from apps.accounts.registration import cadastrar_pelo_sistema
        email = "novo-host@teste.com"
        convites = [PreCadastroUsuario.objects.create(empresa=empresa, email=email, nome="Novo", papel="viewer")
                    for empresa in (self.empresa, self.outra_empresa)]
        token = _marca_host.set(self.marca)
        try:
            usuario = cadastrar_pelo_sistema(email, "Novo", "Teste!Segura91827")
        finally:
            _marca_host.reset(token)
        self.assertEqual(list(usuario.vinculos_empresas.values_list("empresa_id", flat=True)), [self.empresa.pk])
        convites[1].refresh_from_db()
        self.assertIsNone(convites[1].utilizado_em)

    def test_convite_externo_nao_permite_cadastro_neste_host(self):
        email = "externo-host@teste.com"
        convite = PreCadastroUsuario.objects.create(empresa=self.outra_empresa, email=email, nome="Externo", papel="viewer")
        response = self.client.post(reverse("accounts:cadastro"), dict(email=email, first_name="Externo", password1="Teste!Segura91827", password2="Teste!Segura91827"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(email=email).exists())
        convite.refresh_from_db()
        self.assertIsNone(convite.utilizado_em)

    @patch("apps.accounts.views.send_mail")
    def test_recuperacao_de_senha_nao_envia_codigo_para_usuario_externo(self, enviar):
        user = get_user_model().objects.create_user(username="externo-reset", email="externo-reset@teste.com")
        EmpresaUsuario.objects.create(empresa=self.outra_empresa, usuario=user, papel="viewer")
        self.client.post(reverse("accounts:password_reset"), {"email": user.email})
        enviar.assert_not_called()

    def test_login_csrf_mesma_origem_permitido_e_outra_origem_bloqueada(self):
        client = Client(HTTP_HOST=self.marca.dominio, enforce_csrf_checks=True)
        client.get(reverse("accounts:login"), secure=True)
        token = client.cookies["csrftoken"].value
        data = {"username": "naoexiste@teste.com", "password": "senha", "csrfmiddlewaretoken": token}
        response = client.post(reverse("accounts:login"), data, secure=True, HTTP_ORIGIN=f"https://{self.marca.dominio}")
        self.assertEqual(response.status_code, 200)
        response = client.post(reverse("accounts:login"), data, secure=True, HTTP_ORIGIN="https://invasor.example.com")
        self.assertEqual(response.status_code, 403)

    def test_exportacao_streaming_tem_escopo_sem_vazar_entre_chunks(self):
        from .white_label_middleware import WhiteLabelDomainMiddleware
        def exportar():
            yield str(empresas_permitidas(self.superuser).count()).encode()
            yield str(empresas_permitidas(self.superuser).count()).encode()
        stream = WhiteLabelDomainMiddleware.conteudo_no_ambiente(exportar(), self.marca)
        self.assertEqual(next(stream), b"1")
        self.assertIsNone(marca_host_atual())
        self.assertEqual(next(stream), b"1")
        stream.close()
        self.assertIsNone(marca_host_atual())

    def test_contexto_reiniciado_apos_falha(self):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        from .white_label_middleware import WhiteLabelDomainMiddleware
        request = RequestFactory().get("/", HTTP_HOST=self.marca.dominio)
        SessionMiddleware(lambda r: None).process_request(request)
        def falhar(request):
            self.assertEqual(marca_host_atual(), self.marca)
            raise RuntimeError("Falha QA dominio")
        with self.assertRaises(RuntimeError):
            WhiteLabelDomainMiddleware(falhar)(request)
        self.assertIsNone(marca_host_atual())

    @override_settings(CADASTRO_EXIGIR_CONFIRMACAO_EMAIL=True)
    @patch("apps.accounts.registration.send_mail")
    def test_cadastro_email_futuro_nao_dispara_codigo_para_outra_marca(self, enviar):
        email = "convite-outra-marca@teste.com"
        PreCadastroUsuario.objects.create(empresa=self.outra_empresa, email=email, nome="Externo", papel="viewer")
        response = self.client.post(reverse("accounts:cadastro"), {"email": email, "first_name": "Externo"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        enviar.assert_not_called()

    def test_superusuario_salva_dominio_no_site_principal_com_auditoria(self):
        from .models import AcaoUsuarioLog
        client = Client(HTTP_HOST="app.elevdata.com.br")
        client.force_login(self.superuser)
        url = reverse("empresas:white_label_editar", args=[self.marca.slug])
        response = client.post(url, self.dados(dominio=" NOVO.REVEE.EXAMPLE.COM. "))
        self.assertEqual(response.status_code, 302)
        self.marca.refresh_from_db()
        self.assertEqual(self.marca.dominio, "novo.revee.example.com")
        self.assertTrue(AcaoUsuarioLog.objects.filter(dados__ambiente_id=self.marca.pk, dados__dominio=self.marca.dominio).exists())

    def test_admin_de_outra_marca_nao_ganha_acesso_a_cnpj_compartilhado(self):
        usuario = get_user_model().objects.create_user(username="somente-admin-externo")
        self.outra.administradores.add(usuario)
        self.outra.empresas.add(self.empresa)
        self.client.force_login(usuario)
        self.assertEqual(list(self.client.get("/").context["empresas"]), [])
        self.assertEqual(self.client.get(reverse("dashboards:home", args=[self.empresa.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("empresas:white_label_editar", args=[self.marca.slug])).status_code, 404)
