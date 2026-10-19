from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.empresas.models import (
    ContaReceberOmie, Empresa, MetaVendedorComercial, PedidoOmie, VendedorOmie,
)
from .desempenho_vendedores_services import desempenho_vendedores


class DesempenhoVendedoresReceberTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Vendas", cnpj="00.000.000/0001-81")
        self.vendedor = VendedorOmie.objects.create(empresa=self.empresa, codigo=201, nome="Ana")
        MetaVendedorComercial.objects.create(
            empresa=self.empresa, vendedor=self.vendedor, ano=2026, mes=1, valor_mensal=1000,
        )

    def _titulo(self, codigo=1, empresa=None, vendedor=201, **campos):
        dados = {
            "data_emissao": date(2026, 1, 10), "data_vencimento": date(2026, 2, 10),
            "valor_documento": 100, "valor_a_receber": 0, "status_titulo": "RECEBIDO",
            "dados_originais": {"codigo_vendedor": vendedor},
        }
        dados.update(campos)
        return ContaReceberOmie.objects.create(
            empresa=empresa or self.empresa, codigo_lancamento_omie=codigo, **dados,
        )

    def _dados(self, **filtros):
        return desempenho_vendedores(self.empresa, "mes-2026-01", **filtros)

    def test_valor_original_por_emissao_inclui_recebidos_sem_somar_faturamento(self):
        self._titulo(valor_documento=400)
        self._titulo(2, vendedor="201", valor_documento=600, status_titulo="A VENCER", valor_a_receber=50)
        self._titulo(3, data_emissao=date(2025, 12, 30), data_vencimento=date(2026, 1, 15), valor_documento=9999)
        PedidoOmie.objects.create(
            empresa=self.empresa, codigo_pedido=1, codigo_vendedor=201,
            faturado=True, data_faturamento=date(2026, 1, 10), valor_total_pedido=9999,
        )
        dados = self._dados()
        self.assertEqual(dados["ranking_realizado"], [1000.0])
        self.assertEqual(dados["ranking"][0]["percentual"], Decimal("100"))
        self.assertEqual(dados["tendencia_series"][0]["valores"], [1000.0])
        self.assertEqual(dados["indicadores"][3]["valor_completo"], "R$ 500,00")

    def test_exclui_cancelados_inativos_sem_emissao_e_sem_vendedor(self):
        self._titulo()
        self._titulo(2, status_titulo="cancelado")
        self._titulo(3, ativo_omie=False)
        self._titulo(4, data_emissao=None)
        self._titulo(5, dados_originais={})
        self._titulo(6, vendedor=0)
        self._titulo(7, vendedor=999)
        self.assertEqual(self._dados()["ranking_realizado"], [100.0])

    def test_filtra_projeto_e_vendedor_do_titulo_sem_depender_de_pedido(self):
        VendedorOmie.objects.create(empresa=self.empresa, codigo=202, nome="Bia")
        self._titulo(codigo_projeto=10)
        self._titulo(2, codigo_projeto=20)
        self._titulo(3, codigo_projeto=10, vendedor=202)
        dados = self._dados(
            projetos_selecionados=[f"{self.empresa.pk}:10"],
            vendedores_selecionados=[f"{self.empresa.pk}:201"],
        )
        self.assertEqual(dados["ranking_labels"], ["Ana"])
        self.assertEqual(dados["ranking_realizado"], [100.0])

    def test_mesmo_codigo_em_empresas_distintas_nao_mistura_valores_ou_metas(self):
        outra = Empresa.objects.create(nome="Outra", cnpj="00.000.000/0001-82")
        vendedor = VendedorOmie.objects.create(empresa=outra, codigo=201, nome="Bia")
        MetaVendedorComercial.objects.create(
            empresa=outra, vendedor=vendedor, ano=2026, mes=1, valor_mensal=500,
        )
        self._titulo(valor_documento=1000)
        self._titulo(empresa=outra, valor_documento=250)
        dados = self._dados(empresas_ids=[self.empresa.pk, outra.pk])
        self.assertEqual(dados["ranking_labels"], ["Ana", "Bia"])
        self.assertEqual(dados["ranking_realizado"], [1000.0, 250.0])
        self.assertEqual(dados["ranking_meta"], [1000.0, 500.0])
        self.assertEqual([s["valores"] for s in dados["tendencia_series"]], [[1000.0], [250.0]])
        filtrados = self._dados(
            empresas_ids=[self.empresa.pk, outra.pk],
            vendedores_selecionados=[f"{outra.pk}:201"],
        )
        self.assertEqual(filtrados["ranking_labels"], ["Bia"])
        self.assertEqual(filtrados["ranking_realizado"], [250.0])

    def test_carteira_de_pedidos_permanece_separada_do_realizado(self):
        self._titulo(valor_documento=1000)
        PedidoOmie.objects.create(
            empresa=self.empresa, codigo_pedido=1, codigo_vendedor=201,
            data_inclusao=date(2026, 1, 15), faturado=False, valor_total_pedido=700,
        )
        dados = self._dados()
        self.assertEqual(dados["ranking_realizado"], [1000.0])
        self.assertEqual(dados["carteira"][0]["valor"], Decimal("700"))
        self.assertEqual(dados["carteira"][0]["pedidos_num"], 1)

    def test_sem_titulos_retorna_zero_sem_usar_faturamento_como_fallback(self):
        PedidoOmie.objects.create(
            empresa=self.empresa, codigo_pedido=1, codigo_vendedor=201,
            faturado=True, data_faturamento=date(2026, 1, 10), valor_total_pedido=9999,
        )
        dados = self._dados()
        self.assertEqual(dados["ranking_realizado"], [0.0])
        self.assertEqual(dados["indicadores"][3]["valor_completo"], "R$ 0,00")
