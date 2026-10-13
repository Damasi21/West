from datetime import date

from django.test import TestCase

from apps.empresas.models import Empresa, PosicaoEstoqueOmie, ProdutoOmie, RecebimentoNfeItemOmie, RecebimentoNfeOmie
from .analise_preco_saving_services import analise_preco_saving_compras


class PrecoSavingTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Preco Saving", cnpj="00.000.000/0001-93")

    def _item(self, empresa=None, codigo=1, preco=80, familia="Familia A"):
        empresa = empresa or self.empresa
        produto = ProdutoOmie.objects.create(empresa=empresa, codigo_produto=codigo,
                                             codigo="PRD001", descricao="Produto", descricao_familia=familia)
        recebimento = RecebimentoNfeOmie.objects.create(empresa=empresa, codigo_recebimento=codigo,
                                                       etapa="60", data_emissao_nfe=date(2026, 8, 5))
        item = RecebimentoNfeItemOmie.objects.create(
            empresa=empresa, recebimento=recebimento, codigo_recebimento=codigo, sequencia=1,
            codigo_produto_texto="PRD001", descricao="Produto", data_recebimento=date(2026, 10, 13),
            quantidade_nfe=10, preco_unitario=preco, valor_total_item=preco * 10,
        )
        return produto, item

    def _dados(self, empresas=None, periodo="ano-2026"):
        return analise_preco_saving_compras(self.empresa, periodo, None, None, empresas or [self.empresa.pk], [])

    def test_sem_estoque_mostra_produto_preco_e_motivo_sem_inventar_saving(self):
        self._item()
        dados = self._dados()
        self.assertEqual(len(dados["itens"]), 1)
        self.assertEqual(dados["itens"][0]["familia"], "Familia A")
        self.assertEqual(dados["itens"][0]["preco_atual"], "R$ 80,00")
        self.assertEqual(dados["itens"][0]["base_origem"], "Sem CMC")
        self.assertEqual(dados["itens"][0]["variacao"], "-")
        self.assertEqual(dados["itens"][0]["impacto"], "-")
        self.assertEqual(dados["saving_total"], "R$ 0,00")
        self.assertEqual(dados["itens_comparados"], 0)
        self.assertEqual(dados["itens_sem_base"], 1)
        self.assertEqual(dados["familias"], [])

    def test_cmc_valido_mantem_calculo_de_saving(self):
        produto, item = self._item()
        PosicaoEstoqueOmie.objects.create(empresa=self.empresa, produto=produto, codigo_produto=produto.codigo_produto,
                                          codigo_local_estoque=1, codigo=produto.codigo, saldo=100, cmc=98, data_posicao=date(2026, 8, 5))
        dados = self._dados()
        self.assertEqual(dados["saving_total"], "R$ 200,00")
        self.assertEqual(dados["itens_comparados"], 1)
        self.assertEqual(dados["itens_sem_base"], 0)
        self.assertEqual(dados["itens"][0]["preco_base"], "R$ 100,00")

    def test_sem_saldo_anterior_mantem_linha_sem_comparacao(self):
        produto, item = self._item()
        PosicaoEstoqueOmie.objects.create(empresa=self.empresa, produto=produto, codigo_produto=produto.codigo_produto,
                                          codigo_local_estoque=1, codigo=produto.codigo, saldo=10, cmc=80, data_posicao=date(2026, 8, 5))
        dados = self._dados()
        self.assertEqual(dados["itens"][0]["base_origem"], "Sem saldo anterior")
        self.assertEqual(dados["itens_sem_base"], 1)

    def test_empresas_com_mesmo_codigo_nao_compartilham_familia_ou_cmc(self):
        self._item()
        outra = Empresa.objects.create(nome="Outra Saving", cnpj="00.000.000/0001-94")
        produto, item = self._item(outra, codigo=2, preco=60, familia="Familia B")
        PosicaoEstoqueOmie.objects.create(empresa=outra, produto=produto, codigo_produto=produto.codigo_produto,
                                          codigo_local_estoque=1, codigo=produto.codigo, saldo=100, cmc=51, data_posicao=date(2026, 8, 5))
        dados = self._dados([self.empresa.pk, outra.pk])
        self.assertEqual(len(dados["itens"]), 2)
        self.assertEqual(dados["perda_total"], "R$ 100,00")
        self.assertEqual(dados["itens_comparados"], 1)
        self.assertEqual(dados["itens_sem_base"], 1)
        self.assertEqual({item["familia"] for item in dados["itens"]}, {"Familia A", "Familia B"})

    def test_periodo_continua_baseado_na_emissao_da_nota(self):
        self._item()
        self.assertEqual(self._dados(periodo="mes-2026-10")["itens"], [])
        self.assertEqual(len(self._dados(periodo="mes-2026-08")["itens"]), 1)

    def test_cmc_ou_saldo_negativo_nao_entram_na_comparacao(self):
        produto, item = self._item()
        posicao = PosicaoEstoqueOmie.objects.create(
            empresa=self.empresa, produto=produto, codigo_produto=produto.codigo_produto,
            codigo_local_estoque=1, codigo=produto.codigo, saldo=100, cmc=-10,
        )
        self.assertEqual(self._dados()["itens_comparados"], 0)
        posicao.cmc = 4.642092
        posicao.saldo = -2801
        posicao.save()
        self.assertEqual(self._dados()["itens_comparados"], 0)
        self.assertEqual(self._dados()["saving_total"], "R$ 0,00")
