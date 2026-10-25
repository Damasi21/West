from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.empresas.models import Empresa, EmpresaUsuario, CategoriaOmie, ProjetoOmie, DepartamentoOmie, VendedorOmie
from .filtros_modulo import campos_compartilhados


class FiltrosModuloTests(TestCase):
    def setUp(self):
        self.empresa=Empresa.objects.create(nome="Filtros modulo",cnpj="00.000.000/0001-81")
        self.outra=Empresa.objects.create(nome="Filtros outra",cnpj="00.000.000/0001-82")
        self.usuario=get_user_model().objects.create_user(username="filtros-modulo")
        EmpresaUsuario.objects.create(empresa=self.empresa,usuario=self.usuario,papel="viewer")
        self.client.force_login(self.usuario)
        for codigo in [10,20]:
            ProjetoOmie.objects.create(empresa=self.empresa,codigo=codigo,nome=f"Projeto {codigo}")
            DepartamentoOmie.objects.create(empresa=self.empresa,codigo=str(codigo),descricao=f"Departamento {codigo}")
            VendedorOmie.objects.create(empresa=self.empresa,codigo=codigo,nome=f"Vendedor {codigo}")
        for codigo in ["2.01.01","2.01.02"]:
            CategoriaOmie.objects.create(empresa=self.empresa,codigo=codigo,descricao=codigo)
        self.ano=date.today().year

    def url(self,slug,area="financeiro"):
        return reverse("dashboards:dashboard",args=[self.empresa.slug,area,slug])

    def chave(self,slug,area="financeiro"):
        return f"filtros_dashboard:{self.empresa.pk}:{area}:{slug}"

    def modulo(self,area="financeiro"):
        return f"filtros_modulo:{self.empresa.pk}:{area}"

    def aplicar(self,slug="contas-a-pagar",area="financeiro",**extras):
        dados={"_filtrar":"1","periodo":f"mes-{self.ano}-02","projeto":[f"{self.empresa.pk}:10"],
               "departamento":[f"{self.empresa.pk}:10"],"categoria":[f"{self.empresa.pk}:2.01.01"],**extras}
        return self.client.get(self.url(slug,area),dados)

    def test_dre_abre_competencia_inclusive_sessao_antiga(self):
        self.assertEqual(self.client.get(self.url("dre-gerencial")).context["regime_financeiro"],"competencia")
        sessao=self.client.session
        sessao[self.chave("dre-gerencial")]={"regime_financeiro":"caixa","periodo":f"ano-{self.ano}"}
        sessao.save()
        self.assertEqual(self.client.get(self.url("dre-gerencial")).context["regime_financeiro"],"competencia")
        self.assertEqual(self.client.get(self.url("visao-geral")).context["regime_financeiro"],"caixa")

    def test_dre_preserva_escolha_manual_e_limpar_restaura_competencia(self):
        self.aplicar("dre-gerencial",regime_financeiro="caixa")
        self.assertEqual(self.client.get(self.url("dre-gerencial")).context["regime_financeiro"],"caixa")
        r=self.client.get(self.url("dre-gerencial"),{"limpar_filtros":"1"})
        self.assertEqual(r.context["regime_financeiro"],"competencia")

    def test_sem_ativar_atualizar_so_modifica_dashboard_atual(self):
        self.aplicar(usar_modulo="0")
        self.assertNotIn("categorias",self.client.session.get(self.chave("contas-a-receber"),{}))
        r=self.client.get(self.url("contas-a-receber"))
        self.assertEqual(len(r.context["categorias_selecionadas"]),2)
        self.assertFalse(r.context["filtros_modulo_ativos"])

    def test_compartilha_periodo_projeto_departamento_categoria_em_novo_dashboard(self):
        r=self.aplicar(usar_modulo="1")
        self.assertTrue(r.context["filtros_modulo_ativos"])
        for destino in ["dre-gerencial","visao-geral","contas-a-receber","fluxo-de-caixa","inadimplencia"]:
            r=self.client.get(self.url(destino))
            self.assertEqual(r.context["periodo_selecionado"],f"mes-{self.ano}-02",destino)
            self.assertEqual(r.context["projetos_selecionados"],[f"{self.empresa.pk}:10"],destino)
            self.assertEqual(r.context["departamentos_selecionados"],[f"{self.empresa.pk}:10"],destino)
            self.assertEqual(r.context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.01"],destino)
            self.assertTrue(r.context["filtros_modulo_ativos"])

    def test_nova_alteracao_com_botao_ativo_propaga_e_desativar_isola(self):
        self.aplicar(usar_modulo="1")
        self.aplicar("contas-a-receber",usar_modulo="1",categoria=[f"{self.empresa.pk}:2.01.02"])
        self.assertEqual(self.client.get(self.url("contas-a-pagar")).context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.02"])
        self.aplicar("contas-a-receber",usar_modulo="0",categoria=[f"{self.empresa.pk}:2.01.01"])
        self.assertEqual(self.client.get(self.url("contas-a-pagar")).context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.02"])
        self.assertEqual(self.client.get(self.url("contas-a-receber")).context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.01"])

    def test_regimes_dre_e_visao_geral_independentes_durante_compartilhamento(self):
        self.aplicar("dre-gerencial",regime_financeiro="caixa",usar_modulo="0")
        self.aplicar("visao-geral",regime_financeiro="competencia",usar_modulo="1")
        self.assertNotIn("regime_financeiro",self.client.session[self.modulo()])
        self.assertEqual(self.client.get(self.url("dre-gerencial")).context["regime_financeiro"],"caixa")
        self.assertEqual(self.client.get(self.url("visao-geral")).context["regime_financeiro"],"competencia")
        self.aplicar("dre-gerencial",regime_financeiro="competencia",usar_modulo="1")
        self.assertEqual(self.client.get(self.url("visao-geral")).context["regime_financeiro"],"competencia")

    def test_customizado_e_sessoes_ja_visitadas_sao_atualizadas(self):
        self.aplicar("contas-a-receber",categoria=[f"{self.empresa.pk}:2.01.02"],usar_modulo="0")
        self.aplicar(usar_modulo="1",periodo="personalizado",data_inicio=f"{self.ano}-01-15",data_fim=f"{self.ano}-03-10")
        r=self.client.get(self.url("contas-a-receber"))
        self.assertEqual(r.context["periodo_selecionado"],"personalizado")
        self.assertEqual(r.context["data_inicio"],f"{self.ano}-01-15")
        self.assertEqual(r.context["data_fim"],f"{self.ano}-03-10")
        self.assertEqual(r.context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.01"])

    def test_aprovacao_so_compartilha_categoria_sem_apagar_periodo_e_projeto(self):
        self.aplicar(usar_modulo="1")
        self.client.get(self.url("aprovacao-de-pagamentos"),{"_filtrar":"1","usar_modulo":"1","categoria":[f"{self.empresa.pk}:2.01.02"]})
        r=self.client.get(self.url("contas-a-pagar"))
        self.assertEqual(r.context["periodo_selecionado"],f"mes-{self.ano}-02")
        self.assertEqual(r.context["projetos_selecionados"],[f"{self.empresa.pk}:10"])
        self.assertEqual(r.context["categorias_selecionadas"],[f"{self.empresa.pk}:2.01.02"])
        self.assertContains(self.client.get(self.url("aprovacao-de-pagamentos")),"data-module-share-toggle")

    def test_vendedor_apenas_nos_compativeis_e_tela_sem_vendedor_nao_apaga_selecao(self):
        self.aplicar("faturamento","comercial",usar_modulo="1",vendedor=[f"{self.empresa.pk}:10"])
        self.assertNotIn("vendedores",self.client.session[self.chave("analise-de-clientes","comercial")])
        r=self.client.get(self.url("desempenho-de-vendedores","comercial"))
        self.assertEqual(r.context["vendedores_selecionados"],[f"{self.empresa.pk}:10"])
        self.aplicar("analise-de-clientes","comercial",usar_modulo="1",periodo=f"mes-{self.ano}-05")
        r=self.client.get(self.url("desempenho-de-vendedores","comercial"))
        self.assertEqual(r.context["vendedores_selecionados"],[f"{self.empresa.pk}:10"])
        self.assertEqual(r.context["periodo_selecionado"],f"mes-{self.ano}-05")

    def test_escopo_modulo_empresa_usuario_e_valores_validos(self):
        self.aplicar(usar_modulo="1",projeto=[f"{self.empresa.pk}:10",f"{self.outra.pk}:20"])
        self.assertNotIn(self.modulo("comercial"),self.client.session)
        self.assertNotIn(f"filtros_modulo:{self.outra.pk}:financeiro",self.client.session)
        self.assertEqual(self.client.session[self.modulo()]["projetos"],[f"{self.empresa.pk}:10"])
        self.client.logout()
        self.client.force_login(self.usuario)
        self.assertNotIn(self.modulo(),self.client.session)

    def test_limpar_com_compartilhamento_ativo_propaga_reset(self):
        self.aplicar(usar_modulo="1")
        self.client.get(self.url("contas-a-pagar"),{"limpar_filtros":"1","usar_modulo":"1"})
        r=self.client.get(self.url("contas-a-receber"))
        self.assertEqual(r.context["periodo_selecionado"],f"ano-{self.ano}")
        self.assertEqual(len(r.context["categorias_selecionadas"]),2)
        self.assertEqual(len(r.context["projetos_selecionados"]),2)

    def test_regime_nunca_esta_na_lista_de_compartilhamento(self):
        for area,slug in [("financeiro","dre-gerencial"),("financeiro","visao-geral"),("comercial","faturamento")]:
            self.assertNotIn("regime_financeiro",campos_compartilhados(area,slug))
        self.assertNotIn("projetos",campos_compartilhados("compras","budget"))
