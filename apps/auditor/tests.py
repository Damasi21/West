from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import CadastroOmie, ContaPagarOmie, ContaReceberOmie, Empresa, EmpresaUsuario
from .models import CasoAuditoria, EvidenciaAuditoria, EventoAuditoria, ExecucaoAuditoria, VersaoRegistroAuditoria
from .services import executar_auditoria, politicas_empresa, solicitar_execucao
from .tasks import registrar_falha_worker


class AuditorTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Auditor Teste", nome_fantasia="Auditor Teste", cnpj="00.000.000/0001-71")
        self.outra = Empresa.objects.create(nome="Outra Auditor", cnpj="00.000.000/0001-72")
        self.admin = get_user_model().objects.create_user(username="auditor-gestor", password="senha-segura")
        self.viewer = get_user_model().objects.create_user(username="auditor-leitor")
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.admin, papel="gestor", areas_permitidas=["auditor"])
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.viewer, papel="viewer", areas_permitidas=["auditor"])
        self.client.force_login(self.admin)

    def url(self, nome, **kwargs):
        return reverse(f"auditor:{nome}", kwargs={"empresa_slug": self.empresa.slug, **kwargs})

    def titulo(self, numero=1, empresa=None, modelo=ContaPagarOmie, **dados):
        campos = {"codigo_cliente_fornecedor": 10, "numero_documento": f"DOC{numero}",
                  "data_emissao": date(2026, 1, 1) + timedelta(days=numero),
                  "data_vencimento": date(2026, 3, 1), "valor_documento": Decimal("100"), "codigo_categoria": "ENERGIA"}
        campos.update(dados)
        return modelo.objects.create(empresa=empresa or self.empresa, codigo_lancamento_omie=numero, **campos)

    def rodar(self, empresa=None):
        execucao, nova = solicitar_execucao(empresa or self.empresa, self.admin)
        self.assertTrue(nova)
        executar_auditoria(execucao.pk)
        execucao.refresh_from_db()
        return execucao

    def duplicados(self):
        self.titulo(1, numero_documento="NF-123")
        self.titulo(2, numero_documento="NF123")

    def test_telas_navegaveis_e_vazias_sem_dados_demonstrativos(self):
        for pagina in ("visao_geral", "alertas", "regras"):
            r = self.client.get(self.url(pagina))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Auditor")
        r = self.client.get(self.url("visao_geral"))
        self.assertContains(r, "Sem dados")
        self.assertContains(r, "Nenhuma auditoria concluida")

    def test_execucao_vazia_registra_cobertura_sem_afirmar_conformidade(self):
        e = self.rodar()
        self.assertEqual(e.status, "concluida")
        self.assertEqual(e.resumo["sinais"], 0)
        self.assertTrue(all(f["situacao"] == "Sem dados" for f in e.fontes))
        self.assertIn("Sem alertas nao significa ausencia de inconsistencias.", e.resumo["limites"])

    def test_cadastro_incompleto_e_excecao_exterior(self):
        CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=1, tipo="fornecedor")
        CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=2, tipo="fornecedor", exterior=True, razao_social="Exterior")
        self.rodar()
        caso = CasoAuditoria.objects.get(regra="cadastro_incompleto")
        self.assertEqual(caso.evidencias.first().dados["evidencia"]["campos_ausentes"], ["Nome", "CPF/CNPJ"])

    def test_duplicidade_preserva_tratamento_e_evidencias_em_reexecucoes(self):
        self.duplicados()
        self.rodar()
        caso = CasoAuditoria.objects.get(regra="titulo_duplicado")
        caso.status = "justificado"
        caso.save()
        versoes = VersaoRegistroAuditoria.objects.count()
        self.rodar()
        caso.refresh_from_db()
        self.assertEqual(caso.status, "justificado")
        self.assertEqual(CasoAuditoria.objects.count(), 1)
        self.assertEqual(caso.evidencias.count(), 2)
        self.assertEqual(VersaoRegistroAuditoria.objects.count(), versoes)

    def test_parcelas_e_naturezas_nao_sao_confundidas(self):
        self.titulo(1, numero_documento="123", numero_parcela="001/002")
        self.titulo(2, numero_documento="123", numero_parcela="002/002")
        self.titulo(1, numero_documento="123", numero_parcela="001/002", modelo=ContaReceberOmie)
        self.rodar()
        self.assertFalse(CasoAuditoria.objects.filter(regra="titulo_duplicado").exists())

    def test_cancelados_inativos_documento_ausente_nao_geram_duplicidade(self):
        self.titulo(1, numero_documento="123")
        self.titulo(2, numero_documento="123", status_titulo="CANCELADO")
        self.titulo(3, numero_documento="123", ativo_omie=False)
        self.titulo(4, numero_documento="")
        e = self.rodar()
        self.assertFalse(CasoAuditoria.objects.filter(regra="titulo_duplicado").exists())
        self.assertEqual(e.resumo["cobertura"]["titulo_duplicado"]["sem_base"], 1)

    def test_regra_estatistica_usa_apenas_historico_anterior_e_mediana(self):
        for n in range(1, 7):
            self.titulo(n)
        self.titulo(7, valor_documento=1000, codigo_categoria="MARKETING")
        e = self.rodar()
        valor = CasoAuditoria.objects.get(regra="valor_atipico")
        self.assertEqual(valor.evidencias.first().dados["evidencia"]["mediana"], "100.00")
        self.assertTrue(CasoAuditoria.objects.filter(regra="categoria_atipica").exists())
        self.assertEqual(e.resumo["cobertura"]["valor_atipico"]["sem_base"], 6)
        r = self.client.get(self.url("detalhe", caso_id=valor.pk))
        self.assertContains(r, "Mediana historica")
        self.assertContains(r, "R$ 100,00")

    def test_mesmo_dia_nao_serve_de_base_e_sem_historico_nao_conclui(self):
        for n in range(1, 9):
            self.titulo(n, data_emissao=date(2026, 1, 1), valor_documento=1000 if n == 8 else 100)
        e = self.rodar()
        self.assertFalse(CasoAuditoria.objects.filter(regra="valor_atipico").exists())
        self.assertEqual(e.resumo["cobertura"]["valor_atipico"]["sem_base"], 8)

    def test_mudanca_bancaria_tem_baseline_e_dados_mascarados(self):
        c = CadastroOmie.objects.create(empresa=self.empresa, codigo_cliente_omie=1, tipo="fornecedor", razao_social="Fornecedor", cnpj_cpf="12345678000199", dados_bancarios={"chave_pix": "pix-antigo@example.com"})
        self.rodar()
        self.assertFalse(CasoAuditoria.objects.filter(regra="alteracao_bancaria").exists())
        c.dados_bancarios = {"chave_pix": "pix-novo@example.com"}
        c.save()
        self.rodar()
        caso = CasoAuditoria.objects.get(regra="alteracao_bancaria")
        self.assertNotIn("pix-novo@example.com", str(caso.evidencias.first().dados))
        self.assertNotIn("pix-antigo@example.com", str(list(VersaoRegistroAuditoria.objects.values_list("dados", flat=True))))
        self.assertEqual(VersaoRegistroAuditoria.objects.count(), 2)
        self.assertEqual(caso.evidencias.first().dados["evidencia"]["autor_na_origem"], "Nao disponivel")
        r = self.client.get(self.url("detalhe", caso_id=caso.pk))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "pix-novo@example.com")

    def test_isolamento_entre_empresas_mesmo_codigo_de_parceiro(self):
        self.titulo(1, numero_documento="123")
        self.titulo(1, empresa=self.outra, numero_documento="123")
        self.rodar()
        self.assertFalse(CasoAuditoria.objects.exists())
        self.assertFalse(VersaoRegistroAuditoria.objects.filter(empresa=self.outra).exists())

    @patch("apps.auditor.views.executar_auditoria_task.apply_async")
    def test_post_enfileira_somente_auditor_e_nao_duplica_execucao(self, envio):
        for _ in range(2):
            self.assertEqual(self.client.post(self.url("executar")).status_code, 302)
        self.assertEqual(ExecucaoAuditoria.objects.count(), 1)
        self.assertEqual(envio.call_count, 1)
        self.assertEqual(envio.call_args.kwargs["queue"], "auditor")
        self.assertEqual(self.client.get(self.url("executar")).status_code, 405)

    @patch("apps.auditor.views.executar_auditoria_task.apply_async", side_effect=ConnectionError)
    def test_falha_broker_registra_erro_e_permite_nova_tentativa(self, envio):
        for _ in range(2):
            self.client.post(self.url("executar"))
        self.assertEqual(ExecucaoAuditoria.objects.filter(status="erro").count(), 2)

    def test_unica_execucao_ativa_e_reentrega_ignorada(self):
        e, _ = solicitar_execucao(self.empresa, self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExecucaoAuditoria.objects.create(empresa=self.empresa)
        executar_auditoria(e.pk)
        executar_auditoria(e.pk)
        self.assertEqual(ExecucaoAuditoria.objects.count(), 1)

    @patch("apps.auditor.services._detectar", side_effect=RuntimeError("teste"))
    def test_falha_da_analise_registra_erro_sem_evidencias_parciais(self, detectar):
        e, _ = solicitar_execucao(self.empresa, self.admin)
        with self.assertRaises(RuntimeError):
            executar_auditoria(e.pk)
        e.refresh_from_db()
        self.assertEqual(e.status, "erro")
        self.assertFalse(EvidenciaAuditoria.objects.exists())

    def test_acesso_entre_empresas_e_permissoes_de_leitura(self):
        r = self.client.get(reverse("auditor:visao_geral", kwargs={"empresa_slug": self.outra.slug}))
        self.assertEqual(r.status_code, 404)
        self.duplicados()
        self.rodar()
        caso = CasoAuditoria.objects.first()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url("detalhe", caso_id=caso.pk)).status_code, 200)
        self.assertEqual(self.client.post(self.url("executar")).status_code, 403)
        self.assertEqual(self.client.post(self.url("detalhe", caso_id=caso.pk), {"status": "resolvido", "comentario": "Teste"}).status_code, 403)
        self.assertEqual(self.client.post(self.url("regras"), {"codigo": "titulo_duplicado", "ativa": "on", "severidade": "critico"}).status_code, 403)

    def test_restricao_de_dashboard_e_csrf(self):
        vinculo = EmpresaUsuario.objects.get(usuario=self.viewer)
        vinculo.dashboards_permitidos = ["auditor:alertas"]
        vinculo.save()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url("alertas")).status_code, 200)
        self.assertEqual(self.client.get(self.url("visao_geral")).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.url("executar")).status_code, 403)

    def test_tratamento_exige_justificativa_e_registra_autor(self):
        self.duplicados()
        self.rodar()
        caso = CasoAuditoria.objects.first()
        url = self.url("detalhe", caso_id=caso.pk)
        self.assertEqual(self.client.post(url, {"status": "resolvido"}).status_code, 200)
        caso.refresh_from_db()
        self.assertEqual(caso.status, "novo")
        self.client.post(url, {"status": "justificado", "comentario": "Conferido: documentos de series distintas.", "responsavel": self.admin.pk})
        caso.refresh_from_db()
        self.assertEqual(caso.status, "justificado")
        self.assertEqual(caso.eventos.get().autor, self.admin)

    def test_politica_alterada_tem_trilha_e_efeito_na_proxima_execucao(self):
        self.client.get(self.url("regras"))
        self.client.post(self.url("regras"), {"codigo": "titulo_duplicado", "severidade": "alto"})
        self.duplicados()
        e = self.rodar()
        self.assertFalse(CasoAuditoria.objects.exists())
        self.assertFalse(next(p for p in e.politicas if p["codigo"] == "titulo_duplicado")["ativa"])
        self.assertTrue(EventoAuditoria.objects.filter(acao="Politica: titulo_duplicado", autor=self.admin).exists())

    def test_parametros_invalidos_nao_sao_salvos(self):
        self.client.get(self.url("regras"))
        r = self.client.post(self.url("regras"), {"codigo": "valor_atipico", "ativa": "on", "severidade": "alto", "amostras_minimas": 0, "multiplicador_valor": -1, "janela_dias": 0})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["linhas"])
        politica = politicas_empresa(self.empresa).get(codigo="valor_atipico")
        self.assertEqual(politica.parametros["amostras_minimas"], 6)

    def test_banco_e_valores_originais_nunca_sao_modificados(self):
        t = self.titulo()
        self.rodar()
        t.refresh_from_db()
        self.assertEqual(t.valor_documento, Decimal("100"))
        self.assertEqual(t.codigo_categoria, "ENERGIA")

    def test_busca_numero_muito_grande_nao_gera_erro(self):
        self.assertEqual(self.client.get(self.url("alertas"), {"q": "9" * 100}).status_code, 200)

    def test_falha_worker_libera_execucao_sem_afetar_outro_tipo_de_tarefa(self):
        e, _ = solicitar_execucao(self.empresa, self.admin)
        registrar_falha_worker(sender=SimpleNamespace(name="outra_tarefa"), args=[e.pk])
        e.refresh_from_db()
        self.assertEqual(e.status, "fila")
        registrar_falha_worker(sender=SimpleNamespace(name="apps.auditor.executar"), args=[e.pk])
        e.refresh_from_db()
        self.assertEqual(e.status, "erro")

    def test_espera_expirada_pode_ser_encerrada_sem_cancelar_analise(self):
        e, _ = solicitar_execucao(self.empresa, self.admin)
        url = self.url("encerrar_espera", execucao_id=e.pk)
        self.client.post(url)
        e.refresh_from_db()
        self.assertEqual(e.status, "fila")
        ExecucaoAuditoria.objects.filter(pk=e.pk).update(criada_em=timezone.now() - timedelta(hours=1))
        self.client.post(url)
        e.refresh_from_db()
        self.assertEqual(e.status, "erro")
        executar_auditoria(e.pk)
        self.assertFalse(CasoAuditoria.objects.exists())
        outro, _ = solicitar_execucao(self.empresa, self.admin)
        ExecucaoAuditoria.objects.filter(pk=outro.pk).update(status="executando", criada_em=timezone.now() - timedelta(hours=1))
        self.client.post(self.url("encerrar_espera", execucao_id=outro.pk))
        outro.refresh_from_db()
        self.assertEqual(outro.status, "executando")

    def test_politica_reclassifica_caso_sem_reescrever_evidencia_anterior(self):
        self.duplicados()
        self.rodar()
        politica = politicas_empresa(self.empresa).get(codigo="titulo_duplicado")
        politica.severidade = "critico"
        politica.save()
        self.rodar()
        caso = CasoAuditoria.objects.get()
        self.assertEqual(caso.severidade, "critico")
        self.assertEqual(caso.evidencias.last().dados["severidade_detectada"], "alto")

    @patch("apps.auditor.views.executar_auditoria_task.apply_async")
    def test_resposta_broker_perdida_nao_sobrescreve_execucao_concluida(self, enviar):
        def aceitou(*args, **kwargs):
            executar_auditoria(kwargs["args"][0])
            raise ConnectionError
        enviar.side_effect = aceitou
        self.client.post(self.url("executar"))
        self.assertEqual(ExecucaoAuditoria.objects.get().status, "concluida")

    def test_historico_fora_da_janela_nao_e_usado(self):
        for n in range(1, 7):
            self.titulo(n, data_emissao=date(2024, 1, n))
        self.titulo(7, data_emissao=date(2026, 1, 1), valor_documento=10000)
        self.rodar()
        self.assertFalse(CasoAuditoria.objects.filter(regra="valor_atipico").exists())
