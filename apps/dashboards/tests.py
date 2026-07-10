from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.empresas.models import (
    CadastroOmie,
    CategoriaOmie,
    ContaCorrenteOmie,
    ContaDRE,
    ContaPagarOmie,
    ContaReceberOmie,
    DepartamentoOmie,
    Empresa,
    EmpresaUsuario,
    LancamentoContaCorrenteOmie,
    ProjetoOmie,
)


class DashboardPermissaoTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="analista", password="senha-segura"
        )
        self.empresa = Empresa.objects.create(
            nome="Oeste Cliente Ltda",
            nome_fantasia="Oeste Cliente",
            cnpj="11.111.111/0001-11",
        )

    def test_usuario_sem_vinculo_nao_acessa_dashboard(self):
        self.client.force_login(self.usuario)
        response = self.client.get(
            reverse("dashboards:home", kwargs={"empresa_slug": self.empresa.slug})
        )
        self.assertEqual(response.status_code, 404)

    def test_usuario_vinculado_acessa_todas_as_areas_padrao(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        for area in ("comercial", "financeiro", "compras", "estoque", "crm"):
            response = self.client.get(
                reverse(
                    "dashboards:area",
                    kwargs={"empresa_slug": self.empresa.slug, "area_slug": area},
                )
            )
            self.assertEqual(response.status_code, 200)

    def test_menu_principal_usa_imagens_das_areas(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse("dashboards:home", kwargs={"empresa_slug": self.empresa.slug})
        )

        for imagem in (
            "vendas.png",
            "financeiro.png",
            "compras.png",
            "estoque.png",
            "crm.png",
        ):
            self.assertContains(response, f"/media/{imagem}")

    def test_parametros_aparecem_acima_do_status_para_administrador(self):
        administrador = get_user_model().objects.create_user(
            username="admin_dashboard",
            password="senha-segura",
            is_staff=True,
        )
        self.client.force_login(administrador)

        response = self.client.get(
            reverse("dashboards:home", kwargs={"empresa_slug": self.empresa.slug})
        )

        url_parametros = reverse(
            "dashboards:parametros",
            kwargs={"empresa_slug": self.empresa.slug},
        )
        self.assertContains(response, url_parametros)
        conteudo = response.content.decode()
        self.assertLess(
            conteudo.index("Parâmetros"),
            conteudo.index("Estrutura pronta para integração OMIE"),
        )

    def test_parametros_nao_aparecem_para_usuario_comum(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse("dashboards:home", kwargs={"empresa_slug": self.empresa.slug})
        )

        self.assertNotContains(
            response,
            reverse(
                "dashboards:parametros",
                kwargs={"empresa_slug": self.empresa.slug},
            ),
        )

    def test_area_inexistente_retorna_404(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)
        response = self.client.get(
            reverse(
                "dashboards:area",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "inexistente",
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_area_exibe_os_dashboards_disponiveis(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:area",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                },
            )
        )

        self.assertContains(response, "Visão de vendas")
        self.assertContains(response, "Desempenho de vendedores")
        self.assertContains(response, "Análise de clientes")
        self.assertContains(response, "Produtos vendidos")

    def test_dashboard_da_area_pode_ser_aberto(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                    "dashboard_slug": "visao-de-vendas",
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visão de vendas")

    def test_dashboard_exibe_filtros_e_projetos_ativos(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        projeto = ProjetoOmie.objects.create(
            empresa=self.empresa,
            codigo=123,
            nome="PC2025-04",
        )
        ProjetoOmie.objects.create(
            empresa=self.empresa,
            codigo=456,
            nome="Projeto inativo",
            inativo=True,
        )
        departamento = DepartamentoOmie.objects.create(
            empresa=self.empresa,
            codigo="5476993662",
            descricao="Hinfoluz",
            estrutura="001.001.001",
        )
        DepartamentoOmie.objects.create(
            empresa=self.empresa,
            codigo="999",
            descricao="Departamento inativo",
            inativo=True,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                    "dashboard_slug": "visao-de-vendas",
                },
            ),
            {
                "projeto": projeto.codigo,
                "departamento": departamento.codigo,
            },
        )

        self.assertContains(response, "Todos os projetos")
        self.assertContains(response, "PC2025-04")
        self.assertNotContains(response, "Projeto inativo")
        self.assertContains(response, "Todos os departamentos")
        self.assertContains(response, "Hinfoluz")
        self.assertNotContains(response, "Departamento inativo")
        self.assertContains(response, self.empresa.nome_fantasia)

    def test_dashboard_permite_multisselecao_de_filtros(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        outra_empresa = Empresa.objects.create(
            nome="Filial Oeste Ltda",
            nome_fantasia="Filial Oeste",
            cnpj="22.222.222/0001-22",
        )
        EmpresaUsuario.objects.create(empresa=outra_empresa, usuario=self.usuario)
        projeto_principal = ProjetoOmie.objects.create(
            empresa=self.empresa,
            codigo=101,
            nome="Projeto principal",
        )
        projeto_filial = ProjetoOmie.objects.create(
            empresa=outra_empresa,
            codigo=202,
            nome="Projeto filial",
        )
        departamento_principal = DepartamentoOmie.objects.create(
            empresa=self.empresa,
            codigo="DEP-1",
            descricao="Comercial matriz",
        )
        departamento_filial = DepartamentoOmie.objects.create(
            empresa=outra_empresa,
            codigo="DEP-2",
            descricao="Comercial filial",
        )
        self.client.force_login(self.usuario)
        url = reverse(
            "dashboards:dashboard",
            kwargs={
                "empresa_slug": self.empresa.slug,
                "area_slug": "comercial",
                "dashboard_slug": "visao-de-vendas",
            },
        )

        response = self.client.get(
            url,
            {
                "_filtrar": "1",
                "empresa": [str(self.empresa.pk), str(outra_empresa.pk)],
                "projeto": [
                    f"{self.empresa.pk}:{projeto_principal.codigo}",
                    f"{outra_empresa.pk}:{projeto_filial.codigo}",
                ],
                "departamento": [
                    f"{self.empresa.pk}:{departamento_principal.codigo}",
                    f"{outra_empresa.pk}:{departamento_filial.codigo}",
                ],
                "periodo": f"tri-{ano_atual}-2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["empresas_selecionadas"]), 2)
        self.assertEqual(len(response.context["projetos_selecionados"]), 2)
        self.assertEqual(len(response.context["departamentos_selecionados"]), 2)
        self.assertContains(response, "Projeto principal")
        self.assertContains(response, "Projeto filial")
        self.assertContains(response, "Comercial matriz")
        self.assertContains(response, "Comercial filial")

    def test_periodo_pode_ser_compartilhado_no_modulo(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)
        url_vendas = reverse(
            "dashboards:dashboard",
            kwargs={
                "empresa_slug": self.empresa.slug,
                "area_slug": "comercial",
                "dashboard_slug": "visao-de-vendas",
            },
        )
        url_clientes = reverse(
            "dashboards:dashboard",
            kwargs={
                "empresa_slug": self.empresa.slug,
                "area_slug": "comercial",
                "dashboard_slug": "analise-de-clientes",
            },
        )

        response = self.client.get(
            url_vendas,
            {
                "_filtrar": "1",
                "periodo": f"mes-{ano_atual}-04",
                "compartilhar_periodo": "1",
            },
        )
        self.assertTrue(response.context["periodo_foi_compartilhado"])

        response = self.client.get(url_clientes)
        self.assertEqual(
            response.context["periodo_selecionado"],
            f"mes-{ano_atual}-04",
        )
        self.assertTrue(response.context["periodo_compartilhado"])
        self.assertContains(response, f"Abril de {ano_atual}")

    def test_filtro_de_data_exibe_anos_trimestres_e_meses(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                    "dashboard_slug": "visao-de-vendas",
                },
            )
        )

        self.assertContains(response, "1º trimestre")
        self.assertContains(response, "4º trimestre")
        self.assertContains(response, "Janeiro")
        self.assertContains(response, "Dezembro")
        self.assertContains(response, "Período específico")
        self.assertContains(response, "Usar no módulo")

    def test_periodo_especifico_e_compartilhado_no_modulo(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)
        url_vendas = reverse(
            "dashboards:dashboard",
            kwargs={
                "empresa_slug": self.empresa.slug,
                "area_slug": "comercial",
                "dashboard_slug": "visao-de-vendas",
            },
        )
        url_produtos = reverse(
            "dashboards:dashboard",
            kwargs={
                "empresa_slug": self.empresa.slug,
                "area_slug": "comercial",
                "dashboard_slug": "produtos-vendidos",
            },
        )

        response = self.client.get(
            url_vendas,
            {
                "_filtrar": "1",
                "periodo": "personalizado",
                "data_inicio": "2026-01-15",
                "data_fim": "2026-02-20",
                "compartilhar_periodo": "1",
            },
        )

        self.assertEqual(response.context["periodo_selecionado"], "personalizado")
        self.assertEqual(response.context["data_inicio"], "2026-01-15")
        self.assertEqual(response.context["data_fim"], "2026-02-20")
        self.assertContains(response, "15/01/2026 a 20/02/2026")

        response = self.client.get(url_produtos)
        self.assertEqual(response.context["periodo_selecionado"], "personalizado")
        self.assertEqual(response.context["data_inicio"], "2026-01-15")
        self.assertEqual(response.context["data_fim"], "2026-02-20")

    def test_periodo_especifico_invalido_volta_ao_ano_atual(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                    "dashboard_slug": "visao-de-vendas",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": "personalizado",
                "data_inicio": "2026-03-10",
                "data_fim": "2026-03-01",
            },
        )

        self.assertEqual(
            response.context["periodo_selecionado"],
            f"ano-{date.today().year}",
        )

    def test_dashboard_inexistente_retorna_404(self):
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "comercial",
                    "dashboard_slug": "inexistente",
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_dre_gerencial_exibe_indicadores_tabela_e_graficos(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        receita = ContaDRE.objects.create(
            empresa=self.empresa,
            nome="Receita Bruta",
            ordem=1,
        )
        custos = ContaDRE.objects.create(
            empresa=self.empresa,
            nome="Deducoes e Gastos Variaveis",
            sinal=ContaDRE.Sinal.SUBTRACAO,
            ordem=2,
        )
        custos_variaveis = ContaDRE.objects.create(
            empresa=self.empresa,
            nome="Custos Variaveis",
            conta_pai=custos,
            sinal=ContaDRE.Sinal.SUBTRACAO,
            ordem=1,
        )
        categoria = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.02.02",
            descricao="Materia prima",
            conta_dre=custos_variaveis,
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=1001,
            data_lancamento=date(ano_atual, 1, 10),
            valor_lancamento=1200,
            categoria_principal=categoria,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "financeiro",
                    "dashboard_slug": "dre-gerencial",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": f"mes-{ano_atual}-01",
                "regime_financeiro": "caixa",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Receita bruta")
        self.assertContains(response, "Deducoes e gastos variaveis")
        self.assertContains(response, "DRE Gerencial")
        self.assertContains(response, "Custos Variaveis")
        self.assertContains(response, "data-dre-expand-all")
        self.assertContains(response, "data-dre-values-chart")
        self.assertContains(response, "data-dre-ah-chart")
        self.assertContains(response, 'option value="caixa" selected')

    def test_visao_geral_financeira_exibe_indicadores_graficos_e_rankings(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        cliente = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=2001,
            tipo=CadastroOmie.Tipo.CLIENTE,
            nome_fantasia="Cliente Forte",
            razao_social="Cliente Forte Ltda",
        )
        fornecedor = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=3001,
            tipo=CadastroOmie.Tipo.FORNECEDOR,
            nome_fantasia="Fornecedor Chave",
            razao_social="Fornecedor Chave Ltda",
        )
        categoria_receita = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.01.01",
            descricao="Servicos Prestados",
        )
        categoria_despesa = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.01",
            descricao="Alimentacao",
        )
        ContaReceberOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=4001,
            cliente=cliente,
            categoria_principal=categoria_receita,
            data_previsao=date(ano_atual, 1, 10),
            valor_documento=5000,
        )
        ContaPagarOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=5001,
            fornecedor=fornecedor,
            categoria_principal=categoria_despesa,
            data_previsao=date(ano_atual, 1, 12),
            valor_documento=1800,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "financeiro",
                    "dashboard_slug": "visao-geral",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": f"mes-{ano_atual}-01",
                "regime_financeiro": "competencia",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recebimentos")
        self.assertContains(response, "Pagamentos")
        self.assertContains(response, "Resultado")
        self.assertContains(response, "Margem mensal")
        self.assertContains(response, "Cliente Forte")
        self.assertContains(response, "Fornecedor Chave")
        self.assertContains(response, "data-overview-flow-chart")
        self.assertContains(response, "data-overview-margin-chart")
        self.assertContains(response, 'option value="competencia" selected')

    def test_visao_geral_caixa_usa_lancamentos_de_conta_corrente(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        cliente = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=6001,
            tipo=CadastroOmie.Tipo.CLIENTE,
            nome_fantasia="Cliente Caixa",
        )
        fornecedor = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=7001,
            tipo=CadastroOmie.Tipo.FORNECEDOR,
            nome_fantasia="Fornecedor Caixa",
        )
        categoria_receita = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.01.02",
            descricao="Mensalidade",
        )
        categoria_despesa = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.01.02",
            descricao="Insumos",
        )
        ContaReceberOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=8001,
            cliente=cliente,
            categoria_principal=categoria_receita,
            data_registro=date(ano_atual, 2, 10),
            valor_documento=9900,
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=9001,
            cliente_fornecedor=cliente,
            categoria_principal=categoria_receita,
            data_lancamento=date(ano_atual, 1, 10),
            natureza="R",
            valor_lancamento=1200,
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=9002,
            cliente_fornecedor=fornecedor,
            categoria_principal=categoria_despesa,
            data_lancamento=date(ano_atual, 1, 11),
            natureza="P",
            valor_lancamento=400,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "financeiro",
                    "dashboard_slug": "visao-geral",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": f"mes-{ano_atual}-01",
                "regime_financeiro": "caixa",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cliente Caixa")
        self.assertContains(response, "Fornecedor Caixa")
        self.assertNotContains(response, "R$ 9.900,00")

    def test_fluxo_de_caixa_exibe_indicadores_grafico_criticos_e_composicoes(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        cliente = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=10001,
            tipo=CadastroOmie.Tipo.CLIENTE,
            nome_fantasia="Cliente Critico",
        )
        fornecedor = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=10002,
            tipo=CadastroOmie.Tipo.FORNECEDOR,
            nome_fantasia="Fornecedor Critico",
        )
        categoria_receita = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.03.01",
            descricao="Assinaturas",
        )
        categoria_despesa = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="2.03.01",
            descricao="Operacional",
        )
        ContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_omie=101,
            descricao="Conta principal",
            saldo_inicial=15000,
        )
        ContaReceberOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=11001,
            cliente=cliente,
            categoria_principal=categoria_receita,
            data_vencimento=date(ano_atual, 1, 10),
            valor_documento=7000,
            valor_a_receber=7000,
            status_titulo="ATRASADO",
        )
        ContaPagarOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=12001,
            fornecedor=fornecedor,
            categoria_principal=categoria_despesa,
            data_entrada=date(ano_atual, 1, 1),
            data_vencimento=date(ano_atual, 1, 15),
            valor_documento=2500,
            valor_a_pagar=2500,
            status_titulo="ATRASADO",
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=13001,
            data_lancamento=date(ano_atual, 1, 20),
            natureza="R",
            valor_lancamento=900,
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=13002,
            data_lancamento=date(ano_atual, 1, 21),
            natureza="P",
            valor_lancamento=300,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "financeiro",
                    "dashboard_slug": "fluxo-de-caixa",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": f"mes-{ano_atual}-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saldo atual")
        self.assertContains(response, "Entradas previstas")
        self.assertContains(response, "Saidas previstas")
        self.assertContains(response, "Saldo projetado")
        self.assertContains(response, "Prazo medio de pagamento")
        self.assertContains(response, "Cliente Critico")
        self.assertContains(response, "Fornecedor Critico")
        self.assertContains(response, "Composicao das entradas previstas")
        self.assertContains(response, "Composicao das saidas previstas")
        self.assertContains(response, "data-cashflow-chart")
        self.assertContains(response, "data-cashflow-in-pie")
        self.assertContains(response, "data-cashflow-out-pie")

    def test_inadimplencia_exibe_indicadores_graficos_e_top_devedores(self):
        ano_atual = date.today().year
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        cliente_a = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=14001,
            tipo=CadastroOmie.Tipo.CLIENTE,
            nome_fantasia="Devedor Alfa",
        )
        cliente_b = CadastroOmie.objects.create(
            empresa=self.empresa,
            codigo_cliente_omie=14002,
            tipo=CadastroOmie.Tipo.CLIENTE,
            nome_fantasia="Devedor Beta",
        )
        categoria = CategoriaOmie.objects.create(
            empresa=self.empresa,
            codigo="1.04.01",
            descricao="Servicos em atraso",
        )
        ContaReceberOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=15001,
            cliente=cliente_a,
            categoria_principal=categoria,
            data_emissao=date(ano_atual, 1, 1),
            data_vencimento=date(ano_atual, 1, 10),
            valor_documento=8000,
            valor_a_receber=8000,
            status_titulo="ATRASADO",
        )
        ContaReceberOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=15002,
            cliente=cliente_b,
            categoria_principal=categoria,
            data_emissao=date(ano_atual, 1, 5),
            data_vencimento=date(ano_atual, 2, 15),
            valor_documento=3000,
            valor_a_receber=3000,
            status_titulo="ATRASADO",
        )
        LancamentoContaCorrenteOmie.objects.create(
            empresa=self.empresa,
            codigo_lancamento_omie=16001,
            cliente_fornecedor=cliente_a,
            data_lancamento=date(ano_atual, 1, 20),
            natureza="R",
            valor_lancamento=1200,
        )
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse(
                "dashboards:dashboard",
                kwargs={
                    "empresa_slug": self.empresa.slug,
                    "area_slug": "financeiro",
                    "dashboard_slug": "inadimplencia",
                },
            ),
            {
                "_filtrar": "1",
                "periodo": f"ano-{ano_atual}",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total inadimplente")
        self.assertContains(response, "% Inadimplencia")
        self.assertContains(response, "DSO")
        self.assertContains(response, "Recuperado no mes")
        self.assertContains(response, "Aging Schedule")
        self.assertContains(response, "% Inadimplencia")
        self.assertContains(response, "Devedor Alfa")
        self.assertContains(response, "Devedor Beta")
        self.assertContains(response, "data-aging-chart")
        self.assertContains(response, "data-delinquency-trend-chart")
