from copy import deepcopy
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from apps.empresas.models import CategoriaOmie
from apps.empresas.omie import _salvar_categorias
from . import central, lotes, test_central as fixtures
from .tests import categoria
from .models import CadastroCategoria, DestinoReplicacao


class SelecaoCategoriasTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)
        self.origem=CategoriaOmie.objects.get(empresa=self.matriz,codigo='2.01.01')

    def nova(self,codigo='2.01.09',descricao='Condomínio',**extra):
        registro=categoria(codigo,descricao,pai='2.01',codigo_dre='DRE',**extra)
        self.api.catalogos[self.matriz.pk].append(registro)
        _salvar_categorias(self.matriz,[registro])
        return CategoriaOmie.objects.get(empresa=self.matriz,codigo=codigo)

    def executar(self,op):
        central.executar_cadastro(op.pk);op.refresh_from_db();return op

    def previa(self,categorias=None,acao='replicar',destinos=None):
        op=lotes.solicitar(self.plano,self.superuser,[c.pk for c in (categorias or [self.origem])],destinos or [self.destino.pk],acao)
        self.executar(op)
        self.assertEqual(op.status,'revisao',op.mensagem)
        self.assertEqual(self.api.escritas,[])
        return op

    def aprovar(self,op,**escolhas):
        self.executar(lotes.confirmar(op,self.superuser,{'confirmar':'sim',**escolhas}))
        op.refresh_from_db();return op

    def test_previa_nao_escreve_e_duplicidade_ignora_mesmo_com_dre_diferente(self):
        antes=deepcopy(self.api.catalogos)
        op=self.previa();self.assertEqual(op.empresas.get().passos[0]['escolha'],'ignorar')
        op=self.aprovar(op)
        self.assertEqual(op.empresas.get().status,'ignorada',op.empresas.get().mensagem)
        self.assertEqual(self.api.catalogos,antes);self.assertEqual(self.api.escritas,[])

    def test_nome_parecido_exige_decisao_e_pode_usar_sem_renomear(self):
        origem=self.nova(descricao='Aluguel')
        self.api.catalogos[self.destino.pk].append(categoria('2.08.09','Aluguéis',pai='2.08'))
        op=self.previa([origem]);linha=op.empresas.get()
        self.assertEqual(linha.passos[0]['escolha'],'')
        with self.assertRaises(ValidationError):lotes.confirmar(op,self.superuser,{'confirmar':'sim'})
        self.aprovar(op,**{f'decisao_{linha.pk}_0':'usar:2.08.09'})
        self.assertEqual(self.api.escritas,[])
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)

    def test_grupo_e_apenas_filhos_marcados_receita_despesa_sem_raizes(self):
        nova=self.nova();self.nova('2.01.10','Licenciamento')
        receita=categoria('1.03','Reembolsos',grupo=True,pai='1',conta_receita='S',conta_despesa='N')
        self.api.catalogos[self.matriz.pk].append(receita);_salvar_categorias(self.matriz,[receita])
        grupo_receita=CategoriaOmie.objects.get(empresa=self.matriz,codigo='1.03')
        self.api.catalogos[self.destino.pk]=[]
        op=self.previa([grupo_receita,self.pai,nova]);self.aprovar(op)
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas],['IncluirGrupoCategoria','IncluirGrupoCategoria','IncluirCategoria'])
        self.assertEqual(self.api.escritas[0][2]['tipo_grupo'],'R')
        self.assertEqual(self.api.escritas[1][2]['tipo_grupo'],'D')
        self.assertEqual(self.api.escritas[2][2]['descricao'],'Condomínio')
        self.assertTrue(all(e==self.destino.pk for e,_,_ in self.api.escritas))

    def test_categoria_sem_grupo_ignorada_e_origem_inativa_nao_copiada(self):
        origem=self.nova();self.api.catalogos[self.destino.pk]=[]
        op=self.previa([origem]);self.assertIn('Grupo superior indisponível',op.empresas.get().passos[0]['situacao'])
        self.aprovar(op);self.assertEqual(self.api.escritas,[])
        origem=self.nova('2.01.10','Inativa',conta_inativa='S')
        op=self.previa([origem]);self.assertEqual(op.empresas.get().passos[0]['escolha'],'ignorar')
        self.aprovar(op);self.assertEqual(self.api.escritas,[])

    def test_inativar_reativar_preserva_grupos_e_metadados(self):
        for acao,flag in [('inativar','S'),('reativar','N')]:
            self.api.escritas.clear()
            op=self.previa([self.pai,self.origem],acao)
            self.assertEqual(len(op.empresas.get().passos),1)
            self.aprovar(op)
            self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
            self.assertEqual(self.api.escritas[0][2],{'codigo':'2.08.07','descricao':'Energia elétrica','conta_inativa':flag})
            self.assertEqual(self.api.catalogos[self.destino.pk][-1]['codigo_dre'],'LOCAL')

    def test_incerto_verifica_sem_reenviar_e_retoma_etapas_restantes(self):
        origem=self.nova();outra=self.nova('2.01.10','Licenciamento')
        op=self.previa([origem,outra]);self.api.falha='apos_gravar';self.aprovar(op)
        linha=op.empresas.get();self.assertEqual(linha.status,'incerto',linha.mensagem)
        with self.assertRaises(ValidationError):central.retomar(op,self.superuser)
        self.api.falha=None
        central.verificar_cadastro(linha.pk,self.superuser.pk,self.api.catalogos[self.destino.pk][-1]['codigo'])
        self.executar(central.retomar(op,self.superuser))
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual(len(self.api.escritas),2)

    def test_mudanca_no_destino_ou_pai_apos_previa_impede_envios(self):
        for base in [self.matriz,self.destino]:
            op=self.previa([self.nova(codigo='2.01.'+str(20+base.pk%50),descricao='Condomínio'+str(base.pk))])
            self.api.catalogos[base.pk][1]['descricao']+=' alterado'
            self.aprovar(op);self.assertEqual(self.api.escritas,[])
            self.assertTrue(central.situacao(op)['pendencias'])
            central.cancelar(op,self.superuser)

    def test_escolha_fora_das_opcoes_nao_autoriza_escrita(self):
        op=self.previa([self.nova()]);linha=op.empresas.get()
        with self.assertRaises(ValidationError):lotes.confirmar(op,self.superuser,{'confirmar':'sim',f'decisao_{linha.pk}_0':'usar:2.08.07'})
        self.assertEqual(self.api.escritas,[])

    def test_escopo_permissao_e_csrf(self):
        for usuario in [self.viewer,self.lider]:
            with self.assertRaises(PermissionDenied):lotes.solicitar(self.plano,usuario,[self.origem.pk],[self.destino.pk],'replicar')
        with self.assertRaises(PermissionDenied):lotes.solicitar(self.plano,self.superuser,[self.origem.pk],[self.fora.pk],'replicar')
        self.client.force_login(self.superuser)
        client=Client(enforce_csrf_checks=True);client.force_login(self.superuser)
        url=reverse('replicacao:selecionar_categorias',args=[self.plano.pk])
        self.assertEqual(client.post(url,{'categorias':[self.origem.pk],'destinos':[self.destino.pk],'acao':'replicar'}).status_code,403)
        with patch('apps.replicacao.central.publicar_cadastro') as publicar,self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,{'categorias':[self.origem.pk],'destinos':[self.destino.pk],'acao':'replicar'})
        self.assertEqual(response.status_code,302);publicar.assert_called_once()

    def test_telas_renderizam_previa_historico_e_selecao_configuracao(self):
        self.client.force_login(self.superuser)
        op=self.previa([self.nova()])
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk])+f'?cadastro={op.pk}')
        for texto in ['Departamentos','Projetos','Selecionar plano PAI','Conferir antes de enviar','Confirmar e executar','data-rep-selection','Histórico']:
            self.assertContains(response,texto)
        self.assertNotContains(response,'Preparar prévia do plano')
        response=self.client.get(reverse('replicacao:lista')+f'?plano={self.plano.pk}')
        self.assertRedirects(response,reverse('replicacao:detalhe',args=[self.plano.pk]))

    def test_novo_cadastro_escopo_plano_forca_todos_destinos(self):
        DestinoReplicacao.objects.create(plano=self.plano,empresa=self.fora)
        self.client.force_login(self.superuser)
        with patch('apps.replicacao.central.publicar_cadastro'),self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('replicacao:cadastrar',args=[self.plano.pk]),{'escopo':'plano','descricao':'Condomínio','pai':self.pai.pk,'destinos':[self.destino.pk],'confirmar':'sim'})
        op=CadastroCategoria.objects.latest('pk')
        self.assertEqual(set(op.pedido['destinos_ids']),{self.destino.pk,self.fora.pk})

    def test_recusa_real_aparece_na_tela_sem_falso_sucesso(self):
        op=self.previa([self.nova()])
        with patch('apps.replicacao.omie.chamada',side_effect=central.omie.OmieRecusada(codigo='102',detalhe='Descrição duplicada no grupo.')):
            self.aprovar(op)
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk])+f'?cadastro={op.pk}')
        self.assertContains(response,'Descrição duplicada no grupo.')
        self.assertContains(response,'Código OMIE 102')
        self.assertEqual(central.situacao(op)['resultado'],'pendente')

    def test_duplicidade_em_outro_grupo_nao_move_ou_renomeia(self):
        origem=self.nova()
        self.api.catalogos[self.destino.pk].append(categoria('2.99.01','Condomínio',pai='2.99'))
        antes=deepcopy(self.api.catalogos[self.destino.pk])
        op=self.previa([origem]);self.aprovar(op)
        self.assertEqual(self.api.escritas,[])
        self.assertEqual(self.api.catalogos[self.destino.pk],antes)

    def test_ignorar_grupo_ausente_impede_criar_filhas(self):
        origem=self.nova();self.api.catalogos[self.destino.pk]=[]
        op=self.previa([self.pai,origem]);linha=op.empresas.get()
        self.aprovar(op,**{f'decisao_{linha.pk}_0':'ignorar'})
        self.assertEqual(self.api.escritas,[])
        self.assertTrue(all(p['status']=='ignorada' for p in op.empresas.get().passos))

    def test_recusa_em_um_destino_nao_bloqueia_outro_destino(self):
        DestinoReplicacao.objects.create(plano=self.plano,empresa=self.fora)
        self.api.catalogos[self.fora.pk]=deepcopy(self.api.catalogos[self.destino.pk])
        op=self.previa([self.nova()],destinos=[self.destino.pk,self.fora.pk])
        def escrever(integracao,metodo,payload):
            if integracao.empresa_id==self.destino.pk:
                raise central.omie.OmieRecusada(codigo='102',detalhe='Restrição de cadastro.')
            return self.api.chamada(integracao,metodo,payload)
        with patch('apps.replicacao.omie.chamada',side_effect=escrever):self.aprovar(op)
        self.assertEqual(op.empresas.get(empresa=self.destino).status,'erro')
        self.assertEqual(op.empresas.get(empresa=self.fora).status,'sucesso')
        self.assertEqual(len(self.api.escritas),1)

    def test_cancelar_previa_nao_escreve_e_bloqueia_confirmacao(self):
        op=self.previa([self.nova()]);central.cancelar(op,self.superuser)
        with self.assertRaises(ValidationError):lotes.confirmar(op,self.superuser,{'confirmar':'sim'})
        self.assertEqual(self.api.escritas,[])
