from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import (
    CadastroOmie,
    Empresa,
    EmpresaUsuario,
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

        self.assertContains(response, "Budget por familia de produtos")
        self.assertContains(response, "Budget de Projetos")
        self.assertContains(response, "Teto por fornecedor")
        self.assertContains(response, "Sem familia")
        self.assertContains(response, "Materia prima A")
        self.assertContains(response, "Gasto ano anterior")
        self.assertContains(response, "R$ 480,50")
        self.assertContains(response, 'value="1.234,56"')
        self.assertContains(response, 'data-budget-sort="previous"')
        self.assertContains(response, 'data-budget-sort="limit"')
        self.assertContains(response, "Meses")
        self.assertContains(response, 'name="mes_produto"')
        self.assertContains(response, "Todos os meses")
        self.assertContains(response, "Selecionar todos")
        self.assertNotContains(response, "Estoque minimo Omie")
        self.assertContains(
            response,
            f'name="limite_produto_{produto.codigo_produto}"',
        )

        response = self.client.post(
            self.url,
            {
                "acao": "salvar_limites",
                "periodicidade_produto": "mensal",
                "mes_produto": ["1", "3", "12"],
                f"limite_produto_{produto.codigo_produto}": "250,75",
            },
        )

        self.assertRedirects(response, self.url)
        limite = BudgetLimiteCompra.objects.get(
            empresa=self.empresa,
            tipo_controle=BudgetConfiguracaoCompra.TipoControle.PRODUTO,
            referencia_codigo=str(produto.codigo_produto),
        )
        self.assertEqual(limite.referencia_nome, "Materia prima A")
        self.assertEqual(limite.estoque_minimo, Decimal("12.5000"))
        self.assertEqual(limite.limite_compra, Decimal("250.75"))
        configuracao = BudgetConfiguracaoCompra.objects.get(empresa=self.empresa)
        self.assertEqual(configuracao.periodicidades_controle["produto"], "mensal")
        self.assertEqual(configuracao.meses_controle["produto"], [1, 3, 12])

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
                "limite_produto_101": "10",
                "limite_fornecedor_202": "500",
            },
        )

        self.assertRedirects(response, self.url)
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
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "300,00",
                "grupo_item_produto_sem_familia": ["101", "102"],
            },
        )

        self.assertRedirects(response, self.url)
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
                "modalidade_produto": "grupo",
                "total_grupo_produto_sem_familia": "300,00",
                "grupo_item_produto_sem_familia": ["101", "102", "103"],
                "limite_produto_101": "180,00",
            },
        )

        self.assertRedirects(response, self.url)
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
