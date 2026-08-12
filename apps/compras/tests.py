from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.empresas.models import (
    CadastroOmie,
    CategoriaOmie,
    DepartamentoOmie,
    Empresa,
    EmpresaUsuario,
    IntegracaoOmie,
    PedidoCompraItemOmie,
    PedidoCompraOmie,
    ProdutoOmie,
)

from .models import BudgetConfiguracaoCompra, BudgetLimiteCompra


class BudgetComprasParametrosTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="gestor_compras",
            password="senha-segura",
        )
        self.empresa = Empresa.objects.create(
            nome="Empresa Compras Ltda",
            nome_fantasia="Empresa Compras",
            cnpj="00.000.000/0001-77",
        )
        EmpresaUsuario.objects.create(
            empresa=self.empresa,
            usuario=self.usuario,
            papel=EmpresaUsuario.Papel.GESTOR,
        )
        self.url = reverse(
            "dashboards:budget",
            kwargs={"empresa_slug": self.empresa.slug},
        )

    def budget_detail_url(self, tipo_controle):
        return f"{self.url}?budget_tipo={tipo_controle}"

    def test_card_budget_aparece_em_parametros(self):
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:parametros",
                kwargs={"empresa_slug": self.empresa.slug},
            )
        )

        self.assertContains(response, "<h2>Budget</h2>", html=True)
        self.assertContains(response, self.url)

    def test_lista_produtos_com_estoque_minimo_e_salva_limite(self):
        produto = ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
            estoque_minimo=Decimal("12.5000"),
        )
        pedido_anterior = PedidoCompraOmie.objects.create(
            empresa=self.empresa,
            codigo_pedido=900,
            data_previsao=timezone.localdate().replace(
                year=timezone.localdate().year - 1,
                month=3,
                day=10,
            ),
        )
        PedidoCompraItemOmie.objects.create(
            empresa=self.empresa,
            pedido=pedido_anterior,
            codigo_item=901,
            produto=produto,
            codigo_produto=produto.codigo_produto,
            descricao=produto.descricao,
            valor_total=Decimal("480.50"),
        )
        self.client.force_login(self.usuario)
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=BudgetConfiguracaoCompra.objects.get_or_create(
                empresa=self.empresa
            )[0],
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo=str(produto.codigo_produto),
            referencia_nome=produto.descricao,
            limite_compra=Decimal("1234.56"),
        )

        response = self.client.get(self.url)

        self.assertContains(response, 'class="budget-overview "')
        self.assertContains(response, 'class="budget-detail-view d-none"')
        self.assertContains(response, "Budget por familia de produtos")
        self.assertContains(response, "Budget de Projetos")
        self.assertContains(response, "Teto por fornecedor")
        self.assertContains(response, "Budget por Departamentos")
        self.assertContains(response, "Sem familia")
        self.assertContains(response, "Materia prima A")
        self.assertContains(response, "Gasto ano anterior")
        self.assertContains(response, "R$ 480,50")
        self.assertContains(response, 'value="1.234,56"')
        self.assertContains(response, 'data-budget-sort="previous"')
        self.assertContains(response, 'data-budget-sort="limit"')
        self.assertContains(response, "Mes")
        self.assertContains(response, 'name="mes_edicao_produto"')
        self.assertContains(response, "Replicar para o ano")
        self.assertNotContains(response, "Estoque minimo Omie")
        self.assertContains(
            response,
            f'name="limite_produto_{produto.codigo_produto}"',
        )

        response = self.client.get(self.budget_detail_url("produto"))

        self.assertContains(response, 'class="budget-overview d-none"')
        self.assertContains(response, 'class="budget-detail-view "')

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "produto",
                "periodicidade_produto": "mensal",
                "mes_edicao_produto": "3",
                f"limite_produto_{produto.codigo_produto}": "250,75",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        limite = BudgetLimiteCompra.objects.get(
            empresa=self.empresa,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo=str(produto.codigo_produto),
            mes=3,
        )
        self.assertEqual(limite.referencia_nome, "Materia prima A")
        self.assertEqual(limite.estoque_minimo, Decimal("12.5000"))
        self.assertEqual(limite.limite_compra, Decimal("250.75"))
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(configuracao.periodicidades_controle["produto"], "mensal")
        self.assertEqual(configuracao.meses_controle["produto"], [3])

    def test_seleciona_produto_e_fornecedor_na_mesma_rotina(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=202,
            tipo=CadastroOmie.Tipo.FORNECEDOR,
            razao_social="Fornecedor Oeste Ltda",
            cnpj_cpf="11.222.333/0001-44",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "definir_tipos",
                "tipos_controle": [
                    BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                    BudgetConfiguracaoCompra.TipoControle.FORNECEDOR,
                ],
            },
        )

        self.assertRedirects(response, self.url)
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(
            configuracao.tipos_selecionados,
            [
                BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                BudgetConfiguracaoCompra.TipoControle.FORNECEDOR,
            ],
        )

        response = self.client.get(self.url)

        self.assertContains(response, "Materia prima A")
        self.assertContains(response, "Fornecedor Oeste Ltda")
        self.assertContains(response, "11.222.333/0001-44")
        self.assertContains(response, 'data-budget-open="produto"')
        self.assertContains(response, 'data-budget-open="fornecedor"')
        self.assertContains(response, 'data-budget-panel="produto"')
        self.assertContains(response, 'data-budget-panel="fornecedor"')
        self.assertContains(response, 'data-budget-search="produto"')
        self.assertContains(response, 'data-budget-search="fornecedor"')

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "produto",
                "limite_produto_101": "10",
                "limite_fornecedor_202": "500",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        self.assertTrue(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="101",
                limite_compra=Decimal("10"),
            ).exists()
        )
        self.assertTrue(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.FORNECEDOR,
                referencia_codigo="202",
                limite_compra=Decimal("500"),
            ).exists()
        )

    def test_budget_por_departamento_lista_e_salva_limite(self):
        DepartamentoOmie.objects.create(
            empresa=self.empresa,
            codigo="DEP-001",
            descricao="Administrativo",
            estrutura="001.001",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "definir_tipos",
                "tipos_controle": [
                    BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO,
                ],
            },
        )

        self.assertRedirects(response, self.url)
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(
            configuracao.tipos_selecionados,
            [BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO],
        )

        response = self.client.get(self.url)

        self.assertContains(response, "Budget por Departamentos")
        self.assertContains(response, "Administrativo")
        self.assertContains(response, 'data-budget-open="departamento"')
        self.assertContains(response, 'data-budget-panel="departamento"')
        self.assertContains(response, 'data-budget-search="departamento"')

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "departamento",
                "limite_departamento_DEP-001": "1.500,00",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("departamento"))
        self.assertTrue(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO,
                referencia_codigo="DEP-001",
                limite_compra=Decimal("1500"),
            ).exists()
        )

    def test_budget_por_categoria_lista_botao_previsto_realizado_e_salva_limite(self):
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.01",
            descricao="Materiais de uso e consumo",
            categoria_superior="2.01",
        )
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.01.01",
            descricao="Venda de Mercadoria Fabricadas",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "definir_tipos",
                "tipos_controle": [
                    BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                ],
            },
        )

        self.assertRedirects(response, self.url)
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(
            configuracao.tipos_selecionados,
            [BudgetConfiguracaoCompra.TipoControle.CATEGORIA],
        )

        response = self.client.get(self.url)

        self.assertContains(response, "Budget por categoria")
        self.assertContains(response, "Materiais de uso e consumo")
        self.assertContains(response, "Superior 2.01")
        self.assertNotContains(response, "Venda de Mercadoria Fabricadas")
        self.assertContains(response, 'data-budget-open="categoria"')
        self.assertContains(response, 'data-budget-panel="categoria"')
        self.assertContains(response, 'data-budget-search="categoria"')
        self.assertContains(response, "Buscar Previsto x Realizado")
        self.assertContains(response, "data-budget-forecast-category")
        self.assertContains(response, 'form="budget-category-forecast-form"')
        self.assertContains(response, "data-budget-forecast-form")

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "categoria",
                "modalidade_categoria": "individual",
                "periodicidade_categoria": "mensal",
                "mes_edicao_categoria": "8",
                "limite_categoria_2.01.01": "2.500,00",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("categoria"))
        self.assertTrue(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo="2.01.01",
                mes=8,
                limite_compra=Decimal("2500"),
            ).exists()
        )
        configuracao.refresh_from_db()
        self.assertEqual(configuracao.periodicidades_controle["categoria"], "mensal")
        self.assertEqual(configuracao.meses_controle["categoria"], [8])

    def test_budget_por_categoria_rateia_em_grupo(self):
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.01",
            descricao="Materiais",
        )
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.02",
            descricao="Servicos",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "categoria",
                "modalidade_categoria": "grupo",
                "total_grupo_categoria": "1.000,00",
                "grupo_item_categoria": ["2.01.01", "2.01.02"],
            },
        )

        self.assertRedirects(response, self.budget_detail_url("categoria"))
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(configuracao.modalidades_controle["categoria"], "grupo")
        self.assertEqual(configuracao.totais_grupo["categoria"], "1000.00")
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo="2.01.01",
            ).limite_compra,
            Decimal("500.0000"),
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo="2.01.02",
            ).limite_compra,
            Decimal("500.0000"),
        )

    def test_budget_salvo_bloqueia_troca_de_modalidade_ate_reverter(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        configuracao = BudgetConfiguracaoCompra.objects.create(
            empresa=self.empresa,
            modalidades_controle={"produto": "individual"},
        )
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=configuracao,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
            referencia_nome="Materia prima A",
            limite_compra=Decimal("100"),
        )
        self.client.force_login(self.usuario)

        response = self.client.get(self.url)

        self.assertContains(response, "Reverter/Zerar")
        self.assertContains(response, 'form="budget-revert-form-produto"')
        self.assertContains(response, 'data-budget-revert')
        self.assertContains(response, "Reverta o budget salvo para trocar a modalidade")

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "100,00",
                "grupo_item_produto_sem_familia": ["101"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Para alterar a modalidade, reverta o budget salvo antes.",
        )
        configuracao.refresh_from_db()
        self.assertEqual(configuracao.modalidades_controle["produto"], "individual")
        self.assertTrue(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="101",
                limite_compra=Decimal("100"),
            ).exists()
        )

    def test_reverter_budget_zera_limites_e_libera_modalidade(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        configuracao = BudgetConfiguracaoCompra.objects.create(
            empresa=self.empresa,
            modalidades_controle={"produto": "grupo"},
            totais_grupo={
                "produto": {"sem_familia": "100.00"},
                "produto:mes:2": {"sem_familia": "200.00"},
            },
            periodicidades_controle={"produto": "mensal"},
            meses_controle={"produto": [1, 2]},
        )
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=configuracao,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
            referencia_nome="Materia prima A",
            limite_compra=Decimal("100"),
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "reverter_budget",
                "tipo_controle": "produto",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        self.assertFalse(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            ).exists()
        )
        configuracao.refresh_from_db()
        self.assertNotIn("produto", configuracao.modalidades_controle)
        self.assertNotIn("produto", configuracao.totais_grupo)
        self.assertNotIn("produto:mes:2", configuracao.totais_grupo)
        self.assertNotIn("produto", configuracao.periodicidades_controle)
        self.assertNotIn("produto", configuracao.meses_controle)

        response = self.client.get(self.url)

        self.assertNotContains(response, "Reverter/Zerar")
        self.assertNotContains(response, "Reverta o budget salvo para trocar a modalidade")

    def test_replicar_budget_mensal_copia_mes_para_ano(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        configuracao = BudgetConfiguracaoCompra.objects.create(
            empresa=self.empresa,
            modalidades_controle={"produto": "individual"},
            periodicidades_controle={"produto": "mensal"},
            meses_controle={"produto": [3]},
        )
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=configuracao,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
            referencia_nome="Materia prima A",
            mes=3,
            limite_compra=Decimal("750.00"),
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "replicar_budget_mensal",
                "tipo_controle": "produto",
                "mes_origem": "3",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        limites = BudgetLimiteCompra.objects.filter(
            empresa=self.empresa,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
        )
        self.assertEqual(limites.count(), 12)
        self.assertEqual(
            set(limites.values_list("mes", flat=True)),
            set(range(1, 13)),
        )
        self.assertTrue(
            all(limite.limite_compra == Decimal("750.0000") for limite in limites)
        )
        configuracao.refresh_from_db()
        self.assertEqual(configuracao.periodicidades_controle["produto"], "mensal")
        self.assertEqual(configuracao.meses_controle["produto"], [3])

    def test_selecionar_mes_budget_carrega_limites_do_mes(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        configuracao = BudgetConfiguracaoCompra.objects.create(
            empresa=self.empresa,
            periodicidades_controle={"produto": "mensal"},
            meses_controle={"produto": [3]},
        )
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=configuracao,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
            referencia_nome="Materia prima A",
            mes=3,
            limite_compra=Decimal("300.00"),
        )
        BudgetLimiteCompra.objects.create(
            empresa=self.empresa,
            configuracao=configuracao,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo="101",
            referencia_nome="Materia prima A",
            mes=8,
            limite_compra=Decimal("800.00"),
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "selecionar_mes_budget",
                "tipo_controle": "produto",
                "mes_edicao": "8",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        configuracao.refresh_from_db()
        self.assertEqual(configuracao.periodicidades_controle["produto"], "mensal")
        self.assertEqual(configuracao.meses_controle["produto"], [8])

        response = self.client.get(self.url)

        self.assertContains(response, 'value="800,00"')
        self.assertNotContains(response, 'value="300,00"')

    @patch("apps.compras.views.consultar_orcamentos_categorias")
    def test_busca_previsto_realizado_categoria_preenche_limite_pelo_omie(
        self,
        consultar_orcamentos_mock,
    ):
        integracao = IntegracaoOmie(empresa=self.empresa, app_key="app-key")
        integracao.definir_app_secret("app-secret")
        integracao.save()
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.01",
            descricao="Materiais",
        )
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.02",
            descricao="Servicos",
        )
        CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.01.01",
            descricao="Receita",
        )
        consultar_orcamentos_mock.return_value = {
            "orcamentos": [
                {
                    "cCodCateg": "2.01.01",
                    "cDesCateg": "Materiais",
                    "nValorPrevisto": 1200.75,
                    "nValorRealizado": 800,
                },
                {
                    "cCodCateg": "1.01.01",
                    "cDesCateg": "Receita",
                    "nValorPrevisto": 9999,
                    "nValorRealizado": 9999,
                },
            ]
        }
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "buscar_previsto_realizado_categoria",
                "periodicidade_categoria": "mensal",
                "mes_categoria": ["8"],
            },
        )

        self.assertRedirects(response, self.budget_detail_url("categoria"))
        consultar_orcamentos_mock.assert_called_once_with(
            integracao,
            timezone.localdate().year,
            8,
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo="2.01.01",
            ).limite_compra,
            Decimal("1200.75"),
        )
        self.assertFalse(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo="1.01.01",
            ).exists()
        )
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(configuracao.periodicidades_controle["categoria"], "mensal")
        self.assertEqual(configuracao.meses_controle["categoria"], [8])

    def test_rateia_budget_em_grupo_para_itens_selecionados(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=102,
            codigo="MP-102",
            descricao="Materia prima B",
        )
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=103,
            codigo="MP-103",
            descricao="Materia prima C",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "produto",
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "300,00",
                "grupo_item_produto_sem_familia": ["101", "102"],
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(configuracao.modalidades_controle["produto"], "grupo")
        self.assertEqual(configuracao.totais_grupo["produto"]["sem_familia"], "300.00")
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="101",
            ).limite_compra,
            Decimal("150.0000"),
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="102",
            ).limite_compra,
            Decimal("150.0000"),
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="103",
            ).limite_compra,
            Decimal("0.0000"),
        )

    def test_grupo_aceita_valor_manual_e_rateia_restante(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=102,
            codigo="MP-102",
            descricao="Materia prima B",
        )
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=103,
            codigo="MP-103",
            descricao="Materia prima C",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "tipo_ativo": "produto",
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "300,00",
                "grupo_item_produto_sem_familia": ["101", "102", "103"],
                "limite_produto_101": "180,00",
            },
        )

        self.assertRedirects(response, self.budget_detail_url("produto"))
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="101",
            ).limite_compra,
            Decimal("180.00"),
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="102",
            ).limite_compra,
            Decimal("60.0000"),
        )
        self.assertEqual(
            BudgetLimiteCompra.objects.get(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
                referencia_codigo="103",
            ).limite_compra,
            Decimal("60.0000"),
        )

    def test_grupo_nao_salva_quando_soma_dos_itens_difere_do_total(self):
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=101,
            codigo="MP-101",
            descricao="Materia prima A",
        )
        ProdutoOmie.objects.create(
            empresa=self.empresa,
            codigo_produto=102,
            codigo="MP-102",
            descricao="Materia prima B",
        )
        self.client.force_login(self.usuario)

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "300,00",
                "grupo_item_produto_sem_familia": ["101", "102"],
                "limite_produto_101": "100,00",
                "limite_produto_102": "150,00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Valor incompativel com o orçado")
        self.assertFalse(
            BudgetLimiteCompra.objects.filter(
                empresa=self.empresa,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            ).exists()
        )
