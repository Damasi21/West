from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.empresas.models import (
    CadastroOmie, CategoriaOmie, ContaCorrenteOmie, ContaPagarOmie, ContaReceberOmie,
    DepartamentoOmie, Empresa, EmpresaUsuario, ProjetoOmie,
)
from .titulos_financeiros_services import carteira_financeira


@patch("apps.dashboards.titulos_financeiros_services.timezone.localdate", return_value=date(2026, 10, 24))
class TitulosFinanceirosTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Carteira Empresa", cnpj="00.000.000/0001-71")
        self.outra = Empresa.objects.create(nome="Outra Carteira", cnpj="00.000.000/0001-72")
        self.usuario = get_user_model().objects.create_user(username="carteira-user")
        self.vinculo = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario, papel="viewer")
        self.pessoa = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=88, nome_fantasia="Pessoa Comercial")
        self.categoria = CategoriaOmie.objects.create(empresa=self.empresa, codigo="2.01", descricao="Materiais")
        ProjetoOmie.objects.create(empresa=self.empresa, codigo=10, nome="Projeto A")
        DepartamentoOmie.objects.create(empresa=self.empresa, codigo="DEP1", descricao="Departamento A")
        for tipo in ("pagar", "receber"):
            self.criar(tipo, 1, 23, 100, saldo=40)
            self.criar(tipo, 2, 24, 80)
            self.criar(tipo, 3, 27, 120)

    def criar(self, tipo, codigo, dia=24, valor=100, saldo=None, empresa=None, **kwargs):
        modelo = ContaPagarOmie if tipo == "pagar" else ContaReceberOmie
        pessoa_field = "fornecedor" if tipo == "pagar" else "cliente"
        valor_field = "valor_a_pagar" if tipo == "pagar" else "valor_a_receber"
        dados = {"empresa": empresa or self.empresa, "codigo_lancamento_omie": codigo,
                 "data_vencimento": date(2026, 10, dia), "valor_documento": valor,
                 valor_field: saldo if saldo is not None else valor, "codigo_cliente_fornecedor": 88,
                 "codigo_projeto": 10, "codigo_categoria": "2.01"}
        if not empresa:
            dados.update({pessoa_field: self.pessoa, "categoria_principal": self.categoria})
        dados.update(kwargs)
        return modelo.objects.create(**dados)

    def dados(self, tipo="pagar", **kwargs):
        return carteira_financeira(self.empresa, tipo, "mes-2026-10", **kwargs)

    def url(self, tipo="pagar", empresa=None):
        return reverse("dashboards:dashboard", args=[(empresa or self.empresa).slug, "financeiro", f"contas-a-{tipo}"])

    def test_quatro_cards_saldo_residual_e_vencimento(self, relogio):
        for tipo in ("pagar", "receber"):
            with self.subTest(tipo=tipo):
                dados = self.dados(tipo)
                self.assertEqual(len(dados["indicadores"]), 4)
                self.assertEqual([i["valor"] for i in dados["indicadores"]], ["R$ 240,00", "R$ 40,00", "R$ 80,00", "R$ 120,00"])
                self.assertEqual([i["quantidade"] for i in dados["indicadores"]], [3, 1, 1, 1])
                self.assertEqual(sum(dados["fluxo"]["valores"]), 240)
                self.assertEqual(sum(i["valor"] for i in dados["composicao"]), 240)

    def test_exclui_fechados_zerados_negativos_inativos_e_fora_periodo(self, relogio):
        for tipo in ("pagar", "receber"):
            self.criar(tipo, 4, status_titulo=" pago ")
            self.criar(tipo, 5, status_titulo="CANCELADO")
            self.criar(tipo, 6, status_titulo=" liquidado ")
            self.criar(tipo, 7, saldo=0)
            self.criar(tipo, 8, saldo=-5)
            self.criar(tipo, 9, ativo_omie=False)
            self.criar(tipo, 10, data_vencimento=date(2026, 11, 1))
            self.criar(tipo, 11, data_vencimento=None)
            self.criar(tipo, 12, empresa=self.outra)
            if tipo == "receber":
                self.criar(tipo, 13, status_titulo=" recebido ")
            self.assertEqual(self.dados(tipo)["total_fmt"], "R$ 240,00")

    def test_intervalo_e_pelo_vencimento_nao_emissao_ou_previsao(self, relogio):
        self.criar("pagar", 4, 24, 50, data_emissao=date(2024, 1, 1), data_previsao=date(2027, 1, 1))
        dados = carteira_financeira(self.empresa, "pagar", "personalizado", "2026-10-24", "2026-10-24")
        self.assertEqual(dados["total_fmt"], "R$ 130,00")
        self.assertEqual(len(dados["fluxo"]["labels"]), 1)

    def test_periodo_passado_nao_finge_hoje_no_fim_do_mes(self, relogio):
        dados = carteira_financeira(self.empresa, "pagar", "personalizado", "2026-10-01", "2026-10-23")
        self.assertEqual(dados["indicadores"][1]["valor"], "R$ 40,00")
        self.assertEqual(dados["indicadores"][2]["valor"], "R$ 0,00")
        self.assertEqual(dados["indicadores"][3]["valor"], "R$ 0,00")

    def test_banco_oculto_nao_conta(self, relogio):
        banco = ContaCorrenteOmie.objects.create(empresa=self.empresa, codigo_omie=44, nao_fluxo=True, nao_resumo=True)
        for tipo in ("pagar", "receber"):
            self.criar(tipo, 4, id_conta_corrente=44, conta_corrente=banco)
            self.assertEqual(self.dados(tipo)["total_fmt"], "R$ 240,00")

    def test_projeto_categoria_compostos_respeitam_empresa(self, relogio):
        self.criar("pagar", 4, valor=300, empresa=self.outra)
        base = {"empresas_ids": [self.empresa.pk, self.outra.pk]}
        self.assertEqual(self.dados(projetos=[f"{self.empresa.pk}:10"], **base)["total_fmt"], "R$ 240,00")
        self.assertEqual(self.dados(categorias=[f"{self.outra.pk}:2.01"], **base)["total_fmt"], "R$ 300,00")
        self.assertEqual(self.dados(projetos=["999"], **base)["total_fmt"], "R$ 0,00")

    def test_departamento_rateia_saldo_e_nao_valor_original(self, relogio):
        conta = ContaPagarOmie.objects.get(empresa=self.empresa, codigo_lancamento_omie=1)
        conta.distribuicao = [{"cCodDep": "DEP1", "nPerDep": 25}, {"cCodDep": "DEP2", "nPerDep": 75}]
        conta.save()
        dados = self.dados(departamentos=[f"{self.empresa.pk}:DEP1"])
        self.assertEqual(dados["total_fmt"], "R$ 10,00")
        self.assertEqual(dados["indicadores"][0]["quantidade"], 1)
        self.assertTrue(dados["rateado"])
        self.assertEqual(self.dados(departamentos=[f"{self.outra.pk}:DEP1"])["total_fmt"], "R$ 0,00")

    def test_departamento_por_valor_e_percentual_zero(self, relogio):
        conta = ContaPagarOmie.objects.get(empresa=self.empresa, codigo_lancamento_omie=1)
        conta.distribuicao = [{"cCodDep": "DEP1", "nValDep": 50}]
        conta.save()
        self.assertEqual(self.dados(departamentos=["DEP1"])["total_fmt"], "R$ 20,00")
        conta.distribuicao = [{"cCodDep": "DEP1", "nPerDep": 0, "nValDep": 50}]
        conta.save()
        self.assertEqual(self.dados(departamentos=["DEP1"])["total_fmt"], "R$ 0,00")

    def test_fluxo_adapta_granularidade_ao_periodo(self, relogio):
        ano = carteira_financeira(self.empresa, "pagar", "ano-2026")
        self.assertEqual(ano["fluxo"]["granularidade"], "mes")
        self.assertEqual(len(ano["fluxo"]["valores"]), 12)
        trimestre = carteira_financeira(self.empresa, "pagar", "tri-2026-4")
        self.assertEqual(trimestre["fluxo"]["granularidade"], "mes")
        self.assertEqual(trimestre["fluxo"]["labels"], ["Out/26", "Nov/26", "Dez/26"])
        self.assertEqual(sum(trimestre["fluxo"]["valores"]), 240)
        self.assertEqual(self.dados()["fluxo"]["granularidade"], "dia")
        self.assertEqual(len(self.dados()["fluxo"]["labels"]), 31)

    def test_ranking_nao_une_pessoas_por_nome(self, relogio):
        outro = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=99, nome_fantasia=self.pessoa.nome_fantasia)
        self.criar("pagar", 4, fornecedor=outro, codigo_cliente_fornecedor=99)
        self.assertEqual(len(self.dados()["ranking"]), 2)

    def test_categorias_excedentes_agrupadas_sem_perder_valores(self, relogio):
        for indice in range(10):
            self.criar("pagar", 20 + indice, categoria_principal=None, codigo_categoria=f"cat-{indice}")
        dados = self.dados()
        self.assertEqual(len(dados["composicao"]), 7)
        self.assertEqual(dados["composicao"][-1]["nome"], "Outras categorias")
        self.assertEqual(sum(i["valor"] for i in dados["composicao"]), 1240)

    def test_carteira_vazia_e_empresa_inativa(self, relogio):
        self.assertEqual(self.dados(empresas_ids=[])["total_fmt"], "R$ 0,00")
        self.empresa.ativa = False
        self.empresa.save()
        dados = self.dados()
        self.assertEqual(dados["total_fmt"], "R$ 0,00")
        self.assertFalse(dados["fluxo"]["tem_dados"])
        self.assertEqual(dados["composicao"], [])

    def test_lote_sem_n_mais_um(self, relogio):
        with self.assertNumQueries(1):
            self.dados()

    def test_telas_navegacao_e_filtros(self, relogio):
        self.client.force_login(self.usuario)
        for tipo in ("pagar", "receber"):
            response = self.client.get(self.url(tipo), {"periodo": "mes-2026-10", "_filtrar": "1"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Total em aberto")
            self.assertContains(response, 'name="departamento"')
            self.assertContains(response, "R$ 240,00")
            self.assertEqual(len(response.context["titulos_financeiros"]["indicadores"]), 4)

    def test_tela_respeita_permissoes_e_empresa(self, relogio):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(self.url(empresa=self.outra)).status_code, 404)
        self.vinculo.dashboards_permitidos = ["financeiro:contas-a-pagar"]
        self.vinculo.save()
        self.assertEqual(self.client.get(self.url("pagar")).status_code, 200)
        self.assertEqual(self.client.get(self.url("receber")).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_sem_secao_vencimentos_ou_paginacao(self, relogio):
        for i in range(30):
            self.criar("pagar", 100 + i)
        self.client.force_login(self.usuario)
        response = self.client.get(self.url(), {"periodo": "mes-2026-10", "pagina": "2", "_filtrar": "1"})
        dados = response.context["titulos_financeiros"]
        self.assertEqual(dados["total_fmt"], "R$ 3.240,00")
        self.assertNotContains(response, "Vencimentos do periodo")
        self.assertNotContains(response, "titles-pagination")
        self.assertNotIn("pagina", dados)

    def test_todos_os_graficos_e_indicadores_respeitam_periodo(self, relogio):
        for tipo in ("pagar", "receber"):
            self.criar(tipo, 90, valor=250, data_vencimento=date(2026, 2, 10))
            self.criar(tipo, 91, valor=300, data_vencimento=date(2026, 11, 10))
            for periodo, esperado in [("ano-2026", 790), ("tri-2026-4", 540), ("mes-2026-10", 240)]:
                with self.subTest(tipo=tipo, periodo=periodo):
                    dados = carteira_financeira(self.empresa, tipo, periodo)
                    self.assertEqual(sum(dados["fluxo"]["valores"]), esperado)
                    self.assertEqual(sum(i["valor"] for i in dados["composicao"]), esperado)
                    self.assertEqual(sum(i["valor"] for i in dados["ranking"]), esperado)
                    self.assertEqual(dados["indicadores"][0]["valor"], f"R$ {esperado},00")

    def test_dashboard_nao_acessa_api(self, relogio):
        self.client.force_login(self.usuario)
        with patch("apps.empresas.omie.urlopen", side_effect=AssertionError("Nao chamar OMIE")):
            self.assertEqual(self.client.get(self.url()).status_code, 200)
