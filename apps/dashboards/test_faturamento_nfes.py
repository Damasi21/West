from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from apps.empresas.models import Empresa, EmpresaUsuario, NfeSaidaItemOmie, NfeSaidaOmie, PedidoItemOmie, PedidoOmie
from .faturamento_services import faturamento_comercial, linhas_excel_faturamento_produtos


class FaturamentoNfeTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Faturamento NF", cnpj="00.000.000/0001-91")
        self.periodo = "mes-2026-01"

    def _nota(self, codigo=1, valor=100, data=None, cfop="5102", **kwargs):
        nota = NfeSaidaOmie.objects.create(
            empresa=kwargs.pop("empresa", self.empresa), codigo_nf=codigo,
            data_emissao=data or date(2026, 1, 10), numero=str(codigo), valor_total=valor,
            razao_social_destinatario="Cliente importado", **kwargs,
        )
        NfeSaidaItemOmie.objects.create(
            empresa=nota.empresa, nota=nota, sequencia=1, cfop=cfop,
            descricao="Produto importado", quantidade=2, valor_total=valor, valor_produtos=valor,
        )
        return nota

    def _dados(self, **kwargs):
        return faturamento_comercial(self.empresa, self.periodo, tipos_selecionados=["produtos"], **kwargs)

    def test_nota_importada_entra_em_total_graficos_ranking_e_detalhamento(self):
        self._nota()
        dados = self._dados()
        self.assertEqual(dados["indicadores"][0]["valor_completo"], "R$ 100,00")
        self.assertEqual(dados["produtos"], [100.0])
        self.assertEqual(dados["produtos_mercadorias"], [100.0])
        self.assertEqual(dados["acumulado"], [100.0])
        self.assertEqual(dados["ranking"][0]["nome"], "Produto importado")
        self.assertEqual(dados["ranking"][0]["quantidade"], "2")
        linhas = linhas_excel_faturamento_produtos(self.empresa, self.periodo)
        self.assertEqual(linhas[0]["numero_nf"], "1")
        self.assertEqual(linhas[0]["cliente"], "Cliente importado")
        self.assertEqual(linhas[0]["total_nota"], Decimal("100"))

    def test_cfop_inativo_remessa_cancelamento_e_outros_periodos_sao_excluidos(self):
        self._nota(1, cfop="5901")
        self._nota(2, data_cancelamento=date(2026, 1, 11))
        self._nota(3, denegada=True)
        self._nota(4, data_inutilizacao=date(2026, 1, 11))
        self._nota(5, ativo_omie=False)
        self._nota(6, data=date(2026, 2, 10))
        self.empresa.cfops_venda_omie.filter(codigo="5102").update(ativo=False)
        self.assertEqual(self._dados()["produtos"], [0.0])
        self.assertEqual(linhas_excel_faturamento_produtos(self.empresa, self.periodo), [])

    def test_nota_mista_nao_soma_remessa_nem_seus_impostos(self):
        nota = self._nota(valor=1000)
        nota.itens.update(valor_total=100, valor_produtos=95, valor_frete=5,
                          dados_originais={"prod": {"vICMS": 7}})
        NfeSaidaItemOmie.objects.create(empresa=self.empresa, nota=nota, sequencia=2,
                                       cfop="5901", valor_total=900, descricao="Remessa", dados_originais={"prod": {"vICMS": 90}})
        dados = self._dados()
        self.assertEqual(dados["produtos"], [100.0])
        self.assertEqual(dados["produtos_mercadorias"], [95.0])
        self.assertEqual(dados["produtos_frete_despesas"], [5.0])
        self.assertEqual(len(dados["ranking"]), 1)
        impostos = faturamento_comercial(self.empresa, self.periodo, tipos_selecionados=["impostos"])
        self.assertEqual(impostos["produtos_impostos"], [7.0])
        self.assertEqual(linhas_excel_faturamento_produtos(self.empresa, self.periodo)[0]["total_nota"], Decimal("100"))

    def test_nota_vinculada_a_pedido_faturado_nao_duplica(self):
        PedidoOmie.objects.create(empresa=self.empresa, codigo_pedido=9, faturado=True,
                                  data_faturamento=date(2026, 1, 10), valor_total_pedido=100)
        self._nota(codigo_pedido=9)
        self.assertEqual(self._dados()["produtos"], [100.0])
        self.assertEqual(len(linhas_excel_faturamento_produtos(self.empresa, self.periodo)), 1)

    def test_chave_da_nfe_evitar_duplicacao_sem_id_do_pedido(self):
        chave = "1" * 44
        PedidoOmie.objects.create(empresa=self.empresa, codigo_pedido=9, faturado=True,
                                  data_faturamento=date(2026, 1, 10), valor_total_pedido=100,
                                  dados_originais={"nf": {"cChaveNFe": chave}})
        self._nota(chave_nfe=chave)
        self.assertEqual(self._dados()["produtos"], [100.0])

    def test_comparativo_inclui_notas_do_periodo_anterior(self):
        self._nota(1, valor=100)
        self._nota(2, valor=50, data=date(2025, 12, 10))
        dados = self._dados()
        self.assertEqual(dados["produtos_anterior"], [50.0])
        self.assertEqual(dados["media_anterior"], [50.0])
        self.assertEqual(dados["ranking"][0]["variacao_fmt"], "100%")

    def test_isolamento_da_empresa_e_filtros_sem_metadados(self):
        outra = Empresa.objects.create(nome="Outra NF", cnpj="00.000.000/0001-92")
        self._nota(empresa=outra, valor=900)
        self._nota()
        self.assertEqual(self._dados()["produtos"], [100.0])
        self.assertEqual(self._dados(projetos_selecionados=[77])["produtos"], [0.0])
        self.assertEqual(self._dados(vendedores_selecionados=[88])["produtos"], [0.0])
        self.assertEqual(self._dados(empresas_ids=[self.empresa.pk, outra.pk])["produtos"], [1000.0])

    def test_filtros_herdam_pedido_nao_faturado_sem_somar_pedido_ao_faturamento(self):
        PedidoOmie.objects.create(empresa=self.empresa, codigo_pedido=9, faturado=False,
                                  codigo_projeto=77, codigo_vendedor=88)
        self._nota(codigo_pedido=9)
        self.assertEqual(self._dados(projetos_selecionados=[77], vendedores_selecionados=[88])["produtos"], [100.0])

    def test_ranking_une_produto_do_pedido_e_da_nota_antes_do_top_cinco(self):
        pedido = PedidoOmie.objects.create(empresa=self.empresa, codigo_pedido=9, faturado=True,
                                          data_faturamento=date(2026, 1, 10), valor_total_pedido=60)
        PedidoItemOmie.objects.create(empresa=self.empresa, pedido=pedido, codigo_item=1,
                                      descricao="Produto importado", valor_total=60, quantidade=1)
        self._nota()
        ranking = self._dados()["ranking"]
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["valor_fmt"], "R$ 160,00")
        self.assertEqual(ranking[0]["quantidade"], "3")

    def test_tela_e_excel_incluem_nota_importada(self):
        usuario = get_user_model().objects.create_user(username="nf_faturamento")
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=usuario)
        self.client.force_login(usuario)
        self._nota()
        kwargs = {"empresa_slug": self.empresa.slug, "area_slug": "comercial", "dashboard_slug": "faturamento"}
        response = self.client.get(reverse("dashboards:dashboard", kwargs=kwargs), {"_filtrar": "1", "periodo": self.periodo})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["faturamento_produtos_totais"]["total_nota"], Decimal("100"))
        response = self.client.get(reverse("dashboards:exportar_faturamento_produtos", kwargs={"empresa_slug": self.empresa.slug}), {"periodo": self.periodo})
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.active["C2"].value, "1")
        self.assertEqual(workbook.active["F2"].value, 100)
