from copy import deepcopy
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse

from . import central, test_central as fixtures, padronizacao
from .tests import categoria
from apps.empresas.models import AmbienteWhiteLabel
from apps.empresas.white_label_domains import _marca_host


class CancelamentoTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)

    def test_cancelar_fila_impede_worker_de_consultar_ou_enviar_e_nao_reabre(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        cancelada=central.cancelar(op,self.superuser)
        self.assertEqual(cancelada.status,"cancelada")
        with patch('apps.replicacao.omie.listar') as ler:
            central.executar_cadastro(op.pk)
        ler.assert_not_called()
        self.assertEqual(self.api.escritas,[])
        with self.assertRaises(ValidationError): central.retomar(cancelada,self.superuser)
        self.assertEqual(central.cancelar(cancelada,self.superuser).status,"cancelada")

    def test_confirmados_preservados_incerto_continua_bloqueando_apenas_a_empresa(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        op.status="erro";op.save()
        a=op.empresas.get(empresa=self.matriz)
        a.passos=[{"status":"sucesso","codigo":"2.01.01"},{"status":"erro"}]
        a.status="erro";a.save()
        b=op.empresas.get(empresa=self.destino)
        b.passos=[{"status":"executando","codigo":"2.08.07"},{"status":"pendente"}]
        b.status="incerto";b.save()
        central.cancelar(op,self.superuser)
        a.refresh_from_db();b.refresh_from_db()
        self.assertEqual(a.passos[0],{"status":"sucesso","codigo":"2.01.01"})
        self.assertEqual(a.passos[1]["status"],"cancelada")
        self.assertEqual(b.status,"incerto")
        self.assertEqual(b.passos[0]["status"],"incerto")
        self.assertEqual(b.passos[1]["status"],"cancelada")
        central.conferir_sem_incerteza(self.matriz)
        with self.assertRaises(ValidationError): central.conferir_sem_incerteza(self.destino)
        self.assertEqual(self.api.escritas,[])

    def test_nao_interrompe_worker_que_possui_lock(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        outro=connection.copy(alias="cancelamento-lock")
        chave="west-cadastro-categoria:"+str(op.pk)
        try:
            with outro.cursor() as cursor: cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))",[chave])
            with self.assertRaises(ValidationError): central.cancelar(op,self.superuser)
            op.refresh_from_db()
            self.assertEqual(op.status,"fila")
        finally:
            with outro.cursor() as cursor: cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))",[chave])
            outro.close()

    def test_permissoes_marca_csrf_e_confirmacao(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        for usuario in (self.viewer,self.lider):
            with self.assertRaises(PermissionDenied): central.cancelar(op,usuario)
        marca=AmbienteWhiteLabel.objects.create(nome="Outra marca cancelar",slug="outra-marca-cancelar")
        token=_marca_host.set(marca)
        try:
            with self.assertRaises(PermissionDenied): central.cancelar(op,self.superuser)
        finally: _marca_host.reset(token)
        url=reverse('replicacao:cancelar_cadastro',args=[self.plano.pk,op.pk])
        client=Client(enforce_csrf_checks=True);client.force_login(self.superuser)
        self.assertEqual(client.post(url,{'confirmar':'sim'}).status_code,403)
        self.client.force_login(self.superuser)
        self.client.post(url)
        op.refresh_from_db();self.assertEqual(op.status,"fila")
        self.client.post(url,{'confirmar':'sim'})
        op.refresh_from_db();self.assertEqual(op.status,"cancelada")
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]),{'cadastro':op.pk})
        self.assertContains(response,'Requisição cancelada')
        self.assertNotContains(response,'Retomar consulta / pendências')

    def test_botao_aparece_no_erro_e_cancelamento_nao_depende_da_integracao(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        op.status="erro";op.save()
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'Cancelar requisição')
        from apps.empresas.models import IntegracaoOmie
        IntegracaoOmie.objects.filter(empresa=self.matriz).update(ativa=False)
        self.assertEqual(central.cancelar(op,self.superuser).status,"cancelada")

    def test_nova_colisao_102_apos_previa_exige_nova_previa_sem_repetir(self):
        self.api.catalogos[self.destino.pk][-1]['descricao']='Nome antigo 1'
        self.api.catalogos[self.matriz.pk].append(categoria('2.01.02','Seguro',pai='2.01'))
        self.api.catalogos[self.destino.pk].append(categoria('2.08.08','Nome antigo 2',pai='2.08'))
        op=padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk])
        central.executar_cadastro(op.pk);op.refresh_from_db()
        linha=op.empresas.get()
        op=padronizacao.confirmar(op,self.superuser,{'confirmar':'sim',f'aplicar_{linha.pk}':'sim'})
        def escrever(i,m,p):
            if p.get('descricao')=='Energia elétrica':
                raise central.omie.OmieRecusada(codigo='102',detalhe='Nome já existente')
            return self.api.chamada(i,m,p)
        with patch('apps.replicacao.omie.chamada',side_effect=escrever) as envio:
            central.executar_cadastro(op.pk)
        linha.refresh_from_db()
        self.assertEqual(linha.status,'erro',linha.mensagem)
        self.assertEqual(linha.passos[1]['status'],'erro')
        self.assertEqual(linha.passos[2]['status'],'pendente')
        self.assertEqual(envio.call_count,1)

    def test_grupo_duplicado_recebe_ponto_e_preserva_hierarquia_dos_filhos(self):
        self.api.catalogos[self.matriz.pk][1]['descricao']='Grupo já existente'
        self.api.catalogos[self.destino.pk].append(categoria('2.09','Grupo já existente',grupo=True,pai='2'))
        # Equal group counts: a second source group maps to the protected target.
        self.api.catalogos[self.matriz.pk].append(categoria('2.02','Outro grupo',grupo=True,pai='2'))
        op=padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk])
        central.executar_cadastro(op.pk);op.refresh_from_db()
        linha=op.empresas.get()
        self.assertEqual(linha.passos[0]['acao'],'prefixar')
        self.assertEqual(linha.passos[0]['esperado']['descricao'],'.Grupo já existente')
        op=padronizacao.confirmar(op,self.superuser,{'confirmar':'sim',f'aplicar_{linha.pk}':'sim'})
        central.executar_cadastro(op.pk)
        self.assertTrue(self.api.escritas)
        cs={c['codigo']:c for c in self.api.catalogos[self.destino.pk]}
        self.assertEqual(cs['2.08']['descricao'],'Grupo já existente')
        self.assertEqual(cs['2.09']['descricao'],'Outro grupo')
        self.assertEqual(cs['2.08.07']['categoria_superior'],'2.08')

    def test_cancelada_com_envio_incerto_pode_verificar_sem_reabrir_ou_reenviar(self):
        self.api.catalogos[self.destino.pk][-1]['descricao']='Nome antigo'
        op=padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk])
        central.executar_cadastro(op.pk);op.refresh_from_db()
        linha=op.empresas.get()
        op=padronizacao.confirmar(op,self.superuser,{'confirmar':'sim',f'aplicar_{linha.pk}':'sim'})
        self.api.falha='apos_gravar'
        central.executar_cadastro(op.pk)
        linha.refresh_from_db();self.assertEqual(linha.status,'incerto')
        op=central.cancelar(op,self.superuser)
        central.verificar_cadastro(linha.pk,self.superuser.pk)
        linha.refresh_from_db();op.refresh_from_db()
        self.assertEqual(op.status,'cancelada')
        self.assertEqual(linha.status,'ignorada',linha.mensagem)
        self.assertEqual(len(self.api.escritas),1)
        central.conferir_sem_incerteza(self.destino)
        with self.assertRaises(ValidationError): central.retomar(op,self.superuser)

    def test_sucesso_total_nao_pode_ser_cancelado(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        central.executar_cadastro(op.pk)
        with self.assertRaises(ValidationError): central.cancelar(op,self.superuser)

    def test_codigo_102_que_nao_indica_nome_duplicado_nao_e_ignorado(self):
        self.assertFalse(central.omie.eh_duplicidade(central.omie.OmieRecusada(codigo='102',detalhe='Campo obrigatório ausente')))
        self.assertFalse(central.omie.eh_duplicidade(central.omie.OmieRecusada(codigo='123',detalhe='Já existe nome igual')))
        self.assertTrue(central.omie.eh_duplicidade(central.omie.OmieRecusada(codigo='102',detalhe='Já existe categoria com essa descrição neste grupo.')))

    def test_verificacao_respeita_lock_da_operacao_sem_consultar_omie(self):
        op=central.solicitar(self.plano,self.superuser,catalogo=True)
        linha=op.empresas.get(empresa=self.destino)
        linha.status='incerto';linha.passos=[{'status':'incerto'}];linha.save()
        outro=connection.copy(alias='verificacao-cancelamento-lock')
        chave='west-cadastro-categoria:'+str(op.pk)
        try:
            with outro.cursor() as cursor: cursor.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',[chave])
            with patch('apps.replicacao.omie.listar') as ler:
                central.verificar_cadastro(linha.pk,self.superuser.pk)
            ler.assert_not_called()
            linha.refresh_from_db();self.assertEqual(linha.status,'incerto')
        finally:
            with outro.cursor() as cursor: cursor.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',[chave])
            outro.close()
