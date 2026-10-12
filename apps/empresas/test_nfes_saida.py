import json
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from .models import CadastroOmie, Empresa, IntegracaoOmie, NfeSaidaItemOmie, NfeSaidaOmie, ProdutoOmie, SincronizacaoOmie
from .omie import OmieAPIError, _salvar_nfes_saida, consultar_nfes_saida, executar_sincronizacao_omie


class NfeSaidaOmieTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="NF Saida", cnpj="00.000.000/0001-89")
        self.integracao = IntegracaoOmie(empresa=self.empresa, app_key="test-key")
        self.integracao.definir_app_secret("test-secret")
        self.integracao.save()
        self.nota = {
            "compl": {"nIdNF": 3037133684, "nIdPedido": 3037132866,
                      "cChaveNFe": "35201013835876000108550010000000801475879906", "cCodCateg": "1.01.03"},
            "ide": {"nNF": "00000080", "serie": "001", "tpNF": "1", "tpAmb": "1", "mod": "55",
                    "dEmi": "14/10/2020", "dReg": "14/10/2020", "dSaiEnt": "14/10/2020", "dCan": "", "cDeneg": "N"},
            "nfDestInt": {"nCodCli": 3037132752, "cRazao": "PEG BABY LTDA", "cnpj_cpf": "14.016.502/0001-15"},
            "info": {"cImpAPI": "N"},
            "total": {"ICMSTot": {"vNF": 8780.8, "vProd": 8780.8, "vDesc": 0}},
            "titulos": [],
            "det": [
                {"nfProdInt": {"nCodItem": 3037133403, "nCodProd": 3037132647},
                 "prod": {"cProd": "PRD00001", "xProd": "RESIDUO DE POLIETILENO", "qCom": 3848,
                          "uCom": "KG", "vUnCom": 2.1, "vProd": 8080.8, "vTotItem": 8080.8, "CFOP": "5.102", "NCM": "3915.90.00"}},
                {"nfProdInt": {"nCodItem": 3037133608, "nCodProd": 3037133511},
                 "prod": {"cProd": "PRD00002", "xProd": "FITA FRONTAL", "qCom": 7,
                          "uCom": "UN", "vUnCom": 100, "vProd": 700, "vTotItem": 700}},
            ],
        }

    def test_salva_nota_importada_e_itens_sem_duplicar(self):
        cliente = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=3037132752)
        produto = ProdutoOmie.objects.create(empresa=self.empresa, codigo_produto=3037132647)
        _salvar_nfes_saida(self.empresa, [self.nota])
        _salvar_nfes_saida(self.empresa, [self.nota])
        nota = NfeSaidaOmie.objects.get(empresa=self.empresa)
        self.assertEqual(nota.valor_total, Decimal("8780.8"))
        self.assertEqual(nota.numero, "00000080")
        self.assertEqual(nota.data_emissao, date(2020, 10, 14))
        self.assertEqual(nota.cliente, cliente)
        self.assertEqual(nota.dados_originais, self.nota)
        self.assertFalse(nota.importado_api)
        self.assertEqual(nota.itens.count(), 2)
        item = nota.itens.get(sequencia=1)
        self.assertEqual(item.quantidade, Decimal("3848"))
        self.assertEqual(item.valor_unitario, Decimal("2.1"))
        self.assertEqual(item.produto, produto)
        self.assertEqual(item.cfop, "5.102")

    def test_atualiza_cancelamento_e_retira_item_ausente(self):
        _salvar_nfes_saida(self.empresa, [self.nota])
        self.nota["ide"]["dCan"] = "15/10/2020"
        self.nota["det"] = self.nota["det"][:1]
        _salvar_nfes_saida(self.empresa, [self.nota])
        nota = NfeSaidaOmie.objects.get(empresa=self.empresa)
        self.assertEqual(nota.data_cancelamento, date(2020, 10, 15))
        self.assertEqual(nota.itens.filter(ativo_omie=True).count(), 1)
        self.assertEqual(nota.itens.filter(ativo_omie=False).count(), 1)

    def test_isola_empresa_e_ignora_entrada(self):
        outra = Empresa.objects.create(nome="Outra NF", cnpj="00.000.000/0001-88")
        _salvar_nfes_saida(self.empresa, [self.nota])
        _salvar_nfes_saida(outra, [self.nota])
        self.assertEqual(NfeSaidaOmie.objects.count(), 2)
        self.nota["ide"]["tpNF"] = "0"
        self.assertEqual(_salvar_nfes_saida(self.empresa, [self.nota]), 0)
        self.assertEqual(NfeSaidaItemOmie.objects.count(), 4)

    def test_identificador_ausente_nao_produz_importacao_parcial(self):
        self.nota["compl"].pop("nIdNF")
        with self.assertRaises(OmieAPIError):
            _salvar_nfes_saida(self.empresa, [self.nota])
        self.assertFalse(NfeSaidaOmie.objects.exists())

    def test_ignora_nota_sem_cfop_permitido(self):
        for codigo in ("5901", "7101", "", "invalido"):
            with self.subTest(cfop=codigo):
                nota = deepcopy(self.nota)
                for item in nota["det"]:
                    item["prod"]["CFOP"] = codigo
                self.assertEqual(_salvar_nfes_saida(self.empresa, [nota]), 0)
        self.assertFalse(NfeSaidaOmie.objects.exists())
        self.assertFalse(NfeSaidaItemOmie.objects.exists())

    def test_importa_nota_mista_mas_vendas_excluem_remessa(self):
        self.nota["det"][1]["prod"]["CFOP"] = "5901"
        _salvar_nfes_saida(self.empresa, [self.nota])
        nota = self.empresa.nfes_saida_omie.vendas().get()
        self.assertEqual(nota.valor_venda, Decimal("8080.8"))
        self.assertEqual(nota.itens.count(), 2)
        self.assertEqual(nota.itens.vendas().count(), 1)

    def test_configuracao_ativa_da_empresa_controla_importacao(self):
        cfop = self.empresa.cfops_venda_omie.get(codigo="5102")
        cfop.ativo = False
        cfop.save(update_fields=["ativo"])
        self.assertEqual(_salvar_nfes_saida(self.empresa, [self.nota]), 0)
        self.empresa.cfops_venda_omie.create(codigo="5124", descricao="Operacao adicional")
        self.nota["det"][0]["prod"]["CFOP"] = "5.124"
        self.assertGreater(_salvar_nfes_saida(self.empresa, [self.nota]), 0)
        self.assertEqual(self.empresa.nfes_saida_omie.count(), 1)

    @patch("apps.empresas.omie._abrir_requisicao_omie")
    def test_consulta_saida_com_itens_periodo_e_sem_filtro_de_origem(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value = json.dumps({"nfCadastro": [self.nota]}).encode()
        consultar_nfes_saida(self.integracao, 2, inicio=date(2020, 10, 1), fim=date(2020, 10, 31))
        request = abrir.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["call"], "ListarNF")
        params = payload["param"][0]
        self.assertEqual(params["pagina"], 2)
        self.assertEqual(params["tpNF"], "1")
        self.assertEqual(params["cApenasResumo"], "N")
        self.assertNotIn("apenas_importado_api", params)
        self.assertEqual(params["dEmiInicial"], "01/10/2020")
        self.assertEqual(params["dEmiFinal"], "31/10/2020")

    def test_worker_importa_paginas_em_comercial_e_master(self):
        consultas = (
            "clientes", "projetos", "departamentos", "vendedores", "produtos", "produtos_fornecedores",
            "locais_estoque", "posicoes_estoque", "saldos_pendentes_estoque", "pedidos_compra", "recebimentos_nfe",
            "categorias", "servicos", "tipos_conta_corrente", "contas_correntes", "contratos", "ordens_servico",
            "nfses", "contas_pagar", "contas_receber", "movimentos_financeiros", "pesq_titulos_financeiros",
            "lancamentos_conta_corrente", "pedidos", "resumo_financas",
        )
        with ExitStack() as stack:
            for nome in consultas:
                stack.enter_context(patch(f"apps.empresas.omie.consultar_{nome}", return_value={}))
            for recurso in ("comercial", "completa", "financeiro"):
                with self.subTest(recurso=recurso):
                    segunda = deepcopy(self.nota)
                    segunda["compl"]["nIdNF"] = 3037133685
                    mock = stack.enter_context(patch("apps.empresas.omie.consultar_nfes_saida", side_effect=[
                        {"total_de_paginas": 2, "total_de_registros": 2, "nfCadastro": [self.nota]},
                        {"total_de_paginas": 2, "total_de_registros": 2, "nfCadastro": [segunda]},
                    ]))
                    sync = SincronizacaoOmie.objects.create(empresa=self.empresa, recurso=recurso)
                    executar_sincronizacao_omie(sync.pk)
                    sync.refresh_from_db()
                    self.assertEqual(sync.status, "concluida", sync.erro)
                    self.assertEqual(mock.call_count, 0 if recurso == "financeiro" else 2)
            self.assertEqual(self.empresa.nfes_saida_omie.count(), 2)
            self.assertEqual(self.empresa.itens_nfe_saida_omie.count(), 4)
