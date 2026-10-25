import io
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.empresas.models import CadastroOmie, CategoriaOmie, DepartamentoOmie, Empresa, EmpresaUsuario, ContaPagarOmie, ContaCorrenteOmie
from .contas_pagar_forms import ContaPagarLocalForm, MAX_ANEXO_BYTES
from .contas_pagar_storage import armazenamento_contas_pagar
from .models import AnexoContaPagarLocal, ContaPagarLocal


class ContasPagarLocaisTests(TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory(prefix="west-anexos-teste-")
        self.addCleanup(self.pasta.cleanup)
        settings = override_settings(PRIVATE_FILES_ROOT=Path(self.pasta.name))
        settings.enable()
        self.addCleanup(settings.disable)
        storage = patch.object(AnexoContaPagarLocal._meta.get_field("arquivo"), "storage", armazenamento_contas_pagar())
        storage.start()
        self.addCleanup(storage.stop)
        self.empresa = Empresa.objects.create(nome="Conta local", cnpj="00.000.000/0001-65")
        self.outra = Empresa.objects.create(nome="Outra local", cnpj="00.000.000/0001-66")
        self.usuario = get_user_model().objects.create_user(username="cadastro-local")
        self.vinculo = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario, papel="gestor")
        self.fornecedor = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=11, nome_fantasia="Fornecedor Local", tipo="fornecedor")
        self.categoria = CategoriaOmie.objects.create(empresa=self.empresa, codigo="2.01.01", descricao="Materiais", conta_despesa=True)
        self.departamento = DepartamentoOmie.objects.create(empresa=self.empresa, codigo="DEP1", descricao="Administracao")
        self.banco = ContaCorrenteOmie.objects.create(empresa=self.empresa, codigo_omie=91, descricao="Banco cadastro local")
        self.url = reverse("dashboards:cadastrar_conta_pagar_local", args=[self.empresa.slug])
        self.lista = reverse("dashboards:listar_contas_pagar_locais", args=[self.empresa.slug])
        self.client.force_login(self.usuario)

    def dados(self, **extra):
        dados = {"fornecedor": self.fornecedor.pk, "categoria": self.categoria.pk, "departamento": self.departamento.pk,
                 "descricao": "Compra de material", "valor": "1.234,56", "data_emissao": "2026-10-20",
                 "data_vencimento": "2026-10-30", "forma_pagamento": "pix", "documento": "NF 12345",
                 "observacoes": "Observacao local", "token": str(uuid.uuid4()), "conta_corrente": self.banco.pk}
        dados.update(extra)
        return dados

    def pdf(self, nome="NF.pdf"):
        return SimpleUploadedFile(nome, b"%PDF-1.4\n%%EOF", content_type="application/pdf")

    def anexo_url(self, anexo, empresa=None):
        return reverse("dashboards:baixar_anexo_conta_local", args=[(empresa or self.empresa).slug, anexo.pk])

    def test_salva_rascunho_com_valor_br_sem_chamar_omie(self):
        with patch("apps.empresas.omie.urlopen", side_effect=AssertionError("Sem API")):
            response = self.client.post(self.url, self.dados())
        self.assertEqual(response.status_code, 200)
        conta = ContaPagarLocal.objects.get()
        self.assertEqual(str(conta.valor), "1234.56")
        self.assertEqual(conta.empresa, self.empresa)
        self.assertEqual(conta.criado_por, self.usuario)
        self.assertFalse(ContaPagarOmie.objects.exists())
        self.assertTrue(response.json()["sucesso"])

    def test_retry_mesmo_token_nao_duplica_conta_nem_anexos(self):
        dados = self.dados()
        dados["anexos"] = self.pdf()
        response = self.client.post(self.url, dados)
        dados["anexos"] = self.pdf()
        segunda = self.client.post(self.url, dados)
        self.assertEqual(response.json()["id"], segunda.json()["id"])
        self.assertEqual(ContaPagarLocal.objects.count(), 1)
        self.assertEqual(AnexoContaPagarLocal.objects.count(), 1)

    def test_aceita_um_centavo_e_valores_decimais_sem_formatacao(self):
        for valor in ["0,01", "0.01", "1234.56", "R$ 1.234,56", "1.234"]:
            with self.subTest(valor=valor):
                form = ContaPagarLocalForm(self.dados(valor=valor), empresa=self.empresa)
                self.assertTrue(form.is_valid(), form.errors)

    def test_seletor_fornecedor_em_janela_separada_com_validacao_servidor(self):
        html = self.client.get(self.url).json()["html"]
        self.assertIn("data-local-supplier-open", html)
        self.assertNotIn("data-local-supplier-search", html)
        form = ContaPagarLocalForm(self.dados(fornecedor=""), empresa=self.empresa)
        self.assertFalse(form.fields["fornecedor"].widget.use_required_attribute(None))
        self.assertFalse(form.is_valid())
        self.assertIn("fornecedor", form.errors)

    def test_busca_inclui_nome_razao_social_e_cnpj_sem_html_executavel(self):
        self.fornecedor.razao_social = "Comercio <script>alert(1)</script>"
        self.fornecedor.cnpj_cpf = "11.222.333/0001-81"
        self.fornecedor.save()
        html = self.client.get(self.url).json()["html"]
        self.assertIn("Fornecedor Local", html)
        self.assertIn("11.222.333/0001-81", html)
        self.assertIn("Comercio &lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_centro_categoria_fornecedor_sao_da_empresa(self):
        outros = {
            "fornecedor": CadastroOmie.objects.create(empresa=self.outra, codigo_cliente_omie=11, tipo="fornecedor").pk,
            "categoria": CategoriaOmie.objects.create(empresa=self.outra, codigo="2.01.01", conta_despesa=True).pk,
            "departamento": DepartamentoOmie.objects.create(empresa=self.outra, codigo="DEP1", descricao="Outro").pk,
        }
        for campo, valor in outros.items():
            with self.subTest(campo=campo):
                self.assertEqual(self.client.post(self.url, self.dados(**{campo: valor})).status_code, 400)
        self.assertFalse(ContaPagarLocal.objects.exists())

    def test_inativos_nao_sao_aceitos(self):
        self.fornecedor.inativo = True
        self.fornecedor.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 400)
        self.fornecedor.inativo = False
        self.fornecedor.save()
        self.categoria.conta_inativa = True
        self.categoria.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 400)

    def test_categoria_receita_e_totalizadora_nao_sao_aceitas(self):
        self.categoria.conta_despesa = False
        self.categoria.conta_receita = True
        self.categoria.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 400)
        self.categoria.conta_despesa = True
        self.categoria.totalizadora = True
        self.categoria.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 400)

    def test_validacao_valor_datas_e_campos_obrigatorios(self):
        for extra in [{"valor": "0"}, {"valor": "-10"}, {"valor": "abc"}, {"valor": "1,2,3"}, {"data_vencimento": "2026-10-19"}, {"data_emissao": "invalida"}, {"forma_pagamento": "invalida"}, {"descricao": ""}, {"departamento": ""}, {"observacoes": "a" * 5001}]:
            with self.subTest(extra=str(extra)[:70]):
                self.assertEqual(self.client.post(self.url, self.dados(**extra)).status_code, 400)
        self.assertFalse(ContaPagarLocal.objects.exists())

    def test_viewer_pode_cadastrar_e_listar_apenas_suas_contas(self):
        self.vinculo.papel = "viewer"
        self.vinculo.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 200)
        self.assertEqual(self.client.get(self.lista).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_permissao_dashboard_tambem_obrigatoria(self):
        self.vinculo.areas_permitidas = ["compras"]
        self.vinculo.save()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 403)

    def test_outra_empresa_nao_pode_ser_acessada(self):
        url = reverse("dashboards:cadastrar_conta_pagar_local", args=[self.outra.slug])
        self.assertEqual(self.client.post(url, self.dados()).status_code, 404)
        self.assertFalse(ContaPagarLocal.objects.exists())

    def test_login_e_csrf_obrigatorios(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.usuario)
        self.assertEqual(csrf.post(self.url, self.dados()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, self.dados()).status_code, 302)

    def test_upload_privado_download_autorizado_e_sem_url_publica(self):
        self.client.post(self.url, self.dados(anexos=self.pdf()))
        anexo = AnexoContaPagarLocal.objects.get()
        self.assertTrue(Path(anexo.arquivo.path).is_file())
        self.assertTrue(Path(anexo.arquivo.path).is_relative_to(self.pasta.name))
        self.assertNotIn("NF.pdf", anexo.arquivo.name)
        with self.assertRaises(ValueError):
            _ = anexo.arquivo.url
        response = self.client.get(self.anexo_url(anexo))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        # Close the download without closing the connection of this TestCase's transaction.
        with patch("django.core.signals.request_finished.send"):
            response.close()
        self.vinculo.papel = "viewer"
        self.vinculo.save()
        response = self.client.get(self.anexo_url(anexo))
        self.assertEqual(response.status_code, 200)
        with patch("django.core.signals.request_finished.send"):
            response.close()

    def test_download_nao_cruza_empresa(self):
        self.client.post(self.url, self.dados(anexos=self.pdf()))
        anexo = AnexoContaPagarLocal.objects.get()
        EmpresaUsuario.objects.create(empresa=self.outra, usuario=self.usuario, papel="gestor")
        self.assertEqual(self.client.get(self.anexo_url(anexo, self.outra)).status_code, 404)

    def test_arquivo_disfarcado_ou_extensao_invalida_rejeitados(self):
        for arquivo in [SimpleUploadedFile("x.html", b"<script>alert(1)</script>"), SimpleUploadedFile("x.pdf", b"nao e pdf"), SimpleUploadedFile("x.png", b"nao e imagem")]:
            self.assertEqual(self.client.post(self.url, self.dados(anexos=arquivo)).status_code, 400)
        self.assertFalse(AnexoContaPagarLocal.objects.exists())

    def test_imagem_valida_aceita(self):
        imagem = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(imagem, format="PNG")
        arquivo = SimpleUploadedFile("comprovante.png", imagem.getvalue(), content_type="image/png")
        self.assertEqual(self.client.post(self.url, self.dados(anexos=arquivo)).status_code, 200)

    def test_limites_de_anexos_no_servidor(self):
        arquivos = [self.pdf(f"{i}.pdf") for i in range(6)]
        self.assertEqual(self.client.post(self.url, self.dados(anexos=arquivos)).status_code, 400)
        grande = self.pdf()
        grande.size = MAX_ANEXO_BYTES + 1
        form = ContaPagarLocalForm(self.dados(), empresa=self.empresa, arquivos=[grande])
        self.assertFalse(form.is_valid())
        arquivos = [self.pdf(f"{i}.pdf") for i in range(3)]
        for arquivo in arquivos:
            arquivo.size = 9 * 1024 * 1024
        self.assertFalse(ContaPagarLocalForm(self.dados(), empresa=self.empresa, arquivos=arquivos).is_valid())

    def test_falha_storage_nao_deixa_conta_incompleta(self):
        with patch.object(AnexoContaPagarLocal._meta.get_field("arquivo").storage, "save", side_effect=OSError("Disco indisponivel")):
            response = self.client.post(self.url, self.dados(anexos=self.pdf()))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(ContaPagarLocal.objects.exists())
        self.assertFalse(AnexoContaPagarLocal.objects.exists())

    def test_falha_no_segundo_anexo_remove_arquivo_ja_gravado(self):
        storage = AnexoContaPagarLocal._meta.get_field("arquivo").storage
        salvar = storage.save
        chamadas = 0

        def falhar_segundo(*args, **kwargs):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 2:
                raise OSError("Disco indisponivel")
            return salvar(*args, **kwargs)

        with patch.object(storage, "save", side_effect=falhar_segundo):
            response = self.client.post(self.url, self.dados(anexos=[self.pdf("1.pdf"), self.pdf("2.pdf")]))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(ContaPagarLocal.objects.exists())
        self.assertFalse(AnexoContaPagarLocal.objects.exists())
        self.assertFalse(any(p.is_file() for p in Path(self.pasta.name).rglob("*")))

    def test_token_de_outro_usuario_nao_pode_ser_reutilizado(self):
        dados = self.dados()
        self.client.post(self.url, dados)
        outro = get_user_model().objects.create_user(username="outro-gestor-local")
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=outro, papel="gestor")
        self.client.force_login(outro)
        self.assertEqual(self.client.post(self.url, dados).status_code, 403)
        self.assertEqual(ContaPagarLocal.objects.count(), 1)

    def test_lista_local_nao_altera_totais_e_escapa_html(self):
        descricao = "<script>alert(1)</script>"
        self.client.post(self.url, self.dados(descricao=descricao))
        html = self.client.get(self.lista).json()["html"]
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn(descricao, html)
        self.assertEqual(self.client.get(self.lista)["Cache-Control"], "private, no-store")
        self.assertFalse(ContaPagarOmie.objects.exists())

    def test_botoes_apenas_pagar_incluindo_visualizador(self):
        pagar = reverse("dashboards:dashboard", args=[self.empresa.slug, "financeiro", "contas-a-pagar"])
        receber = reverse("dashboards:dashboard", args=[self.empresa.slug, "financeiro", "contas-a-receber"])
        self.assertContains(self.client.get(pagar), "Nova conta a pagar")
        self.assertNotContains(self.client.get(receber), "data-local-create")
        self.vinculo.papel = "viewer"
        self.vinculo.save()
        self.assertContains(self.client.get(pagar), "data-local-create")
