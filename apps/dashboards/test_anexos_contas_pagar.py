import base64
import hashlib
import io
import json
import tempfile
import zipfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase

from . import test_envio_contas_pagar as fixtures
from .contas_pagar_anexos import dados_anexo, processar_anexos
from .contas_pagar_envio import executar_envio, preparar_envio
from .contas_pagar_omie import ANEXOS_URL, ResultadoOmieIncerto, incluir_anexo, consultar_anexo
from .models import AnexoContaPagarLocal


class AnexosContasPagarTests(TestCase):
    conta = fixtures.EnvioContasPagarTests.conta

    def setUp(self):
        fixtures.EnvioContasPagarTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        storage = patch.object(AnexoContaPagarLocal._meta.get_field("arquivo"), "storage", FileSystemStorage(location=self.temp.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.titulo = self.conta(status="enviado", codigo_lancamento_omie=3001)
        self.conteudo = b"%PDF-1.4\n%%EOF"
        self.anexo = self.criar_anexo()

    def criar_anexo(self, nome="nota.fiscal.pdf", conta=None):
        anexo = AnexoContaPagarLocal(conta=conta or self.titulo, nome_original=nome, tamanho=len(self.conteudo))
        anexo.arquivo.save(nome, ContentFile(self.conteudo), save=True)
        return anexo

    def resposta(self, anexo=None, codigo=91):
        anexo = anexo or self.anexo
        return {"cCodStatus": "0000", "nIdAnexo": codigo, "cCodIntAnexo": anexo.codigo_integracao,
                "cTabela": "conta-pagar", "nId": anexo.conta.codigo_lancamento_omie}

    def test_zip_base64_md5_id_e_nome_seguro_estaveis(self):
        dados = dados_anexo(self.anexo)
        self.assertEqual(dados, dados_anexo(self.anexo))
        self.assertEqual(dados["nId"], 3001)
        self.assertEqual(dados["cTabela"], "conta-pagar")
        self.assertLessEqual(len(dados["cCodIntAnexo"]), 20)
        self.assertEqual(dados["cTipoArquivo"], "pdf")
        self.assertEqual(dados["cNomeArquivo"], "nota_fiscal.pdf")
        compactado = base64.b64decode(dados["cArquivo"], validate=True)
        self.assertEqual(dados["cMd5"], hashlib.md5(dados["cArquivo"].encode("ascii")).hexdigest())
        self.assertNotEqual(dados["cMd5"], hashlib.md5(compactado).hexdigest())
        with zipfile.ZipFile(io.BytesIO(compactado)) as pacote:
            self.assertEqual(pacote.namelist(), ["nota_fiscal.pdf"])
            self.assertEqual(pacote.read("nota_fiscal.pdf"), self.conteudo)
        self.assertNotIn("app_secret", dados)
        self.assertNotIn("cArquivo", json.dumps(self.anexo.__dict__, default=str))

    def test_codigos_diferentes_para_anexos_com_mesmo_nome(self):
        outro = self.criar_anexo()
        self.assertNotEqual(outro.codigo_integracao, self.anexo.codigo_integracao)

    def test_rascunho_nao_envia_arquivos(self):
        self.titulo.status = "rascunho"
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo") as incluir:
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_not_called()
        with self.assertRaises(ValueError):
            dados_anexo(self.anexo)

    def test_sucesso_nao_reenvia_arquivo_ou_altera_titulo(self):
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value=self.resposta()) as incluir:
            processar_anexos(self.titulo, self.integracao)
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_called_once()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "enviado")
        self.assertEqual(self.anexo.codigo_anexo_omie, 91)
        self.assertIsNotNone(self.anexo.enviado_em)
        self.titulo.refresh_from_db()
        self.assertEqual(self.titulo.status, "enviado")
        self.assertFalse(self.titulo.editavel)

    def test_timeout_apenas_consulta_chave_na_proxima_tentativa(self):
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", side_effect=ResultadoOmieIncerto("timeout")) as incluir:
            processar_anexos(self.titulo, self.integracao)
            self.anexo.refresh_from_db()
            self.assertEqual(self.anexo.status_omie, "incerto")
            with patch("apps.dashboards.contas_pagar_anexos.consultar_anexo", return_value=self.resposta()) as consultar:
                processar_anexos(self.titulo, self.integracao)
        incluir.assert_called_once()
        consultar.assert_called_once_with(self.integracao, self.anexo.codigo_integracao, 3001)
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "enviado")

    def test_ambiguo_nao_encontrado_continua_bloqueado_sem_reenvio(self):
        self.anexo.status_omie = "enviando"
        self.anexo.save()
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo") as incluir, patch("apps.dashboards.contas_pagar_anexos.consultar_anexo", return_value={"cCodStatus": "1"}):
            processar_anexos(self.titulo, self.integracao)
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_not_called()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "incerto")

    def test_recusa_explicita_permite_tentar_somente_anexo(self):
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value={"cCodStatus": "2"}):
            processar_anexos(self.titulo, self.integracao)
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "erro")
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value=self.resposta()) as incluir:
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_called_once()

    def test_anexo_confirmado_de_outra_conta_nao_e_aceito(self):
        resposta = self.resposta()
        resposta["nId"] = 999
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value=resposta):
            processar_anexos(self.titulo, self.integracao)
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "incerto")

    def test_arquivo_ausente_nao_chama_api_e_continua_conta_enviada(self):
        self.anexo.arquivo.delete(save=False)
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo") as incluir:
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_not_called()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "erro")
        self.titulo.refresh_from_db()
        self.assertEqual(self.titulo.status, "enviado")

    def test_falha_um_arquivo_nao_impede_os_demais(self):
        outro = self.criar_anexo("boleto.pdf")
        def enviar(integracao, dados):
            if dados["cCodIntAnexo"] == self.anexo.codigo_integracao:
                raise ResultadoOmieIncerto("timeout")
            return self.resposta(outro, 92)
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", side_effect=enviar):
            processar_anexos(self.titulo, self.integracao)
        self.anexo.refresh_from_db()
        outro.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "incerto")
        self.assertEqual(outro.status_omie, "enviado")

    def test_worker_so_envia_anexo_apos_confirmar_titulo(self):
        conta = self.conta()
        anexo = self.criar_anexo(conta=conta)
        envio = preparar_envio(self.a, self.empresa, [conta.pk])
        ordem = []
        def incluir_titulo(*args):
            ordem.append("titulo")
            return {"codigo_status": "0", "codigo_lancamento_omie": 3010}
        def incluir_arquivo(integracao, dados):
            ordem.append("anexo")
            self.assertEqual(dados["nId"], 3010)
            self.assertEqual(dados["cCodIntAnexo"], anexo.codigo_integracao)
            return {"cCodStatus": "0", "nIdAnexo": 93}
        with patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar", side_effect=incluir_titulo), patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", side_effect=incluir_arquivo):
            executar_envio(envio.pk)
        self.assertEqual(ordem, ["titulo", "anexo"])

    def test_verificar_conta_enviada_processa_anexo_sem_incluir_novo_titulo(self):
        envio = preparar_envio(self.a, self.empresa, [self.titulo.pk], verificar=True)
        with patch("apps.dashboards.contas_pagar_envio.consultar_conta_por_integracao", return_value={"codigo_lancamento_omie": 3001}), patch("apps.dashboards.contas_pagar_envio.incluir_conta_pagar") as incluir_titulo, patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value=self.resposta()):
            executar_envio(envio.pk)
        incluir_titulo.assert_not_called()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie, "enviado")

    def test_gateway_anexos_endpoint_metodo_e_tentativa_unica(self):
        with patch("apps.dashboards.contas_pagar_omie.urlopen") as http:
            http.return_value.__enter__.return_value.read.return_value = b'{"nIdAnexo":91,"cCodStatus":"0"}'
            incluir_anexo(self.integracao, dados_anexo(self.anexo))
            request = http.call_args.args[0]
            self.assertEqual(request.full_url, ANEXOS_URL)
            payload = json.loads(request.data)
            self.assertEqual(payload["call"], "lcpIncluirAnexo")
            self.assertEqual(payload["param"][0]["nCodTitulo"], 3001)
            self.assertEqual(payload["param"][0]["cNomeArq"], "nota_fiscal.pdf")
            self.assertNotIn("cTabela", payload["param"][0])
            http.reset_mock()
            consultar_anexo(self.integracao, self.anexo.codigo_integracao, 3001)
            self.assertEqual(json.loads(http.call_args.args[0].data)["call"], "lcpConsultarAnexo")
            http.reset_mock()
            http.side_effect = TimeoutError()
            with self.assertRaises(ResultadoOmieIncerto):
                incluir_anexo(self.integracao, dados_anexo(self.anexo))
            http.assert_called_once()

    def test_resposta_financeira_real_sem_id_anexo_confirma_titulo_e_chave(self):
        resposta={"nCodTitulo":3001,"cCodIntAnexo":self.anexo.codigo_integracao,
                  "cNomeArq":"nota_fiscal.pdf","cCodStatus":"0","cDesStatus":"Sucesso"}
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo", return_value=resposta) as incluir:
            processar_anexos(self.titulo, self.integracao)
            processar_anexos(self.titulo, self.integracao)
        incluir.assert_called_once()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie,"enviado")
        self.assertIsNone(self.anexo.codigo_anexo_omie)

    def test_resposta_vazia_da_api_geral_nao_e_sucesso(self):
        resposta={"nId":0,"nIdAnexo":0,"cCodIntAnexo":"","cNomeArquivo":"","cCodStatus":""}
        with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo",return_value=resposta):
            processar_anexos(self.titulo,self.integracao)
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie,"incerto")

    def test_consulta_financeira_sem_status_confirma_chave_e_titulo(self):
        self.anexo.status_omie="incerto"
        self.anexo.save()
        resposta={"nCodTitulo":3001,"cCodIntAnexo":self.anexo.codigo_integracao,"cNomeArq":"nota_fiscal.pdf"}
        with patch("apps.dashboards.contas_pagar_anexos.consultar_anexo",return_value=resposta), patch("apps.dashboards.contas_pagar_anexos.incluir_anexo") as incluir:
            processar_anexos(self.titulo,self.integracao)
        incluir.assert_not_called()
        self.anexo.refresh_from_db()
        self.assertEqual(self.anexo.status_omie,"enviado")

    def test_resposta_financeira_exige_identidade_completa(self):
        for extra in [{"nCodTitulo":999},{"cCodIntAnexo":"outra-chave"},{"cNomeArq":""},{"cCodStatus":"5"}]:
            self.anexo.status_omie="pendente"
            self.anexo.save()
            resposta={"nCodTitulo":3001,"cCodIntAnexo":self.anexo.codigo_integracao,"cNomeArq":"nota.pdf","cCodStatus":"0",**extra}
            with patch("apps.dashboards.contas_pagar_anexos.incluir_anexo",return_value=resposta):
                processar_anexos(self.titulo,self.integracao)
            self.anexo.refresh_from_db()
            self.assertNotEqual(self.anexo.status_omie,"enviado")
