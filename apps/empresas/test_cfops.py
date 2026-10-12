from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .cfops import CFOPS_VENDA_PADRAO
from .models import CfopVendaOmie, Empresa, NfeSaidaItemOmie, NfeSaidaOmie


class ClassificacaoCfopTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="CFOP", cnpj="00.000.000/0001-81")
        self.outra = Empresa.objects.create(nome="Outra CFOP", cnpj="00.000.000/0001-82")
        self.admin = get_user_model().objects.create_user(username="admin_cfop", is_staff=True)
        self.client.force_login(self.admin)
        self.url = reverse("dashboards:classificacoes", kwargs={"empresa_slug": self.empresa.slug})

    def test_lista_pre_preenchida_por_empresa_sem_remessas(self):
        esperado = set("""
            5101 5102 5103 5104 5105 5106 5109 5110 5111 5112 5113 5114
            5115 5116 5117 5118 5119 5120 5122 5123 5401 5402 5403 5405
            5651 5652 5653 5654 5655 5656
            6101 6102 6103 6104 6105 6106 6107 6108 6109 6110 6111 6112
            6113 6114 6115 6116 6117 6118 6119 6120 6122 6123 6401 6402 6403 6404
            6651 6652 6653 6654 6655 6656
        """.split())
        self.assertEqual(set(self.empresa.cfops_venda_omie.values_list("codigo", flat=True)), esperado)
        self.assertEqual(len(CFOPS_VENDA_PADRAO), 62)
        self.assertFalse(self.empresa.cfops_venda_omie.filter(codigo="5901").exists())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5.102")
        response = self.client.get(reverse("dashboards:parametros", kwargs={"empresa_slug": self.empresa.slug}))
        self.assertContains(response, self.url)

    def test_cria_edita_valida_e_normaliza_codigo(self):
        response = self.client.post(self.url, {"codigo": "5.124", "descricao": "Operacao adicional", "ativo": "on"})
        self.assertEqual(response.status_code, 302)
        cfop = self.empresa.cfops_venda_omie.get(codigo="5124")
        response = self.client.post(self.url, {"cfop_id": cfop.pk, "codigo": "5124", "descricao": "Alterado"})
        self.assertEqual(response.status_code, 302)
        cfop.refresh_from_db()
        self.assertEqual(cfop.descricao, "Alterado")
        self.assertFalse(cfop.ativo)
        for codigo in ("5.124", "1102", "abc", "59010"):
            with self.subTest(codigo=codigo):
                response = self.client.post(self.url, {"codigo": codigo, "descricao": "Invalido", "ativo": "on"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)

    def test_excluir_nao_recria_padrao_ao_reabrir(self):
        cfop = self.empresa.cfops_venda_omie.get(codigo="5102")
        self.client.post(self.url, {"acao": "excluir", "cfop_id": cfop.pk})
        self.client.get(self.url)
        self.assertFalse(self.empresa.cfops_venda_omie.filter(codigo="5102").exists())
        self.assertTrue(self.outra.cfops_venda_omie.filter(codigo="5102").exists())

    def test_permissao_e_isolamento_em_todas_as_mutacoes(self):
        cfop = self.outra.cfops_venda_omie.get(codigo="5102")
        for acao in ("excluir", "alternar", "salvar"):
            response = self.client.post(self.url, {
                "acao": acao, "cfop_id": cfop.pk, "codigo": "5103", "descricao": "Nao autorizado",
            })
            self.assertEqual(response.status_code, 404)
        usuario = get_user_model().objects.create_user(username="cfop_sem_acesso")
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"codigo": "5103"}).status_code, 403)

    def _nota(self, empresa, codigo, cfops, **kwargs):
        nota = NfeSaidaOmie.objects.create(empresa=empresa, codigo_nf=codigo, valor_total=1000, **kwargs)
        for sequencia, cfop in enumerate(cfops, start=1):
            NfeSaidaItemOmie.objects.create(
                empresa=empresa, nota=nota, sequencia=sequencia, cfop=cfop,
                valor_total=100 if sequencia == 1 else 900,
            )
        return nota

    def test_nota_mista_considera_apenas_itens_de_venda(self):
        nota = self._nota(self.empresa, 1, ["5.102", "5901"])
        self._nota(self.empresa, 2, ["5901"])
        self.assertEqual(self.empresa.nfes_saida_omie.vendas().count(), 1)
        self.assertEqual(self.empresa.itens_nfe_saida_omie.vendas().count(), 1)
        classificada = self.empresa.nfes_saida_omie.vendas().get(pk=nota.pk)
        self.assertEqual(classificada.valor_venda, Decimal("100"))
        self.assertEqual(classificada.valor_total, Decimal("1000"))

    def test_alterar_cfop_reclassifica_sem_sincronizar_e_sem_afetar_outra_empresa(self):
        self._nota(self.empresa, 1, ["5102"])
        self._nota(self.outra, 1, ["5102"])
        cfop = self.empresa.cfops_venda_omie.get(codigo="5102")
        self.client.post(self.url, {"acao": "alternar", "cfop_id": cfop.pk})
        self.assertEqual(self.empresa.nfes_saida_omie.vendas().count(), 0)
        self.assertEqual(self.outra.nfes_saida_omie.vendas().count(), 1)
        self.client.post(self.url, {"acao": "alternar", "cfop_id": cfop.pk, "ativo": "on"})
        self.assertEqual(self.empresa.nfes_saida_omie.vendas().count(), 1)

    def test_exclui_canceladas_inutilizadas_denegadas_e_inativas(self):
        for codigo, flags in enumerate((
            {"data_cancelamento": "2026-10-12"}, {"data_inutilizacao": "2026-10-12"},
            {"denegada": True}, {"ativo_omie": False},
        ), start=1):
            self._nota(self.empresa, codigo, ["5102"], **flags)
        nota = self._nota(self.empresa, 5, ["5102"])
        nota.itens.update(ativo_omie=False)
        self.assertEqual(self.empresa.nfes_saida_omie.vendas().count(), 0)
        self.assertEqual(self.empresa.itens_nfe_saida_omie.vendas().count(), 0)
