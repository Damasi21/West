import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import AmbienteWhiteLabel, Empresa, EmpresaUsuario
from .white_label_branding import SESSION_MARCA, contexto_identidade, texto_contraste
from .white_label_identity_forms import IdentidadeWhiteLabelForm


class IdentidadeWhiteLabelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.TemporaryDirectory(prefix="west-identidade-test-")
        cls.override = override_settings(MEDIA_ROOT=cls.media.name)
        cls.override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.override.disable()
        cls.media.cleanup()
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_user(username="super-visual", is_superuser=True, is_staff=True)
        self.owner = User.objects.create_user(username="owner-visual", email="owner@example.com")
        self.outro = User.objects.create_user(username="outro-visual")
        self.gestor = User.objects.create_user(username="gestor-visual")
        self.lider = User.objects.create_user(username="lider-visual")
        self.viewer = User.objects.create_user(username="viewer-visual")
        self.empresa = Empresa.objects.create(nome="Empresa Visual", nome_fantasia="Empresa Visual", cnpj="11222333000111")
        self.outra_empresa = Empresa.objects.create(nome="Empresa Outra Visual", nome_fantasia="Empresa Outra Visual", cnpj="11222333000122")
        self.marca = AmbienteWhiteLabel.objects.create(nome="Marca Visual", slug="marca-visual")
        self.marca.empresas.add(self.empresa)
        self.marca.administradores.add(self.owner)
        self.outra = AmbienteWhiteLabel.objects.create(nome="Outra Marca Visual", slug="outra-marca-visual")
        self.outra.administradores.add(self.outro)
        self.outra.empresas.add(self.outra_empresa)
        for usuario,papel in [(self.gestor,"gestor"),(self.lider,"lider"),(self.viewer,"viewer")]:
            EmpresaUsuario.objects.create(empresa=self.empresa, usuario=usuario, papel=papel)
        self.url = reverse("empresas:white_label_identidade", args=[self.marca.slug])
        self.previa = reverse("empresas:white_label_previa_login", args=[self.marca.slug])
        self.login = reverse("accounts:login_marca", args=[self.marca.slug])

    def dados(self, **extra):
        dados = dict(layout_login="classico", cor_primaria="#742183", cor_secundaria="#214fac", cor_destaque="#e5a738", cor_fundo="#eff3f8")
        dados.update(extra)
        return dados

    def imagem(self, nome="logo.png", formato="PNG", size=(160,60)):
        arquivo = BytesIO()
        Image.new("RGB", size, "#742183").save(arquivo, format=formato)
        return SimpleUploadedFile(nome, arquivo.getvalue(), content_type="image/png" if formato=="PNG" else "image/jpeg")

    def salvar(self, usuario=None, **extra):
        self.client.force_login(usuario or self.owner)
        return self.client.post(self.url, self.dados(**extra))

    def test_super_e_adm_editam_identidade_somente_do_ambiente_autorizado(self):
        for usuario in (self.superuser,self.owner):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url).status_code,200)
            self.assertEqual(self.client.get(self.previa).status_code,200)
        for usuario in (self.outro,self.gestor,self.lider,self.viewer):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url).status_code,404)
            self.assertEqual(self.client.post(self.url,self.dados()).status_code,404)
            self.assertEqual(self.client.get(self.previa).status_code,404)

    def test_campos_fora_da_identidade_nao_alteram_empresa_ou_responsavel(self):
        self.assertRedirects(self.salvar(nome="Invadida", slug="invadida", administradores=[self.outro.pk], empresas=[self.outra_empresa.pk], ativa=""),self.url)
        self.marca.refresh_from_db()
        self.assertEqual(self.marca.nome,"Marca Visual")
        self.assertTrue(self.marca.ativa)
        self.assertEqual(list(self.marca.administradores.all()),[self.owner])
        self.assertEqual(list(self.marca.empresas.all()),[self.empresa])

    def test_classico_tres_cores_aurora_quatro_cores(self):
        self.assertRedirects(self.salvar(cor_fundo=""),self.url)
        self.marca.refresh_from_db()
        self.assertTrue(self.marca.identidade_personalizada)
        self.assertEqual(self.marca.cor_primaria,"#742183")
        self.assertEqual(contexto_identidade(self.marca)["wl_fundo"],"#f7f2f8")
        response=self.salvar(layout_login="aurora",cor_fundo="#111827")
        self.assertRedirects(response,self.url)
        self.marca.refresh_from_db()
        self.assertEqual(contexto_identidade(self.marca)["wl_fundo"],"#111827")
        self.assertEqual(contexto_identidade(self.marca)["wl_texto_fundo"],"#ffffff")

    def test_rejeita_cor_css_injetada_layout_invalido_e_quarta_cor_ausente(self):
        for extra in [dict(cor_primaria="red;}</style><script>alert(1)</script>"),dict(cor_secundaria="red"),dict(cor_destaque="#12345g"),dict(layout_login="invalido"),dict(layout_login="aurora",cor_fundo="")]:
            response=self.salvar(**extra)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context["form"].errors)
        self.marca.refresh_from_db()
        self.assertFalse(self.marca.identidade_personalizada)

    def test_logos_separados_normalizados_e_nomes_seguros(self):
        self.assertRedirects(self.salvar(logo_login=self.imagem("../../login.jpg","JPEG"),logo_navbar=self.imagem("navbar.png")),self.url)
        self.marca.refresh_from_db()
        self.assertNotEqual(self.marca.logo_login.name,self.marca.logo_navbar.name)
        for arquivo in (self.marca.logo_login,self.marca.logo_navbar):
            self.assertTrue(arquivo.name.startswith(f"white_label/{self.marca.pk}/"))
            self.assertTrue(arquivo.name.endswith(".png"))
            with Image.open(arquivo.path) as img: self.assertEqual(img.format,"PNG")

    def test_logos_invalidos_grandes_e_dimensoes_excessivas(self):
        for arquivo in [SimpleUploadedFile("logo.svg",b'<svg onload="alert(1)"></svg>',content_type="image/svg+xml"),SimpleUploadedFile("fake.png",b"nao sou imagem",content_type="image/png"),self.imagem(size=(4097,1))]:
            response=self.salvar(logo_login=arquivo)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context["form"].errors)
        arquivo=self.imagem()
        arquivo.size=3*1024*1024+1
        form=IdentidadeWhiteLabelForm(self.dados(),{"logo_login":arquivo},instance=self.marca)
        self.assertFalse(form.is_valid())

    def test_limpar_um_logo_nao_remove_outro(self):
        self.salvar(logo_login=self.imagem(),logo_navbar=self.imagem())
        self.marca.refresh_from_db()
        navbar=self.marca.logo_navbar.name
        self.assertRedirects(self.salvar(**{"logo_login-clear":"on"}),self.url)
        self.marca.refresh_from_db()
        self.assertFalse(self.marca.logo_login)
        self.assertEqual(self.marca.logo_navbar.name,navbar)

    def test_tema_no_bi_somente_empresa_da_marca(self):
        self.salvar()
        self.client.force_login(self.superuser)
        response=self.client.get(reverse("dashboards:home",args=[self.empresa.slug]))
        self.assertContains(response,"white-label-themed")
        self.assertContains(response,"#742183")
        self.assertContains(response,"Marca Visual")
        response=self.client.get(reverse("dashboards:home",args=[self.outra_empresa.slug]))
        self.assertNotContains(response,"white-label-themed")
        self.assertNotContains(response,"#742183")

    def test_duas_marcas_no_mesmo_cnpj_exigem_escolha_explicita(self):
        self.salvar()
        self.outra.identidade_personalizada=True
        self.outra.empresas.add(self.empresa)
        self.outra.save()
        self.client.force_login(self.superuser)
        url=reverse("dashboards:home",args=[self.empresa.slug])
        self.assertNotContains(self.client.get(url),"white-label-themed")
        session=self.client.session
        session[SESSION_MARCA]=self.marca.pk
        session.save()
        self.assertContains(self.client.get(url),"#742183")

    def test_link_publico_login_tema_e_sessao_sem_conceder_acessos(self):
        self.salvar()
        self.client.logout()
        response=self.client.get(self.login)
        self.assertContains(response,"Marca Visual")
        self.assertContains(response,"#742183")
        self.assertEqual(self.client.session[SESSION_MARCA],self.marca.pk)
        self.client.force_login(self.outro)
        response=self.client.get(reverse("empresas:lista"))
        self.assertEqual(list(response.context["empresas"]),[])

    def test_previa_nao_altera_sessao_ou_persiste_escolhas(self):
        self.client.force_login(self.owner)
        response=self.client.get(self.previa)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["X-Frame-Options"],"SAMEORIGIN")
        self.assertContains(response,'type="submit" disabled')
        self.assertNotIn(SESSION_MARCA,self.client.session)
        self.marca.refresh_from_db()
        self.assertFalse(self.marca.identidade_personalizada)
        self.assertEqual(self.client.post(self.previa,{}).status_code,405)

    def test_marca_inativa_sem_login_publico(self):
        self.marca.ativa=False
        self.marca.save()
        self.assertEqual(self.client.get(self.login).status_code,404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code,404)

    def test_logout_retorna_login_da_marca(self):
        self.client.get(self.login)
        self.client.force_login(self.owner)
        response=self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response,self.login)

    def test_nome_de_marca_e_escapado_e_cor_legada_invalida_tem_fallback(self):
        self.marca.nome='<script>alert("marca")</script>'
        self.marca.cor_primaria='badcss'
        self.marca.save()
        response=self.client.get(self.login)
        self.assertNotContains(response,'<script>alert(')
        self.assertContains(response,'&lt;script&gt;')
        self.assertContains(response,'#217ed4')
        self.assertEqual(texto_contraste("#ffffff"),"#111827")
        self.assertEqual(texto_contraste("#000000"),"#ffffff")

    def test_login_geral_permanece_padrao_e_previa_nao_contamina_o_tema(self):
        self.salvar()
        self.client.get(self.previa)
        self.client.logout()
        response=self.client.get(reverse("accounts:login"))
        self.assertNotContains(response,"white-label-themed")
        self.assertNotContains(response,"Marca Visual")

    def test_sessao_da_marca_nao_aplica_logo_em_empresa_alheia(self):
        self.salvar()
        session=self.client.session
        session[SESSION_MARCA]=self.marca.pk
        session.save()
        self.client.force_login(self.superuser)
        response=self.client.get(reverse("dashboards:home",args=[self.outra_empresa.slug]))
        self.assertNotContains(response,"#742183")
        self.assertNotContains(response,"white-label-themed")

    def test_editor_exige_csrf(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url,self.dados()).status_code,403)

    def test_logo_png_preserva_transparencia(self):
        arquivo=BytesIO()
        Image.new("RGBA",(30,20),(0,0,0,0)).save(arquivo,format="PNG")
        response=self.salvar(logo_login=SimpleUploadedFile("sem-fundo.png",arquivo.getvalue(),content_type="image/png"))
        self.assertRedirects(response,self.url)
        self.marca.refresh_from_db()
        with Image.open(self.marca.logo_login.path) as imagem:
            self.assertEqual(imagem.getpixel((0,0))[3],0)
