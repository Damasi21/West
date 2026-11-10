from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from apps.empresas.models import AcaoUsuarioLog
from . import central, test_central as fixtures


class MotivoPendenciasTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)

    def solicitar(self):
        return central.solicitar(self.plano,self.superuser,"Despesas de Frota",self.pai,estrito=False)

    def executar(self,erro):
        original=self.api.chamada
        def chamada(integracao,metodo,parametros):
            if integracao.empresa_id==self.destino.pk:raise erro
            return original(integracao,metodo,parametros)
        op=self.solicitar()
        with patch('apps.replicacao.omie.chamada',side_effect=chamada):central.executar_cadastro(op.pk)
        op.refresh_from_db()
        return op,op.empresas.get(empresa=self.destino)

    def test_recusa_guarda_codigo_motivo_categoria_e_metodo(self):
        op,linha=self.executar(central.omie.OmieRecusada("Recusa de cadastro",codigo="123",detalhe="Categoria superior inválida."))
        self.assertEqual(linha.status,"erro")
        self.assertIn("123",linha.mensagem)
        self.assertIn("Categoria superior inválida",linha.mensagem)
        passo=linha.passos[-1]
        self.assertEqual(passo['erro']['codigo'],'123')
        self.assertEqual(passo['metodo'],'IncluirCategoria')
        self.assertTrue(AcaoUsuarioLog.objects.filter(descricao="Registrou pendência de replicação",dados__cadastro_id=op.pk).exists())
        self.assertIn('encerrada com pendências',central.situacao(op)['mensagem'])
        motivo=central.situacao(op)['pendencias'][0]
        self.assertEqual(motivo['categoria'],'Despesas de Frota')
        self.assertEqual(motivo['empresa'],self.destino.nome_fantasia)
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'Motivo das pendências')
        self.assertContains(response,'Categoria superior inválida.')
        data=self.client.get(reverse('replicacao:progresso_cadastro',args=[self.plano.pk,op.pk])).json()
        self.assertIn('123',data['pendencias'][0]['mensagem'])

    def test_incerta_exibe_falha_sem_liberar_reenvio(self):
        op,linha=self.executar(central.omie.OmieIncerta("Comunicação sem confirmação",detalhe="OMIE retornou HTTP 500."))
        self.assertEqual(linha.status,'incerto')
        self.assertIn('HTTP 500',linha.mensagem)
        self.assertIn('sem reenviar',linha.mensagem)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):central.retomar(op,self.superuser)
        self.assertEqual(linha.passos[-1]['status'],'executando')

    def test_falha_desconhecida_nao_expoe_payload_ou_credenciais(self):
        op,linha=self.executar(RuntimeError('app_secret=segredo-privado; payload completo'))
        self.assertNotIn('segredo-privado',linha.mensagem)
        self.assertIn('Falha interna',linha.mensagem)
        self.assertNotIn('segredo-privado',str(central.situacao(op)))

    def test_html_da_mensagem_da_omie_e_escapado(self):
        op,linha=self.executar(central.omie.OmieRecusada(detalhe='<script>alert(1)</script>',codigo='123'))
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response,'<script>alert(1)</script>')

    def test_verificacao_com_sucesso_remove_alerta_sem_repetir_escrita(self):
        op=self.solicitar();self.api.falha='apos_gravar'
        central.executar_cadastro(op.pk);op.refresh_from_db()
        linha=op.empresas.get(empresa=self.matriz)
        self.assertEqual(linha.status,'incerto')
        self.api.falha=None
        escritos=len(self.api.escritas)
        central.verificar_cadastro(linha.pk,self.superuser.pk,self.api.catalogos[self.matriz.pk][-1]['codigo'])
        linha.refresh_from_db()
        self.assertEqual(linha.status,'sucesso')
        self.assertEqual(len(self.api.escritas),escritos)
        self.assertNotIn(self.matriz.nome_fantasia,[p['empresa'] for p in central.situacao(op)['pendencias']])

    def test_verificacao_falha_guarda_motivo_e_mantem_incerteza(self):
        op,linha=self.executar(central.omie.OmieIncerta("Retorno sem confirmação"))
        central.verificar_cadastro(linha.pk,self.superuser.pk,'2.99.99')
        linha.refresh_from_db()
        self.assertEqual(linha.status,'incerto')
        self.assertIn('Cadastro ainda não confirmado',linha.mensagem)
