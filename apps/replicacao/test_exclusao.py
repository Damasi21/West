from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.empresas.models import Empresa, CategoriaOmie, AcaoUsuarioLog, AmbienteWhiteLabel
from apps.empresas.omie import _salvar_categorias
from . import tests as fixtures
from .models import PlanoReplicacao, DestinoReplicacao, ComparacaoReplicacao, CadastroCategoria, VinculoCategoria
from .services import excluir_configuracao


class ExcluirConfiguracaoTests(TestCase):
    def setUp(self):
        fixtures.ReplicacaoTests.setUp(self)

    def test_exclui_apenas_configuracao_vazia_e_destinos_registrando_auditoria(self):
        pk, nome = self.plano.pk, self.plano.nome
        excluir_configuracao(self.plano, self.gestor)
        self.assertFalse(PlanoReplicacao.objects.filter(pk=pk).exists())
        self.assertFalse(DestinoReplicacao.objects.filter(plano_id=pk).exists())
        self.assertTrue(Empresa.objects.filter(pk=self.matriz.pk).exists())
        self.assertTrue(Empresa.objects.filter(pk=self.destino.pk).exists())
        log = AcaoUsuarioLog.objects.get(descricao="Excluiu configuração de replicação sem solicitações")
        self.assertEqual(log.dados["plano_replicacao"], pk)
        self.assertEqual(log.dados["nome"], nome)
        self.assertEqual(self.api.escritas, [])

    def test_bloqueia_qualquer_solicitacao_independente_de_status_e_modo(self):
        for status in ["fila", "comparando", "pronta", "enviando", "concluida", "erro"]:
            with self.subTest(comparacao=status):
                comp = ComparacaoReplicacao.objects.create(plano=self.plano, solicitado_por=self.superuser, status=status)
                with self.assertRaises(ValidationError): excluir_configuracao(self.plano, self.superuser)
                comp.delete()
        for modo in ["cadastro", "catalogo"]:
            for status in ["fila", "consultando", "revisao", "enviando", "concluido", "erro"]:
                with self.subTest(modo=modo, status=status):
                    op = CadastroCategoria.objects.create(plano=self.plano, solicitado_por=self.superuser, modo=modo, status=status)
                    with self.assertRaises(ValidationError): excluir_configuracao(self.plano, self.superuser)
                    op.delete()
        self.assertTrue(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())
        self.assertEqual(self.api.escritas, [])

    def test_vinculos_sem_solicitacao_tambem_sao_preservados(self):
        _salvar_categorias(self.matriz, self.api.catalogos[self.matriz.pk])
        _salvar_categorias(self.destino, self.api.catalogos[self.destino.pk])
        VinculoCategoria.objects.create(destino=self.alvo, origem=CategoriaOmie.objects.get(empresa=self.matriz, codigo="2.01"), categoria=CategoriaOmie.objects.get(empresa=self.destino, codigo="2.08"), confirmado_por=self.superuser)
        with self.assertRaises(ValidationError): excluir_configuracao(self.plano, self.superuser)
        self.assertTrue(VinculoCategoria.objects.exists())

    def test_permite_excluir_pausada_e_rejeita_lider_ou_visualizador(self):
        self.plano.ativo = False
        self.plano.save()
        for usuario in [self.lider, self.viewer]:
            with self.assertRaises(PermissionDenied): excluir_configuracao(self.plano, usuario)
        excluir_configuracao(self.plano, self.superuser)
        self.assertFalse(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())

    def test_botao_confirmacao_e_protecao_de_solicitacao_criada_apos_abrir_tela(self):
        self.client.force_login(self.superuser)
        url = reverse("replicacao:excluir", args=[self.plano.pk])
        self.assertContains(self.client.get(reverse("replicacao:lista")), url)
        self.assertContains(self.client.get(url), "Confirmo a exclusão")
        self.assertTrue(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())
        self.client.post(url, {})
        self.assertTrue(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())
        CadastroCategoria.objects.create(plano=self.plano, solicitado_por=self.superuser, status="erro")
        response = self.client.post(url, {"confirmar": "sim"}, follow=True)
        self.assertContains(response, "não pode ser excluída")
        self.assertTrue(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())
        self.assertNotContains(self.client.get(reverse("replicacao:lista")), url)

    def test_exclusao_post_confirmado_e_csrf_obrigatorio(self):
        url = reverse("replicacao:excluir", args=[self.plano.pk])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post(url, {"confirmar":"sim"}).status_code, 403)
        self.client.force_login(self.gestor)
        self.assertRedirects(self.client.post(url, {"confirmar":"sim"}), reverse("replicacao:lista"))
        self.assertFalse(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())

    @override_settings(ALLOWED_HOSTS=["testserver", "excluir.example.com"])
    def test_isolamento_white_label(self):
        marca = AmbienteWhiteLabel.objects.create(nome="Marca Exclusão", slug="marca-exclusao", dominio="excluir.example.com", dominio_ativo=True)
        marca.empresas.add(self.matriz, self.destino)
        self.plano.marca = marca
        self.plano.save()
        url = reverse("replicacao:excluir", args=[self.plano.pk])
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.post(url, {"confirmar":"sim"}).status_code, 404)
        self.assertEqual(self.client.get(url, HTTP_HOST="excluir.example.com").status_code, 200)
        self.client.post(url, {"confirmar":"sim"}, HTTP_HOST="excluir.example.com")
        self.assertFalse(PlanoReplicacao.objects.filter(pk=self.plano.pk).exists())
