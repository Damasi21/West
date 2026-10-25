import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import CadastroOmie, CategoriaOmie, ContaCorrenteOmie, DepartamentoOmie, Empresa, EmpresaUsuario, IntegracaoOmie
from .contas_pagar_envio import dados_inclusao, preparar_envio, executar_envio, publicar_envio
from .contas_pagar_omie import ResultadoOmieIncerto, incluir_conta_pagar, incluir_contas_pagar_lote, consultar_conta_por_integracao
from .models import ContaPagarLocal, AnexoContaPagarLocal, EnvioContasPagarLocal


class EnvioContasPagarTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Envio empresa", cnpj="00.000.000/0001-51")
        self.outra = Empresa.objects.create(nome="Outra envio", cnpj="00.000.000/0001-52")
        User = get_user_model()
        self.a = User.objects.create_user(username="autor-a", first_name="Autor A")
        self.b = User.objects.create_user(username="autor-b", first_name="Autor B")
        self.gestor = User.objects.create_user(username="gestor-envio")
        for u, papel in [(self.a, "viewer"), (self.b, "viewer"), (self.gestor, "gestor")]:
            EmpresaUsuario.objects.create(empresa=self.empresa, usuario=u, papel=papel)
        self.fornecedor = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=11, nome_fantasia="Fornecedor envio", tipo="fornecedor")
        self.categoria = CategoriaOmie.objects.create(empresa=self.empresa, codigo="2.01.01", descricao="Materiais", conta_despesa=True)
        self.departamento = DepartamentoOmie.objects.create(empresa=self.empresa, codigo="DEP", descricao="Administracao")
        self.banco = ContaCorrenteOmie.objects.create(empresa=self.empresa, codigo_omie=91, descricao="Banco envio")
        self.integracao = IntegracaoOmie(empresa=self.empresa, app_key="key-teste")
        self.integracao.definir_app_secret("segredo-teste")
        self.integracao.save()
        self.lista = reverse("dashboards:listar_contas_pagar_locais", args=[self.empresa.slug])
        self.cadastro = reverse("dashboards:cadastrar_conta_pagar_local", args=[self.empresa.slug])
        self.enviar = reverse("dashboards:enviar_contas_pagar_locais", args=[self.empresa.slug])
        self.client.force_login(self.a)

    def conta(self, usuario=None, **extra):
        dados = dict(empresa=self.empresa, criado_por=usuario or self.a, fornecedor=self.fornecedor,
                     categoria=self.categoria, departamento=self.departamento, conta_corrente=self.banco,
                     descricao="Conta propria", valor=Decimal("1234.56"), data_emissao=timezone.localdate(),
                     data_vencimento=timezone.localdate()+timedelta(days=5), forma_pagamento="pix", documento="NF123")
        dados.update(extra)
        return ContaPagarLocal.objects.create(**dados)

    def post(self, ids, acao="enviar", **extra):
        return self.client.post(self.enviar, json.dumps(dict(ids=ids, acao=acao, confirmar=True, **extra)), content_type="application/json")

    def editar_dados(self, conta, **extra):
        dados = {campo: getattr(conta, campo+"_id") if campo in {"fornecedor", "categoria", "departamento", "conta_corrente"} else getattr(conta, campo) for campo in ["fornecedor", "descricao", "categoria", "departamento", "conta_corrente", "valor", "data_emissao", "data_vencimento", "forma_pagamento", "documento", "observacoes"]}
        dados.update(conta_id=conta.pk, token=str(conta.token_cadastro), **extra)
        return dados

    def test_visualizador_so_lista_proprias_e_gestor_lista_todas(self):
        propria = self.conta(descricao="Exclusiva A")
        outra = self.conta(self.b, descricao="Exclusiva B")
        html = self.client.get(self.lista).json()["html"]
        self.assertIn("Exclusiva A", html)
        self.assertNotIn("Exclusiva B", html)
        self.assertIn("Meus cadastros", html)
        self.client.force_login(self.gestor)
        html = self.client.get(self.lista).json()["html"]
        self.assertIn("Exclusiva A", html)
        self.assertIn("Exclusiva B", html)
        self.assertIn("Autor B", html)
        self.assertIn("Todos os cadastros", html)

    def test_visualizador_nao_le_edita_envia_ou_baixa_anexo_alheio(self):
        conta = self.conta(self.b)
        anexo = AnexoContaPagarLocal.objects.create(conta=conta, arquivo="privado/teste.pdf", nome_original="teste.pdf", tamanho=10)
        self.assertEqual(self.client.get(self.cadastro, {"conta_id": conta.pk}).status_code, 404)
        self.assertEqual(self.client.post(self.cadastro, self.editar_dados(conta)).status_code, 404)
        self.assertEqual(self.post([conta.pk]).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboards:baixar_anexo_conta_local", args=[self.empresa.slug, anexo.pk])).status_code, 404)
        self.assertFalse(EnvioContasPagarLocal.objects.exists())

    def test_gestor_pode_editar_rascunho_de_outro_autor(self):
        conta = self.conta(self.b)
        self.client.force_login(self.gestor)
        r = self.client.post(self.cadastro, self.editar_dados(conta, descricao="Corrigida pelo gestor"))
        self.assertEqual(r.status_code, 200)
        conta.refresh_from_db()
        self.assertEqual(conta.descricao, "Corrigida pelo gestor")
        self.assertEqual(conta.criado_por, self.b)

    def test_payload_inclui_campos_obrigatorios_rateio_e_nao_realiza_baixa(self):
        conta = self.conta()
        dados = dados_inclusao(conta)
        self.assertEqual(dados["codigo_cliente_fornecedor"], 11)
        self.assertEqual(dados["id_conta_corrente"], 91)
        self.assertEqual(dados["valor_documento"], 1234.56)
        self.assertEqual(dados["codigo_lancamento_integracao"], conta.codigo_integracao)
        self.assertEqual(dados["data_previsao"], dados["data_vencimento"])
        self.assertEqual(dados["distribuicao"][0]["nPerDep"], 100)
        self.assertEqual(dados["baixar_documento"], "N")
        self.assertNotIn("pagamento", dados)
        self.assertNotIn("app_secret", dados)
        self.assertNotIn("anexos", dados)

    def test_sem_banco_ou_cadastro_de_outra_empresa_nao_prepara_envio(self):
        conta = self.conta(conta_corrente=None)
        with self.assertRaises(ValidationError):
            preparar_envio(self.a, self.empresa, [conta.pk])
        banco = ContaCorrenteOmie.objects.create(empresa=self.outra, codigo_omie=91)
        conta.conta_corrente = banco
        conta.save()
        with self.assertRaises(ValidationError):
            preparar_envio(self.a, self.empresa, [conta.pk])
        self.assertFalse(EnvioContasPagarLocal.objects.exists())

    def test_datas_vencidas_documento_longo_e_integracao_inativa_impedem_envio(self):
        conta = self.conta(data_vencimento=timezone.localdate()-timedelta(days=1))
        with self.assertRaises(ValidationError):
            dados_inclusao(conta)
        conta.data_vencimento = timezone.localdate()
        conta.documento = "a"*21
        with self.assertRaises(ValidationError):
            dados_inclusao(conta)
        self.integracao.ativa = False
        self.integracao.save()
        with self.assertRaises(ValidationError):
            preparar_envio(self.a, self.empresa, [conta.pk])

    @patch("apps.dashboards.contas_pagar_local_views.publicar_envio")
    def test_botao_enfileira_uma_vez_e_nao_chama_api_na_requisicao(self, publicar):
        conta = self.conta()
        with self.captureOnCommitCallbacks(execute=True), patch("apps.dashboards.contas_pagar_omie.urlopen", side_effect=AssertionError("Sem API no request")):
            self.assertEqual(self.post([conta.pk]).status_code, 202)
        publicar.assert_called_once()
        conta.refresh_from_db()
        self.assertEqual(conta.status, "enviando")
        self.assertEqual(self.post([conta.pk]).status_code, 400)
        self.assertEqual(EnvioContasPagarLocal.objects.count(), 1)

    def test_confirmacao_explicita_e_ids_validos_obrigatorios(self):
        self.assertEqual(self.client.post(self.enviar, json.dumps({"ids": [1], "acao": "enviar"}), content_type="application/json").status_code, 400)
        for ids in [[], [True], ["1"], [1, 1], list(range(1, 52))]:
            self.assertEqual(self.post(ids).status_code, 400)
        self.assertFalse(EnvioContasPagarLocal.objects.exists())

    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar")
    def test_sucesso_individual_bloqueia_edicao_e_tarefa_repetida(self, incluir):
        conta = self.conta()
        incluir.return_value = {"codigo_status": "0000", "codigo_lancamento_omie": 9001, "codigo_lancamento_integracao": conta.codigo_integracao}
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        executar_envio(envio.pk)
        executar_envio(envio.pk)
        incluir.assert_called_once()
        conta.refresh_from_db()
        self.assertEqual(conta.status, "enviado")
        self.assertEqual(conta.enviado_por, self.a)
        self.assertEqual(conta.codigo_lancamento_omie, 9001)
        self.assertFalse(conta.editavel)
        self.assertEqual(self.client.get(self.cadastro, {"conta_id": conta.pk}).status_code, 409)
        self.assertEqual(self.client.post(self.cadastro, self.editar_dados(conta, descricao="Nao pode alterar")).status_code, 409)
        self.assertEqual(self.post([conta.pk]).status_code, 400)
        html = self.client.get(self.lista).json()["html"]
        self.assertIn("OMIE #9001", html)
        self.assertNotIn(f'data-local-edit="{conta.pk}"', html)
        self.assertNotIn(f'data-local-send="{conta.pk}"', html)

    @patch("apps.dashboards.contas_pagar_envio.consultar_conta_por_integracao")
    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar", side_effect=ResultadoOmieIncerto("Timeout"))
    def test_timeout_nao_reenvia_e_confirma_somente_por_consulta(self, incluir, consultar):
        conta = self.conta()
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        executar_envio(envio.pk)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "incerto")
        with self.assertRaises(ValidationError):
            preparar_envio(self.a, self.empresa, [conta.pk])
        consultar.return_value = {"codigo_lancamento_omie": 9002, "codigo_lancamento_integracao": conta.codigo_integracao}
        verificacao = preparar_envio(self.a, self.empresa, [conta.pk], verificar=True)
        executar_envio(verificacao.pk)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "enviado")
        incluir.assert_called_once()
        consultar.assert_called_once_with(self.integracao, conta.codigo_integracao)

    @patch("apps.dashboards.contas_pagar_envio.consultar_conta_por_integracao")
    @patch("apps.dashboards.contas_pagar_envio.incluir_contas_pagar_lote", return_value={"codigo_status": "0", "lote": 100})
    def test_lote_nao_e_sucesso_individual_e_trata_confirmacao_parcial(self, incluir, consultar):
        a, b = self.conta(), self.conta(descricao="Segunda")
        envio = preparar_envio(self.a, self.empresa, [a.pk, b.pk])
        executar_envio(envio.pk)
        self.assertEqual(list(ContaPagarLocal.objects.order_by("pk").values_list("status", flat=True)), ["confirmar", "confirmar"])
        incluir.assert_called_once()
        self.assertEqual(len(incluir.call_args.args[2]), 2)
        consultar.side_effect = [{"codigo_lancamento_omie": 9003, "codigo_lancamento_integracao": a.codigo_integracao}, ResultadoOmieIncerto("Ainda sem confirmacao")]
        executar_envio(preparar_envio(self.a, self.empresa, [a.pk, b.pk], verificar=True).pk)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, "enviado")
        self.assertEqual(b.status, "confirmar")
        self.assertFalse(b.editavel)
        self.assertEqual(consultar.call_count, 2)

    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar", return_value={"codigo_status": "121", "descricao_status": "Recusado"})
    def test_recusa_confirmada_libera_correcao_sem_repetir_automaticamente(self, incluir):
        conta = self.conta()
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        executar_envio(envio.pk)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "erro")
        self.assertTrue(conta.editavel)
        incluir.assert_called_once()

    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar", return_value={"codigo_status": "0"})
    def test_sucesso_sem_id_permanece_bloqueado_ate_confirmacao(self, incluir):
        conta = self.conta()
        executar_envio(preparar_envio(self.a, self.empresa, [conta.pk]).pk)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "confirmar")
        self.assertFalse(conta.editavel)

    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar")
    def test_permissao_revogada_antes_do_worker_nao_dispara_api(self, incluir):
        conta = self.conta()
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        EmpresaUsuario.objects.filter(usuario=self.a).update(ativo=False)
        executar_envio(envio.pk)
        incluir.assert_not_called()
        conta.refresh_from_db()
        self.assertEqual(conta.status, "erro")

    @patch("apps.dashboards.tasks.processar_contas_pagar_locais.apply_async", side_effect=ConnectionError("Redis"))
    def test_broker_indisponivel_preserva_solicitacao_sem_criar_outra(self, publicar):
        conta = self.conta()
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        self.assertFalse(publicar_envio(envio))
        self.assertEqual(preparar_envio(self.a, self.empresa, [conta.pk], verificar=True).pk, envio.pk)
        self.assertEqual(EnvioContasPagarLocal.objects.count(), 1)

    @patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar")
    def test_reentrega_tarefa_em_processamento_nao_repete_escrita(self, incluir):
        conta = self.conta()
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        envio.status = "processando"
        envio.iniciado_em = timezone.now()
        envio.save()
        self.assertEqual(executar_envio(envio.pk), "ja_processado")
        incluir.assert_not_called()

    @patch("apps.dashboards.contas_pagar_omie.urlopen")
    def test_gateway_metodos_payload_e_sem_retry_de_timeout(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value = b'{"codigo_status":"0","codigo_lancamento_omie":99}'
        incluir_conta_pagar(self.integracao, {"valor_documento": 1.23})
        payload = json.loads(abrir.call_args.args[0].data)
        self.assertEqual(payload["call"], "IncluirContaPagar")
        self.assertEqual(payload["param"], [{"valor_documento": 1.23}])
        incluir_contas_pagar_lote(self.integracao, 123, [{"valor_documento": 2.34}])
        payload = json.loads(abrir.call_args.args[0].data)
        self.assertEqual(payload["call"], "IncluirContaPagarPorLote")
        self.assertEqual(payload["param"][0]["lote"], 123)
        abrir.reset_mock()
        abrir.side_effect = TimeoutError("segredo-teste key-teste")
        with self.assertRaises(ResultadoOmieIncerto) as erro:
            incluir_conta_pagar(self.integracao, {})
        abrir.assert_called_once()
        self.assertNotIn("segredo-teste", str(erro.exception))
        self.assertNotIn("key-teste", str(erro.exception))
