from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from apps.empresas.models import Empresa, EmpresaUsuario, ProjetoOmie, DepartamentoOmie, CategoriaOmie, ContaPagarOmie, MovimentoFinanceiroOmie
from apps.compras.models import BudgetConfiguracaoCompra, BudgetLimiteCompra
from .budget_services import budget_compras


class BudgetModulosTests(TestCase):
    def setUp(self):
        self.usuario=get_user_model().objects.create_user(username='budget-gestor')
        self.empresa=Empresa.objects.create(nome='Budget teste',cnpj='11111111000111')
        EmpresaUsuario.objects.create(empresa=self.empresa,usuario=self.usuario,papel='gestor')
        self.client.force_login(self.usuario)
        self.config=BudgetConfiguracaoCompra.objects.create(empresa=self.empresa,tipos_controle=['produto','fornecedor','projeto','departamento','categoria'])
        ProjetoOmie.objects.create(empresa=self.empresa,codigo=11,nome='Projeto A')
        DepartamentoOmie.objects.create(empresa=self.empresa,codigo='DEP1',descricao='Departamento A')
        CategoriaOmie.objects.create(empresa=self.empresa,codigo='2.01.01',descricao='Categoria A',conta_despesa=True)
        for tipo,codigo in [('projeto','11'),('departamento','DEP1'),('categoria','2.01.01'),('fornecedor','909')]:
            BudgetLimiteCompra.objects.create(empresa=self.empresa,configuracao=self.config,tipo_controle=tipo,referencia_codigo=codigo,referencia_nome=tipo,limite_compra=1000)
        self.financeiro=reverse('dashboards:budget_financeiro',args=[self.empresa.slug])
        self.compras=reverse('dashboards:budget',args=[self.empresa.slug])

    def conta(self,codigo=1,pago=200,**kwargs):
        dados=dict(data_previsao=date(2026,2,10),data_emissao=date(2026,1,10),valor_documento=1000,codigo_projeto=11,codigo_categoria='2.01.01',distribuicao=[{'cCodDep':'DEP1','nPerDep':100}])
        dados.update(kwargs)
        conta=ContaPagarOmie.objects.create(empresa=self.empresa,codigo_lancamento_omie=codigo,**dados)
        if pago is not None:
            MovimentoFinanceiroOmie.objects.create(empresa=self.empresa,codigo_titulo=codigo,natureza='P',valor_pago=pago,data_pagamento=date(2026,3,10))
        return conta

    def calcular(self,dimensao='projeto',periodo='mes-2026-02',**filtros):
        return budget_compras(self.empresa,periodo,'','',[self.empresa.pk],dimensao,area_slug='financeiro',**filtros)

    def test_cards_configuracao_separados_e_novo_dashboard_no_financeiro(self):
        compras=self.client.get(self.compras)
        financeiro=self.client.get(self.financeiro)
        self.assertEqual({s['tipo'] for s in compras.context['secoes']},{'produto','fornecedor'})
        self.assertEqual({s['tipo'] for s in financeiro.context['secoes']},{'projeto','departamento','categoria'})
        response=self.client.get(reverse('dashboards:dashboard',args=[self.empresa.slug,'financeiro','budget']))
        self.assertEqual(response.status_code,200)
        self.assertEqual({o['valor'] for o in response.context['budget']['opcoes_dimensao']},{'projeto','departamento','categoria'})
        self.assertContains(response,self.financeiro)
        self.assertContains(response,'Configurar Budget')

    def test_periodo_pela_previsao_mas_consumo_so_valor_pago(self):
        self.conta()
        self.assertEqual(self.calcular()['total_gasto'],Decimal('200'))
        self.assertEqual(self.calcular(periodo='mes-2026-03')['total_gasto'],0)
        self.assertEqual(self.calcular('categoria')['total_gasto'],Decimal('200'))

    def test_aberto_e_quitado_sem_movimento_de_pagamento_nao_sao_inferidos(self):
        self.conta(pago=None,valor_a_pagar=1000,status_titulo='ABERTO')
        self.conta(codigo=2,pago=None,valor_a_pagar=0,status_titulo='PAGO')
        self.assertEqual(self.calcular()['total_gasto'],0)

    def test_movimentos_cancelados_sem_data_ou_de_receita_nao_consumem(self):
        self.conta(codigo=1);self.conta(codigo=2);self.conta(codigo=3)
        MovimentoFinanceiroOmie.objects.filter(codigo_titulo=1).update(status=' cancelado ')
        MovimentoFinanceiroOmie.objects.filter(codigo_titulo=2).update(data_pagamento=None)
        MovimentoFinanceiroOmie.objects.filter(codigo_titulo=3).update(natureza='R')
        self.assertEqual(self.calcular()['total_gasto'],0)

    def test_rateios_departamento_categoria_e_filtros_combinados(self):
        self.conta(categorias=[{'codigo_categoria':'2.01.01','percentual':40},{'codigo_categoria':'2.01.02','percentual':60}],distribuicao=[{'cCodDep':'DEP1','nPerDep':25},{'cCodDep':'DEP2','nPerDep':75}])
        self.assertEqual(self.calcular('departamento')['total_gasto'],Decimal('50'))
        self.assertEqual(self.calcular('categoria')['total_gasto'],Decimal('80'))
        self.assertEqual(self.calcular('categoria',departamentos=[f'{self.empresa.pk}:DEP1'])['total_gasto'],Decimal('20'))
        self.assertEqual(self.calcular('projeto',projetos=[f'{self.empresa.pk}:999'])['total_gasto'],0)

    def test_consolidacao_mesmos_codigos_nao_duplica_gastos(self):
        self.conta()
        outra=Empresa.objects.create(nome='Outra Budget',cnpj='22222222000122')
        cfg=BudgetConfiguracaoCompra.objects.create(empresa=outra,tipos_controle=['projeto'])
        BudgetLimiteCompra.objects.create(empresa=outra,configuracao=cfg,tipo_controle='projeto',referencia_codigo='11',limite_compra=500)
        ContaPagarOmie.objects.create(empresa=outra,codigo_lancamento_omie=1,codigo_projeto=11,data_previsao=date(2026,2,10),valor_documento=1000)
        MovimentoFinanceiroOmie.objects.create(empresa=outra,codigo_titulo=1,natureza='P',valor_pago=50,data_pagamento=date(2026,3,10))
        dados=budget_compras(self.empresa,'mes-2026-02','','',[self.empresa.pk,outra.pk],'projeto',area_slug='financeiro')
        self.assertEqual(dados['total_budget'],1500)
        self.assertEqual(dados['total_gasto'],250)
        filtrado=budget_compras(self.empresa,'mes-2026-02','','',[self.empresa.pk,outra.pk],'projeto',area_slug='financeiro',projetos=[f'{self.empresa.pk}:11'])
        self.assertEqual(filtrado['total_budget'],1000)
        self.assertEqual(filtrado['total_gasto'],200)

    def test_orcamentos_mensais_somam_so_meses_do_periodo_sem_duplicar_pago(self):
        self.conta();self.config.periodicidades_controle={'projeto':'mensal'};self.config.save()
        for mes,valor in [(2,1000),(3,2000)]:
            BudgetLimiteCompra.objects.create(empresa=self.empresa,configuracao=self.config,tipo_controle='projeto',referencia_codigo='11',mes=mes,limite_compra=valor)
        self.assertEqual(self.calcular()['total_budget'],1000)
        anual=self.calcular(periodo='ano-2026')
        self.assertEqual(anual['total_budget'],3000)
        self.assertEqual(anual['total_gasto'],200)
        self.assertEqual(anual['total_itens'],1)

    def test_salvar_ou_ativar_financeiro_preserva_controles_e_limites_compras(self):
        self.client.post(self.financeiro,{'acao':'definir_tipos','tipos_controle':['categoria']})
        self.config.refresh_from_db()
        self.assertEqual(set(self.config.tipos_selecionados),{'produto','fornecedor','categoria'})
        self.client.post(self.financeiro,{'acao':'salvar_limites','tipo_ativo':'categoria','limite_categoria_2.01.01':'200,00'})
        self.assertEqual(BudgetLimiteCompra.objects.get(empresa=self.empresa,tipo_controle='fornecedor').limite_compra,1000)
        self.assertEqual(BudgetLimiteCompra.objects.get(empresa=self.empresa,tipo_controle='categoria').limite_compra,200)

    def test_post_de_outro_modulo_nao_altera_limites(self):
        self.client.post(self.compras,{'acao':'reverter_budget','tipo_controle':'categoria'})
        self.client.post(self.financeiro,{'acao':'reverter_budget','tipo_controle':'fornecedor'})
        self.assertEqual(BudgetLimiteCompra.objects.filter(empresa=self.empresa).count(),4)
        self.assertTrue(all(l.limite_compra==1000 for l in BudgetLimiteCompra.objects.filter(empresa=self.empresa)))
        response=self.client.get(reverse('dashboards:dashboard',args=[self.empresa.slug,'compras','budget']),{'_filtrar':'1','budget_dimensao':'categoria'})
        self.assertNotEqual(response.context['budget']['dimensao'],'categoria')

    def test_visualizador_ve_dashboard_autorizado_mas_nao_configura(self):
        vinculo=EmpresaUsuario.objects.get(empresa=self.empresa,usuario=self.usuario)
        vinculo.papel=EmpresaUsuario.Papel.VISUALIZADOR;vinculo.areas_permitidas=['financeiro'];vinculo.dashboards_permitidos=['financeiro:budget'];vinculo.save()
        self.assertEqual(self.client.get(self.financeiro).status_code,403)
        self.assertEqual(self.client.get(reverse('dashboards:dashboard',args=[self.empresa.slug,'financeiro','budget'])).status_code,200)
        self.assertEqual(self.client.get(reverse('dashboards:dashboard',args=[self.empresa.slug,'compras','budget'])).status_code,404)

    def test_sem_previsao_nao_substitui_pelo_vencimento(self):
        self.conta(data_previsao=None,data_vencimento=date(2026,2,10))
        self.assertEqual(self.calcular()['total_gasto'],0)
