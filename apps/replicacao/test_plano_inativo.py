from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from . import central, conciliacao, test_central as fixtures
from .models import CadastroCategoria
from .test_conciliacao import decisoes_padrao


class PlanoCompletoInativoTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)
        self.client.force_login(self.superuser)

    def previa_ativa(self):
        with override_settings(REPLICACAO_PLANO_COMPLETO_ATIVO=True):
            op=conciliacao.solicitar(self.plano,self.superuser,[self.destino.pk])
            central.executar_cadastro(op.pk);op.refresh_from_db()
            return op

    def test_padrao_inativo_oculta_card_e_modal_sem_afetar_avulso(self):
        from .plano_completo import ativo
        self.assertFalse(ativo())
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'CADASTRO AVULSO')
        self.assertContains(response,'Cadastrar categoria ou grupo')
        self.assertNotContains(response,'Preparar prévia do plano')
        self.assertNotContains(response,'id="rep-padronizar"')
        op=central.solicitar(self.plano,self.superuser,'Energia elétrica',self.pai,estrito=False)
        central.executar_cadastro(op.pk)
        self.assertTrue(all(l.status=='sucesso' for l in op.empresas.all()))

    def test_nova_previa_via_funcao_ou_post_nao_publica_tarefa(self):
        with self.assertRaisesMessage(ValidationError,'temporariamente inativo'):
            conciliacao.solicitar(self.plano,self.superuser,[self.destino.pk])
        with patch('apps.replicacao.central.publicar_cadastro') as publicar:
            self.client.post(reverse('replicacao:padronizar',args=[self.plano.pk]),{'destinos':str(self.destino.pk)})
        publicar.assert_not_called()
        self.assertFalse(CadastroCategoria.objects.exists())
        self.assertEqual(self.api.escritas,[])

    def test_previa_anterior_nao_confirma_nem_retoma_mas_pode_cancelar(self):
        op=self.previa_ativa()
        with self.assertRaisesMessage(ValidationError,'temporariamente inativo'):
            conciliacao.confirmar(op,self.superuser,decisoes_padrao(op))
        with self.assertRaisesMessage(ValidationError,'temporariamente inativo'):
            central.retomar(op,self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertNotContains(response,'Confirmar decisões e executar pelos workers')
        self.assertNotContains(response,'Retomar consulta / pendências')
        self.assertContains(response,'Cancelar requisição')
        central.cancelar(op,self.superuser)
        op.refresh_from_db();self.assertEqual(op.status,'cancelada')
        self.assertEqual(self.api.escritas,[])

    def test_worker_bloqueia_tarefa_ja_enfileirada_sem_consultar_ou_escrever(self):
        op=self.previa_ativa()
        with override_settings(REPLICACAO_PLANO_COMPLETO_ATIVO=True):
            op=conciliacao.confirmar(op,self.superuser,decisoes_padrao(op))
        with patch('apps.replicacao.omie.listar') as listar:
            central.executar_cadastro(op.pk)
        listar.assert_not_called()
        op.refresh_from_db()
        self.assertEqual(op.status,'erro')
        self.assertIn('temporariamente inativo',op.mensagem)
        self.assertEqual(self.api.escritas,[])

    def test_verificacao_anterior_continua_disponivel_sem_escrita(self):
        self.api.catalogos[self.destino.pk][-1]['descricao']='Cadastro antigo'
        op=self.previa_ativa()
        with override_settings(REPLICACAO_PLANO_COMPLETO_ATIVO=True):
            op=conciliacao.confirmar(op,self.superuser,decisoes_padrao(op))
            self.api.falha='apos_gravar'
            central.executar_cadastro(op.pk)
        linha=op.empresas.get();self.assertEqual(linha.status,'incerto')
        codigo=self.api.catalogos[self.destino.pk][-1]['codigo']
        self.api.falha=None;escritas=len(self.api.escritas)
        central.verificar_cadastro(linha.pk,self.superuser.pk,codigo)
        linha.refresh_from_db()
        self.assertFalse(any(p.get('status') in {'incerto','executando'} for p in linha.passos))
        self.assertEqual(len(self.api.escritas),escritas)
