import importlib
import json
from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.empresas.models import (
    ContaCorrenteOmie, ContaPagarOmie, Empresa, EmpresaUsuario, IntegracaoOmie,
    RecebimentoNfeOmie, SincronizacaoOmie,
)
from apps.empresas.omie import _salvar_recebimentos_nfe, consultar_recebimentos_nfe, executar_sincronizacao_omie
from apps.empresas.recebimentos_nfe import atualizar_titulos_recebimento, codigos_titulos_recebimento
from .aprovacao_pagamentos_services import _linhas_pagamentos
from .pagamento_nfe_services import notas_das_contas


@override_settings(ENABLE_PAYMENT_APPROVAL_DASHBOARD=True)
class NotaPagamentoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa NF", cnpj="00.000.000/0001-91")
        self.outra = Empresa.objects.create(nome="Outra NF", cnpj="00.000.000/0001-92")
        self.usuario = get_user_model().objects.create_user(username="leitor-nf")
        self.vinculo = EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario, papel="viewer")
        self.conta = ContaPagarOmie.objects.create(
            empresa=self.empresa, codigo_lancamento_omie=1234,
            codigo_cliente_fornecedor=88, data_previsao=date(2026, 10, 24),
            valor_documento=150, numero_documento_fiscal="456",
        )
        self.nota = RecebimentoNfeOmie.objects.create(
            empresa=self.empresa, codigo_recebimento=987, numero_nfe="000456",
            serie_nfe="1", valor_nfe=150, codigo_fornecedor=88,
            parcelas={"parcelasLista": [{"nIdTitulo": 1234, "nSequencia": 1, "vParcela": 150, "dVencimento": "24/10/2026"}]},
            cabec={"cRazaoSocial": "Fornecedor NF"},
        )
        atualizar_titulos_recebimento(self.nota)
        self.url = reverse("dashboards:nota_pagamento", args=[self.empresa.slug, self.conta.pk])
        self.client.force_login(self.usuario)

    def test_pagina_exibe_nota_parcelas_sem_chamar_api(self):
        with patch("apps.empresas.omie.urlopen", side_effect=AssertionError("Nao consultar API na visualizacao")):
            response = self.client.get(self.url)
        self.assertContains(response, "NF 000456")
        self.assertContains(response, "Fornecedor NF")
        self.assertContains(response, "1234")
        self.assertContains(response, "nao substitui o XML ou o DANFE original")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_linha_tem_numero_e_link_para_empresa_da_conta(self):
        contas = ContaPagarOmie.objects.filter(pk=self.conta.pk).select_related("empresa")
        linha = _linhas_pagamentos(contas)[0]
        self.assertEqual(linha["numero_nf"], "000456")
        self.assertEqual(linha["url_nf"], self.url)

    def test_mesmo_codigo_em_empresas_diferentes_nao_cruza_notas(self):
        outra_nota = RecebimentoNfeOmie.objects.create(
            empresa=self.outra, codigo_recebimento=987, numero_nfe="OUTRA",
            parcelas=self.nota.parcelas,
        )
        atualizar_titulos_recebimento(outra_nota)
        outra_conta = ContaPagarOmie.objects.create(empresa=self.outra, codigo_lancamento_omie=1234)
        mapa = notas_das_contas([self.conta, outra_conta])
        self.assertEqual(mapa[self.conta.pk], self.nota)
        self.assertEqual(mapa[outra_conta.pk], outra_nota)
        url = reverse("dashboards:nota_pagamento", args=[self.empresa.slug, outra_conta.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboards:nota_pagamento", args=[self.outra.slug, outra_conta.pk])).status_code, 404)

    def test_vinculo_ambiguo_nao_abre_nota_arbitraria(self):
        outra = RecebimentoNfeOmie.objects.create(empresa=self.empresa, codigo_recebimento=988, parcelas=self.nota.parcelas)
        atualizar_titulos_recebimento(outra)
        self.assertEqual(notas_das_contas([self.conta]), {})
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_fornecedor_divergente_nao_libera_documento(self):
        self.nota.codigo_fornecedor = 99
        self.nota.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_nf_sem_vinculo_mostra_numero_sem_link(self):
        self.nota.titulos_financeiros.all().delete()
        linha = _linhas_pagamentos(ContaPagarOmie.objects.filter(pk=self.conta.pk).select_related("empresa"))[0]
        self.assertEqual(linha["numero_nf"], "456")
        self.assertEqual(linha["url_nf"], "")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_sem_numero_mostra_traco(self):
        self.nota.titulos_financeiros.all().delete()
        self.conta.numero_documento_fiscal = ""
        self.conta.save()
        linha = _linhas_pagamentos(ContaPagarOmie.objects.filter(pk=self.conta.pk).select_related("empresa"))[0]
        self.assertEqual(linha["numero_nf"], "-")

    def test_nota_e_conta_inativas_nao_abrem(self):
        self.nota.ativo_omie = False
        self.nota.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.nota.ativo_omie = True
        self.nota.save()
        self.conta.ativo_omie = False
        self.conta.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_permissao_dashboard_e_revalidada(self):
        self.vinculo.areas_permitidas = ["compras"]
        self.vinculo.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.vinculo.areas_permitidas = ["financeiro"]
        self.vinculo.dashboards_permitidos = ["financeiro:dre-gerencial"]
        self.vinculo.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(ENABLE_PAYMENT_APPROVAL_DASHBOARD=False)
    def test_dashboard_desativado_nao_expoe_nota(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_login_obrigatorio_e_apenas_get(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_conta_oculta_no_financeiro_nao_expoe_nota(self):
        banco = ContaCorrenteOmie.objects.create(empresa=self.empresa, codigo_omie=55, nao_fluxo=True, nao_resumo=True)
        self.conta.conta_corrente = banco
        self.conta.id_conta_corrente = 55
        self.conta.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_nao_executa_html_dos_dados_omie(self):
        self.nota.cabec = {"cRazaoSocial": "<script>alert(1)</script>"}
        self.nota.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_indice_usa_uma_consulta_para_lote(self):
        with self.assertNumQueries(1):
            self.assertEqual(notas_das_contas([self.conta])[self.conta.pk], self.nota)

    def test_sincronizacao_substitui_vinculos_sem_depender_da_ordem_das_contas(self):
        _salvar_recebimentos_nfe(self.empresa, [{
            "cabec": {"nIdReceb": 987, "cNumeroNFe": "456"},
            "parcelas": {"parcelasLista": [{"nIdTitulo": "5678"}, {"nIdTitulo": 5678}]},
        }])
        self.assertEqual(list(self.nota.titulos_financeiros.values_list("codigo_lancamento_omie", flat=True)), [5678])
        conta_nova = ContaPagarOmie.objects.create(empresa=self.empresa, codigo_lancamento_omie=5678)
        self.assertEqual(notas_das_contas([conta_nova])[conta_nova.pk], self.nota)
        _salvar_recebimentos_nfe(self.empresa, [{"cabec": {"nIdReceb": 987}, "parcelas": {}}])
        self.assertFalse(self.nota.titulos_financeiros.exists())

    def test_codigos_invalidos_ignorados(self):
        self.assertEqual(codigos_titulos_recebimento({"parcelasLista": [None, {}, {"nIdTitulo": -1}, {"nIdTitulo": True}, {"nIdTitulo": "x"}, {"nIdTitulo": 0}, {"nIdTitulo": 2**64}, {"nIdTitulo": "1234"}]}), {1234})
        self.assertEqual(codigos_titulos_recebimento([]), set())

    def test_migracao_reaproveita_parcelas_ja_salvas(self):
        self.nota.titulos_financeiros.all().delete()
        migracao = importlib.import_module("apps.empresas.migrations.0054_recebimentonfetitulos")
        migracao.preencher_vinculos(apps, SimpleNamespace(connection=connection))
        migracao.preencher_vinculos(apps, SimpleNamespace(connection=connection))
        self.assertEqual(self.nota.titulos_financeiros.count(), 1)

    def test_financeiro_tambem_sincroniza_recebimentos(self):
        integracao = IntegracaoOmie(empresa=self.empresa, app_key="teste")
        integracao.definir_app_secret("segredo")
        integracao.save()
        sincronizacao = SincronizacaoOmie.objects.create(empresa=self.empresa, recurso="financeiro")
        nomes = (
            "clientes", "projetos", "departamentos", "categorias", "tipos_conta_corrente",
            "contas_correntes", "contas_pagar", "contas_receber", "movimentos_financeiros",
            "pesq_titulos_financeiros", "lancamentos_conta_corrente", "resumo_financas",
        )
        with ExitStack() as stack:
            for nome in nomes:
                stack.enter_context(patch(f"apps.empresas.omie.consultar_{nome}", return_value={}))
            consultar = stack.enter_context(patch("apps.empresas.omie.consultar_recebimentos_nfe", return_value={
                "nTotPaginas": 1, "nTotRegistros": 1,
                "recebimentos": [{"cabec": {"nIdReceb": 987}, "parcelas": self.nota.parcelas}],
            }))
            executar_sincronizacao_omie(sincronizacao.pk)
        consultar.assert_called_once()
        sincronizacao.refresh_from_db()
        self.assertEqual(sincronizacao.status, "concluida", sincronizacao.erro)
        self.assertEqual(self.nota.titulos_financeiros.count(), 1)

    @patch("apps.empresas.omie.consultar_recebimento_nfe")
    @patch("apps.empresas.omie.urlopen")
    def test_api_preserva_cabecalho_e_normaliza_paginacao(self, abrir, detalhe):
        integracao = IntegracaoOmie(empresa=self.empresa, app_key="teste")
        integracao.definir_app_secret("segredo")
        integracao.save()
        abrir.return_value.__enter__.return_value.read.return_value = json.dumps({
            "nPagina": 1, "nTotalPaginas": 3, "nTotalRegistros": 250,
            "recebimentos": [{"cabec": {"nIdReceb": 987, "cNumeroNFe": "456"}}],
        }).encode()
        detalhe.return_value = {"cabec": {"nIdReceb": 987}, "parcelas": self.nota.parcelas}
        dados = consultar_recebimentos_nfe(integracao, 1)
        self.assertEqual(dados["nTotPaginas"], 3)
        self.assertEqual(dados["nTotRegistros"], 250)
        self.assertEqual(dados["recebimentos"][0]["cabec"]["cNumeroNFe"], "456")
        self.assertEqual(dados["recebimentos"][0]["parcelas"], self.nota.parcelas)
