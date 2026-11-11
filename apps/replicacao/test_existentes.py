from copy import deepcopy
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from apps.empresas.models import CategoriaOmie, AmbienteWhiteLabel
from apps.empresas.omie import _salvar_categorias
from . import central, existentes, test_central as fixtures
from .tests import categoria


class ReplicarExistenteTests(TestCase):
    def setUp(self):fixtures.CadastroCentralTests.setUp(self)

    def nova(self,codigo='2.01.09',descricao='Condomínio',**kwargs):
        dados=categoria(codigo,descricao,pai='2.01',codigo_dre='4.01',tipo_categoria='FC',**kwargs)
        self.api.catalogos[self.matriz.pk].append(dados)
        _salvar_categorias(self.matriz,[dados])
        return CategoriaOmie.objects.get(empresa=self.matriz,codigo=codigo)

    def solicitar(self,origem=None,filhos=False):
        return existentes.solicitar(self.plano,self.superuser,origem or self.nova(),[self.destino.pk],filhos)

    def executar(self,op):
        central.executar_cadastro(op.pk);op.refresh_from_db();return op

    def test_categoria_copia_metadados_sem_escrever_na_pai(self):
        origem=self.nova();antes=deepcopy(self.api.catalogos[self.matriz.pk])
        op=self.executar(self.solicitar(origem));linha=op.empresas.get()
        self.assertEqual(linha.status,'sucesso',linha.mensagem)
        self.assertEqual(list(op.empresas.values_list('empresa_id',flat=True)),[self.destino.pk])
        self.assertEqual(self.api.catalogos[self.matriz.pk],antes)
        self.assertEqual(len(self.api.escritas),1)
        empresa,metodo,payload=self.api.escritas[0]
        self.assertEqual((empresa,metodo),(self.destino.pk,'IncluirCategoria'))
        self.assertEqual(payload,{'descricao':'Condomínio','categoria_superior':'2.08','tipo_categoria':'FC','codigo_dre':'4.01'})
        self.assertNotIn('natureza',payload)

    def test_grupo_sozinho_nao_envia_seus_filhos(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        op=self.executar(self.solicitar(self.pai))
        self.assertEqual(op.empresas.get().status,'sucesso')
        self.assertEqual([m for _,m,_ in self.api.escritas],['IncluirGrupoCategoria'])

    def test_grupo_com_filhos_nao_inclui_inativos_ou_posicoes_disponiveis(self):
        self.nova();self.nova('2.01.10','Desativada',conta_inativa='S');self.nova('2.01.95','&lt;Disponível&gt;')
        self.api.catalogos[self.destino.pk]=[self.raiz]
        op=self.executar(self.solicitar(self.pai,True))
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas],['IncluirGrupoCategoria','IncluirCategoria','IncluirCategoria'])
        grupo=self.api.escritas[1][2]['categoria_superior']
        self.assertEqual(self.api.escritas[2][2]['categoria_superior'],grupo)
        self.assertTrue(all(e==self.destino.pk for e,_,_ in self.api.escritas))

    def test_multiplos_filhos_apos_reaproveitamento_usam_o_grupo_correto(self):
        self.api.catalogos[self.destino.pk][-1]['codigo_dre']='MATRIZ'
        self.nova();self.nova('2.01.10','Licenciamento')
        op=self.executar(self.solicitar(self.pai,True))
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual(len(self.api.escritas),2)
        self.assertTrue(all(p['categoria_superior']=='2.08' for _,_,p in self.api.escritas))

    def test_categoria_sem_grupo_identico_bloqueia_so_destino_sem_criar_pai(self):
        self.api.catalogos[self.destino.pk][1]['descricao']='Grupo diferente'
        op=self.executar(self.solicitar())
        self.assertEqual(op.empresas.get().status,'bloqueada')
        self.assertEqual(self.api.escritas,[])
        self.assertTrue(central.situacao(op)['pendencias'])

    def test_exata_existente_reaproveita_sem_escrita_e_divergente_exige_revisao(self):
        self.api.catalogos[self.destino.pk][-1]['codigo_dre']='MATRIZ'
        origem=CategoriaOmie.objects.get(empresa=self.matriz,codigo='2.01.01')
        op=self.executar(self.solicitar(origem))
        self.assertEqual(op.empresas.get().status,'sucesso')
        self.assertEqual(self.api.escritas,[])
        self.api.catalogos[self.destino.pk][-1]['codigo_dre']='LOCAL'
        op=self.executar(self.solicitar(origem))
        self.assertEqual(op.status,'revisao')
        self.assertFalse(op.empresas.get().passos[-1]['candidatos'][0]['compativel'])

    def test_origem_alterada_apos_solicitar_bloqueia_antes_de_escrever(self):
        origem=self.nova();op=self.solicitar(origem)
        self.api.catalogos[self.matriz.pk][-1]['codigo_dre']='OUTRO'
        self.executar(op)
        self.assertEqual(op.status,'erro')
        self.assertIn('mudou na base PAI',op.mensagem)
        self.assertEqual(self.api.escritas,[])

    def test_acesso_destinos_indevidos_e_origem_de_outra_empresa(self):
        origem=self.nova()
        for usuario in [self.viewer,self.lider]:
            with self.assertRaises(PermissionDenied):existentes.solicitar(self.plano,usuario,origem,[self.destino.pk])
        for ids in [[self.matriz.pk],[self.fora.pk],[],[self.destino.pk,self.destino.pk]]:
            with self.assertRaises((ValidationError,PermissionDenied)):existentes.solicitar(self.plano,self.superuser,origem,ids)
        _salvar_categorias(self.destino,self.api.catalogos[self.destino.pk])
        with self.assertRaises(PermissionDenied):existentes.solicitar(self.plano,self.superuser,CategoriaOmie.objects.get(empresa=self.destino,codigo='2.08'),[self.destino.pk])

    def test_inativo_nao_replicavel_e_categoria_nao_inclui_filhos(self):
        origem=self.nova()
        with self.assertRaises(ValidationError):self.solicitar(origem,True)
        origem.conta_inativa=True;origem.save()
        with self.assertRaises(ValidationError):self.solicitar(origem)

    def test_falha_incerta_verifica_e_retoma_sem_repetir_criacao(self):
        self.api.catalogos[self.destino.pk][-1]['codigo_dre']='MATRIZ'
        self.nova();self.nova('2.01.10','Licenciamento')
        op=self.solicitar(self.pai,True);self.api.falha='apos_gravar';self.executar(op)
        linha=op.empresas.get();self.assertEqual(linha.status,'incerto')
        with self.assertRaises(ValidationError):central.retomar(op,self.superuser)
        self.api.falha=None
        central.verificar_cadastro(linha.pk,self.superuser.pk,self.api.catalogos[self.destino.pk][-1]['codigo'])
        self.executar(central.retomar(op,self.superuser))
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual(len(self.api.escritas),2)
        self.assertTrue(all(p['categoria_superior']=='2.08' for _,_,p in self.api.escritas))

    def test_nome_codificado_e_enviado_literal_sem_alterar_snapshot(self):
        origem=self.nova(descricao='Servi&ccedil;os &amp; taxas')
        op=self.executar(self.solicitar(origem))
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas[-1][2]['descricao'],'Serviços & taxas')
        self.assertEqual(op.pedido['origens_existentes'][-1]['descricao'],'Servi&ccedil;os &amp; taxas')

    def test_tela_post_confirmacao_obrigatoria_e_card_plano_completo_inativo(self):
        origem=self.nova();self.client.force_login(self.superuser)
        url=reverse('replicacao:replicar_existente',args=[self.plano.pk,origem.pk])
        response=self.client.get(url)
        self.assertContains(response,'base PAI será somente consultada')
        self.assertNotContains(response,'name="incluir_filhos"')
        self.assertContains(self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk])),'Replicar existente')
        self.assertNotContains(self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk])),'Preparar prévia do plano')
        with patch('apps.replicacao.central.publicar_cadastro') as publicar:
            self.client.post(url,{'destinos':[self.destino.pk]})
            publicar.assert_not_called()
        client=Client(enforce_csrf_checks=True);client.force_login(self.superuser)
        self.assertEqual(client.post(url,{'destinos':[self.destino.pk],'confirmar':'on'}).status_code,403)
        with patch('apps.replicacao.central.publicar_cadastro') as publicar,self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,{'destinos':[self.destino.pk],'confirmar':'on'})
        self.assertEqual(response.status_code,302);publicar.assert_called_once()

    @override_settings(ALLOWED_HOSTS=['testserver','origem.example.com'])
    def test_isolamento_white_label(self):
        origem=self.nova();marca=AmbienteWhiteLabel.objects.create(nome='Origem',slug='origem',dominio='origem.example.com',dominio_ativo=True)
        marca.empresas.add(self.matriz,self.destino);self.plano.marca=marca;self.plano.save()
        self.client.force_login(self.superuser)
        url=reverse('replicacao:replicar_existente',args=[self.plano.pk,origem.pk])
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(url,HTTP_HOST='origem.example.com').status_code,200)

    def test_grupo_recusado_por_duplicidade_ignora_todos_os_filhos(self):
        self.nova();self.api.catalogos[self.destino.pk]=[self.raiz]
        op=self.solicitar(self.pai,True)
        with patch('apps.replicacao.omie.chamada',side_effect=central.omie.OmieRecusada(codigo='102',detalhe='Já existe grupo com essa descrição.')) as escrever:
            self.executar(op)
        self.assertEqual(escrever.call_count,1)
        self.assertEqual(op.empresas.get().status,'sucesso')
        self.assertTrue(all(p['status']=='ignorada' for p in op.empresas.get().passos))
