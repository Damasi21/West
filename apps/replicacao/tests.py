from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch, MagicMock
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa, EmpresaUsuario, IntegracaoOmie, CategoriaOmie, AmbienteWhiteLabel, ContaDRE
from apps.empresas.omie import _salvar_categorias
from apps.empresas.white_label_domains import _marca_host, marca_host_atual
from . import omie
from .comparacao import dados, semelhanca
from .forms import PlanoForm
from .models import PlanoReplicacao, DestinoReplicacao, VinculoCategoria, ComparacaoReplicacao, ItemReplicacao
from .permissions import empresas_gerenciaveis, planos_permitidos
from .services import solicitar_comparacao, executar_comparacao, aprovar, executar_envio, verificar_item, resolver_item, publicar


def categoria(codigo, descricao, *, grupo=False, pai="", **extra):
    return {"codigo": codigo, "descricao": descricao, "natureza": "", "tipo_categoria": "",
            "categoria_superior": pai, "totalizadora": "S" if grupo else "N", "conta_despesa": "S",
            "conta_receita": "N", "conta_inativa": "N", "transferencia": "N", **extra}


class OmieSimulada:
    def __init__(self, catalogos):
        self.catalogos = deepcopy(catalogos)
        self.escritas = []
        self.falha = None

    def listar(self, integracao, descricao=""):
        itens = deepcopy(self.catalogos[integracao.empresa_id])
        return [c for c in itens if descricao.casefold() in c["descricao"].casefold()]

    def chamada(self, integracao, metodo, payload):
        self.escritas.append((integracao.empresa_id, metodo, deepcopy(payload)))
        if self.falha == "recusada":
            raise omie.OmieRecusada()
        catalogo = self.catalogos[integracao.empresa_id]
        if metodo.startswith("Incluir"):
            grupo = metodo == "IncluirGrupoCategoria"
            codigo = f"2.{9 + len(self.escritas):02d}" if grupo else payload["categoria_superior"]+f".{len(self.escritas):02d}"
            numero = len(self.escritas)
            while codigo in {c['codigo'] for c in catalogo}:
                numero += 1
                codigo = f"2.{9 + numero:02d}" if grupo else payload["categoria_superior"]+f".{numero:02d}"
            novo = categoria(codigo, payload["descricao"], grupo=grupo, pai="2" if grupo else payload["categoria_superior"])
            novo.update({k:v for k,v in payload.items() if k not in {"tipo_grupo"}})
            catalogo.append(novo)
        else:
            codigo = payload["codigo"]
            next(c for c in catalogo if c["codigo"] == codigo).update(payload)
        if self.falha == "apos_gravar":
            raise omie.OmieIncerta()
        return {"codigo_status": "0", "codigo": codigo}


class ReplicacaoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_user(username="rep-super", is_superuser=True, is_staff=True)
        self.gestor = User.objects.create_user(username="rep-gestor")
        self.lider = User.objects.create_user(username="rep-lider")
        self.viewer = User.objects.create_user(username="rep-viewer")
        self.matriz = Empresa.objects.create(nome="Matriz", nome_fantasia="Matriz", cnpj="11111111000111")
        self.destino = Empresa.objects.create(nome="Destino B", nome_fantasia="Destino B", cnpj="22222222000122")
        self.fora = Empresa.objects.create(nome="Destino externo", nome_fantasia="Destino externo", cnpj="33333333000133")
        for empresa in (self.matriz, self.destino, self.fora):
            integracao = IntegracaoOmie(empresa=empresa, app_key=f"app-{empresa.pk}")
            integracao.definir_app_secret("segredo-teste")
            integracao.save()
        for empresa in (self.matriz, self.destino):
            for usuario, papel in ((self.gestor,"gestor"),(self.lider,"lider"),(self.viewer,"viewer")):
                EmpresaUsuario.objects.create(empresa=empresa,usuario=usuario,papel=papel)
        self.plano = PlanoReplicacao.objects.create(nome="Padronização", matriz=self.matriz, criado_por=self.superuser)
        self.alvo = DestinoReplicacao.objects.create(plano=self.plano,empresa=self.destino)
        self.raiz = categoria("2", "Despesas", grupo=True)
        self.grupo = categoria("2.01", "Operacionais", grupo=True,pai="2")
        self.filha = categoria("2.01.01", "Energia elétrica", pai="2.01", codigo_dre="MATRIZ")
        self.grupo_destino = categoria("2.08", "Operacionais", grupo=True,pai="2")
        self.filha_destino = categoria("2.08.07", "Energia elétrica", pai="2.08", codigo_dre="LOCAL")
        self.api = OmieSimulada({self.matriz.pk:[self.raiz,self.grupo,self.filha],self.destino.pk:[self.raiz,self.grupo_destino,self.filha_destino],self.fora.pk:[self.raiz]})
        self.patches = [patch('apps.replicacao.omie.listar',side_effect=self.api.listar),patch('apps.replicacao.omie.chamada',side_effect=self.api.chamada)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def comparar(self, usuario=None):
        comp = solicitar_comparacao(self.plano, usuario or self.superuser)
        executar_comparacao(comp.pk)
        comp.refresh_from_db()
        self.assertEqual(comp.status,"pronta",comp.mensagem)
        return comp

    def item(self, comp, grupo=False, empresa=None):
        return comp.itens.get(destino__empresa=empresa or self.destino,origem__codigo="2.01" if grupo else "2.01.01")

    def enviar(self, comp, itens):
        aprovar(comp,self.superuser,[i.pk for i in itens])
        executar_envio(comp.pk)
        for item in itens: item.refresh_from_db()

    def test_comparacao_consulta_omie_nao_escreve_e_mapeia_codigos_distintos(self):
        comp = self.comparar()
        self.assertEqual(self.item(comp).situacao,"igual")
        self.assertEqual(self.item(comp).categoria.codigo,"2.08.07")
        self.assertEqual(comp.itens.get(origem__codigo="2").situacao,"bloqueado")
        self.assertEqual(self.api.escritas,[])
        self.assertFalse(VinculoCategoria.objects.exists())

    def test_confirmar_iguais_so_cria_vinculos_e_preserva_dre_local(self):
        comp = self.comparar()
        filha = self.item(comp)
        conta_dre = ContaDRE.objects.create(empresa=self.destino,nome="DRE personalizada")
        CategoriaOmie.objects.filter(pk=filha.categoria_id).update(conta_dre=conta_dre)
        self.enviar(comp,[self.item(comp,True),filha])
        self.assertEqual(filha.status,"sucesso",filha.mensagem)
        self.assertEqual(self.api.escritas,[])
        self.assertEqual(VinculoCategoria.objects.count(),2)
        filha.categoria.refresh_from_db()
        self.assertEqual(filha.categoria.codigo_dre,"LOCAL")
        self.assertEqual(filha.categoria.conta_dre_id,conta_dre.pk)

    def test_incluir_grupo_antes_da_filha_e_confirmar_codigo_retornado(self):
        self.api.catalogos[self.destino.pk] = [self.raiz]
        comp = self.comparar()
        grupo,filha = self.item(comp,True),self.item(comp)
        self.enviar(comp,[grupo,filha])
        self.assertEqual([e[1] for e in self.api.escritas],["IncluirGrupoCategoria","IncluirCategoria"])
        self.assertEqual(grupo.status,"sucesso",grupo.mensagem)
        self.assertEqual(filha.status,"sucesso",filha.mensagem)
        self.assertEqual(self.api.escritas[1][2]['categoria_superior'],grupo.codigo_confirmado)
        self.assertNotEqual(filha.codigo_confirmado,"2.01.01")
        self.assertEqual(VinculoCategoria.objects.count(),2)

    def test_alteracao_usa_codigo_destino_e_nao_envia_dre_ou_inativacao(self):
        comp = self.comparar()
        self.enviar(comp,[self.item(comp,True),self.item(comp)])
        self.api.catalogos[self.matriz.pk][-1]["descricao"] = "Energia e iluminação"
        comp = self.comparar()
        item = self.item(comp)
        self.assertEqual(item.situacao,"alterar")
        self.enviar(comp,[item])
        self.assertEqual(item.status,"sucesso",item.mensagem)
        payload = self.api.escritas[-1][2]
        self.assertEqual(payload['codigo'],"2.08.07")
        self.assertNotIn('codigo_dre',payload)
        self.assertNotIn('conta_inativa',payload)

    def test_alterar_grupo_usa_metodo_proprio(self):
        comp = self.comparar()
        self.enviar(comp,[self.item(comp,True),self.item(comp)])
        self.api.catalogos[self.matriz.pk][1]['descricao'] = 'Custos operacionais'
        comp = self.comparar()
        item=self.item(comp,True)
        self.enviar(comp,[item])
        self.assertEqual(item.status,'sucesso',item.mensagem)
        self.assertEqual(self.api.escritas[-1][1],'AlterarGrupoCategoria')

    def test_filha_exige_grupo_selecionado_ou_vinculado(self):
        comp=self.comparar()
        with self.assertRaises(ValidationError): aprovar(comp,self.superuser,[self.item(comp).pk])
        self.assertEqual(self.api.escritas,[])

    def test_mesmo_codigo_com_descricao_diferente_exige_resolucao(self):
        self.api.catalogos[self.destino.pk]=[self.raiz,self.grupo,categoria('2.01.01','Telefonia',pai='2.01')]
        comp=self.comparar()
        item=self.item(comp)
        self.assertEqual(item.situacao,'ambiguo')
        resolver_item(item,self.superuser,categoria_id=CategoriaOmie.objects.get(empresa=self.destino,codigo='2.01.01').pk)
        item.refresh_from_db()
        self.assertEqual(item.situacao,'alterar')
        self.assertEqual(self.api.escritas,[])

    def test_nomes_repetidos_sao_ambiguos(self):
        self.api.catalogos[self.destino.pk].append(categoria('2.08.08','Energia elétrica',pai='2.08'))
        comp=self.comparar()
        self.assertEqual(self.item(comp).situacao,'ambiguo')

    def preparar_aluguel(self, descricao_destino='Aluguéis'):
        self.api.catalogos[self.matriz.pk][-1]['descricao']='Aluguel'
        self.api.catalogos[self.destino.pk][-1]['descricao']=descricao_destino

    def test_plural_sugere_revisao_sem_vincular_ou_enviar(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        self.assertEqual(item.situacao,'ambiguo')
        self.assertIsNone(item.categoria_id)
        self.assertIn('semelhantes',item.mensagem)
        self.assertEqual(item.candidatos,[CategoriaOmie.objects.get(empresa=self.destino,codigo='2.08.07').pk])
        with self.assertRaises(ValidationError): aprovar(comp,self.superuser,[self.item(comp,True).pk,item.pk])
        self.assertFalse(VinculoCategoria.objects.exists())
        self.assertEqual(self.api.escritas,[])

    def test_modelo_anterior_pode_criar_item_durante_transicao_de_versao(self):
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader
        comp=self.comparar()
        origem=CategoriaOmie.objects.create(empresa=self.matriz,codigo='2.01.99',descricao='Cadastro anterior')
        historico=MigrationLoader(connection).project_state([('replicacao','0002_comparacaoreplicacao_aplicativos')]).apps.get_model('replicacao','ItemReplicacao')
        antigo=historico.objects.create(comparacao_id=comp.pk,destino_id=self.alvo.pk,origem_id=origem.pk,situacao='criar',caminho='Cadastro anterior')
        self.assertEqual(ItemReplicacao.objects.get(pk=antigo.pk).revisao_inclusao,{})

    def test_revisao_de_plural_padroniza_descricao_preservando_codigo_destino(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        categoria_id=CategoriaOmie.objects.get(empresa=self.destino,codigo='2.08.07').pk
        resolver_item(item,self.superuser,categoria_id=categoria_id)
        item.refresh_from_db()
        self.assertEqual(item.situacao,'alterar')
        self.enviar(comp,[self.item(comp,True),item])
        self.assertEqual(item.status,'sucesso',item.mensagem)
        self.assertEqual(item.categoria_id,categoria_id)
        self.assertEqual(self.api.escritas[-1][1],'AlterarCategoria')
        self.assertEqual(self.api.escritas[-1][2]['codigo'],'2.08.07')
        self.assertEqual(item.categoria.descricao,'Aluguel')

    def test_usuario_pode_escolher_criar_apos_revisar_semelhantes(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        resolver_item(item,self.superuser,criar=True)
        item.refresh_from_db()
        self.assertEqual(item.situacao,'criar')
        self.assertTrue(item.revisao_inclusao['assinatura'])
        self.assertEqual(item.revisao_inclusao['usuario_id'],self.superuser.pk)
        self.enviar(comp,[self.item(comp,True),item])
        self.assertEqual(item.status,'sucesso',item.mensagem)
        self.assertEqual(self.api.escritas[-1][1],'IncluirCategoria')
        self.assertEqual(next(c for c in self.api.catalogos[self.destino.pk] if c['codigo']=='2.08.07')['descricao'],'Aluguéis')

    def test_previa_antiga_nao_libera_criar_sem_revisar_semelhantes(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        comp.itens.filter(pk=item.pk).update(situacao='criar',candidatos=[])
        with self.assertRaises(ValidationError): aprovar(comp,self.superuser,[self.item(comp,True).pk,item.pk])
        self.assertEqual(self.api.escritas,[])

    def test_semelhante_aparece_depois_da_aprovacao_bloqueia_inclusao(self):
        self.api.catalogos[self.matriz.pk][-1]['descricao']='Aluguel'
        self.api.catalogos[self.destino.pk]=[self.raiz,self.grupo_destino]
        comp=self.comparar()
        item=self.item(comp)
        self.assertEqual(item.situacao,'criar')
        aprovar(comp,self.superuser,[self.item(comp,True).pk,item.pk])
        self.api.catalogos[self.destino.pk].append(categoria('2.08.07','Aluguéis',pai='2.08'))
        executar_envio(comp.pk)
        item.refresh_from_db()
        self.assertEqual(item.status,'erro')
        self.assertIn('semelhante',item.mensagem)
        self.assertEqual(self.api.escritas,[])

    def test_revisao_explicita_expira_se_aparece_outro_semelhante(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        resolver_item(item,self.superuser,criar=True)
        aprovar(comp,self.superuser,[self.item(comp,True).pk,item.pk])
        self.api.catalogos[self.destino.pk].append(categoria('2.08.08','ALUGUEIS',pai='2.08'))
        executar_envio(comp.pk)
        item.refresh_from_db()
        self.assertEqual(item.status,'erro')
        self.assertEqual(self.api.escritas,[])

    def test_semelhanca_nao_cruza_grupo_receita_inatividade_ou_empresa(self):
        self.api.catalogos[self.matriz.pk][-1]['descricao']='Aluguel'
        self.api.catalogos[self.destino.pk]=[self.raiz,self.grupo_destino,
            categoria('2.09','Financeiro',grupo=True,pai='2'),
            categoria('2.09.01','Aluguéis',pai='2.09'),
            categoria('1.08.01','Aluguéis',pai='1.08',conta_despesa='N',conta_receita='S'),
            categoria('2.08.11','Aluguéis',pai='2.08',conta_inativa='S'),
            categoria('2.08.12','Aluguéis',pai='2.08',transferencia='S')]
        _salvar_categorias(self.fora,[categoria('2.08.07','Aluguéis',pai='2.08')])
        comp=self.comparar()
        self.assertEqual(self.item(comp).situacao,'criar')
        self.assertEqual(self.item(comp).candidatos,[])

    def test_tela_destaca_sugestao_sem_pre_selecionar_destino(self):
        self.preparar_aluguel()
        comp=self.comparar()
        item=self.item(comp)
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'Nomes semelhantes no destino:')
        self.assertContains(response,'Aluguéis')
        response=self.client.get(reverse('replicacao:resolver',args=[self.plano.pk,item.pk]))
        self.assertContains(response,'Nomes semelhantes encontrados no destino')
        self.assertContains(response,'Nomes semelhantes — revisar')
        self.assertNotContains(response,' selected')
        self.assertEqual(self.api.escritas,[])

    def test_igualdade_exata_tem_preferencia_sobre_nomes_parecidos(self):
        self.preparar_aluguel(descricao_destino='Aluguel')
        self.api.catalogos[self.destino.pk].append(categoria('2.08.08','Aluguéis',pai='2.08'))
        comp=self.comparar()
        self.assertEqual(self.item(comp).situacao,'igual')
        self.assertEqual(self.item(comp).categoria.codigo,'2.08.07')

    def test_numeros_distintos_e_siglas_curtas_nao_sao_sugeridos(self):
        self.assertEqual(semelhanca('Aluguel sala 1','Aluguel sala 2'),0)
        self.assertEqual(semelhanca('ISS','ICMS'),0)
        self.assertEqual(semelhanca('Taxa 2025','Taxa 2026'),0)
        self.assertEqual(semelhanca('Aluguel','Locação'),0)
        for origem,destino in [('Aluguel','Aluguéis'),('Manutenção','Manutenções'),('Serviço','Serviços'),('Manutenção predial','Manutencao prediall')]:
            with self.subTest(origem=origem,destino=destino): self.assertGreaterEqual(semelhanca(origem,destino),.8)

    def test_resolver_nao_aceita_categoria_de_outra_empresa_ou_tipo(self):
        comp=self.comparar()
        estrangeira=CategoriaOmie.objects.create(empresa=self.fora,codigo='2.08.01',descricao='Energia elétrica')
        with self.assertRaises(ValidationError): resolver_item(self.item(comp),self.superuser,categoria_id=estrangeira.pk)

    def test_nome_igual_em_grupo_diferente_nao_e_correspondencia(self):
        self.api.catalogos[self.destino.pk] = [self.raiz,categoria('2.09','Financeiro',grupo=True,pai='2'),categoria('2.09.01','Energia elétrica',pai='2.09')]
        comp=self.comparar()
        self.assertEqual(self.item(comp).situacao,'criar')
        self.assertIsNone(self.item(comp).categoria_id)

    def test_bloqueia_inativas_transferencias_e_descricao_excedida(self):
        for campo,valor in [('conta_inativa','S'),('transferencia','S'),('descricao','X'*51)]:
            with self.subTest(campo=campo):
                self.api.catalogos[self.matriz.pk][-1]=dict(self.filha,**{campo:valor})
                comp=self.comparar()
                self.assertEqual(self.item(comp).situacao,'bloqueado')

    def test_aprovacao_rejeita_dado_local_alterado_apos_previa(self):
        comp=self.comparar()
        item=self.item(comp)
        CategoriaOmie.objects.filter(pk=item.origem_id).update(descricao='Alterado')
        with self.assertRaises(ValidationError): aprovar(comp,self.superuser,[self.item(comp,True).pk,item.pk])

    def test_revalida_matriz_remota_antes_de_escrever(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo,filha=self.item(comp,True),self.item(comp)
        aprovar(comp,self.superuser,[grupo.pk,filha.pk])
        self.api.catalogos[self.matriz.pk][1]['descricao']='Mudou na OMIE'
        executar_envio(comp.pk)
        grupo.refresh_from_db()
        self.assertEqual(grupo.status,'erro')
        self.assertEqual(self.api.escritas,[])

    def test_revalida_destino_remoto_antes_de_alterar(self):
        comp=self.comparar()
        self.enviar(comp,[self.item(comp,True),self.item(comp)])
        self.api.catalogos[self.matriz.pk][-1]['descricao']='Energia atualizada'
        comp=self.comparar()
        item=self.item(comp)
        aprovar(comp,self.superuser,[item.pk])
        self.api.catalogos[self.destino.pk][-1]['descricao']='Alteração local no destino'
        executar_envio(comp.pk)
        item.refresh_from_db()
        self.assertEqual(item.status,'erro')
        self.assertEqual(self.api.escritas,[])

    def test_resultado_incerto_nunca_repete_inclusao_e_exige_verificacao(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo=self.item(comp,True)
        self.api.falha='apos_gravar'
        self.enviar(comp,[grupo])
        self.assertEqual(grupo.status,'incerto')
        self.assertEqual(len(self.api.escritas),1)
        executar_envio(comp.pk)
        self.assertEqual(len(self.api.escritas),1)
        self.api.falha=None
        novo_codigo=self.api.catalogos[self.destino.pk][-1]['codigo']
        verificar_item(grupo,self.superuser,codigo=novo_codigo)
        grupo.refresh_from_db()
        self.assertEqual(grupo.status,'sucesso',grupo.mensagem)
        self.assertEqual(len(self.api.escritas),1)

    def test_recusa_de_grupo_nao_envia_filhas(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo,filha=self.item(comp,True),self.item(comp)
        self.api.falha='recusada'
        self.enviar(comp,[grupo,filha])
        self.assertEqual(grupo.status,'erro')
        self.assertEqual(filha.status,'erro')
        self.assertEqual(len(self.api.escritas),1)

    def test_perda_de_permissao_antes_worker_nao_escreve(self):
        comp=self.comparar(self.gestor)
        aprovar(comp,self.gestor,[self.item(comp,True).pk,self.item(comp).pk])
        EmpresaUsuario.objects.filter(usuario=self.gestor,empresa=self.destino).update(ativo=False)
        executar_envio(comp.pk)
        self.assertEqual(self.api.escritas,[])
        self.assertTrue(comp.itens.filter(status='erro').exists())

    def test_duplicata_de_task_nao_repete_escritas(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        self.enviar(comp,[self.item(comp,True),self.item(comp)])
        executar_envio(comp.pk)
        self.assertEqual(len(self.api.escritas),2)

    def test_troca_de_aplicativo_apos_aprovacao_nao_envia_para_nova_base(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo=self.item(comp,True)
        aprovar(comp,self.superuser,[grupo.pk])
        IntegracaoOmie.objects.filter(empresa=self.destino).update(app_key='outra-base-omie')
        executar_envio(comp.pk)
        grupo.refresh_from_db()
        self.assertEqual(grupo.status,'erro')
        self.assertEqual(self.api.escritas,[])

    def test_superusuario_desativado_antes_worker_nao_envia(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo=self.item(comp,True)
        aprovar(comp,self.superuser,[grupo.pk])
        get_user_model().objects.filter(pk=self.superuser.pk).update(is_active=False)
        executar_envio(comp.pk)
        self.assertEqual(self.api.escritas,[])

    def test_erro_em_um_destino_nao_interrompe_outro(self):
        DestinoReplicacao.objects.create(plano=self.plano,empresa=self.fora)
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        a,b=self.item(comp,True),self.item(comp,True,empresa=self.fora)
        real=self.api.chamada
        def falhar_um(integracao,metodo,payload):
            if integracao.empresa_id==self.destino.pk: raise omie.OmieRecusada()
            return real(integracao,metodo,payload)
        with patch('apps.replicacao.omie.chamada',side_effect=falhar_um): self.enviar(comp,[a,b])
        self.assertEqual(a.status,'erro')
        self.assertEqual(b.status,'sucesso',b.mensagem)

    def test_plano_nao_admite_duas_comparacoes_ativas(self):
        comp=solicitar_comparacao(self.plano,self.superuser)
        with self.assertRaises(ValidationError): solicitar_comparacao(self.plano,self.superuser)
        self.assertEqual(comp.status,'fila')

    def test_aprovar_item_de_outra_comparacao_rejeita_ids_adulterados(self):
        primeira=self.comparar()
        segunda=self.comparar()
        with self.assertRaises(PermissionDenied): aprovar(primeira,self.superuser,[self.item(segunda).pk])

    def test_erro_de_broker_mantem_fila_e_nao_grava_omie(self):
        comp=solicitar_comparacao(self.plano,self.superuser)
        with patch('apps.replicacao.tasks.comparar_categorias.apply_async',side_effect=RuntimeError('broker')):
            self.assertFalse(publicar(comp))
        comp.refresh_from_db()
        self.assertEqual(comp.status,'fila')
        self.assertEqual(self.api.escritas,[])

    def test_pausa_exige_tratar_resultado_incerto(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        self.api.falha='apos_gravar'
        self.enviar(comp,[self.item(comp,True)])
        self.client.force_login(self.superuser)
        self.client.post(reverse('replicacao:alternar',args=[self.plano.pk]))
        self.plano.refresh_from_db()
        self.assertTrue(self.plano.ativo)

    def test_pausa_e_reativacao_sem_envios_pendentes(self):
        self.client.force_login(self.superuser)
        url=reverse('replicacao:alternar',args=[self.plano.pk])
        self.client.post(url);self.plano.refresh_from_db()
        self.assertFalse(self.plano.ativo)
        self.client.post(url);self.plano.refresh_from_db()
        self.assertTrue(self.plano.ativo)

    def test_espera_expirada_nao_libera_reenvio_de_inclusao(self):
        self.api.catalogos[self.destino.pk]=[self.raiz]
        comp=self.comparar()
        grupo,filha=self.item(comp,True),self.item(comp)
        aprovar(comp,self.superuser,[grupo.pk,filha.pk])
        antigo=timezone.now()-timedelta(minutes=31)
        ComparacaoReplicacao.objects.filter(pk=comp.pk).update(iniciada_em=antigo,atualizada_em=antigo)
        ItemReplicacao.objects.filter(pk=grupo.pk).update(status='executando',metodo='IncluirGrupoCategoria',atualizado_em=antigo)
        self.client.force_login(self.superuser)
        self.client.post(reverse('replicacao:atualizar_situacao',args=[self.plano.pk,comp.pk]))
        grupo.refresh_from_db();filha.refresh_from_db()
        self.assertEqual(grupo.status,'incerto')
        self.assertEqual(filha.status,'erro')
        executar_envio(comp.pk)
        self.assertEqual(self.api.escritas,[])

    def test_csrf_impede_acionar_envio_por_post_sem_token(self):
        comp=self.comparar()
        client=Client(enforce_csrf_checks=True);client.force_login(self.superuser)
        response=client.post(reverse('replicacao:enviar',args=[self.plano.pk,comp.pk]),{'confirmar':'sim','itens':[self.item(comp,True).pk]})
        self.assertEqual(response.status_code,403)
        self.assertFalse(comp.itens.filter(status='fila').exists())
        self.assertEqual(self.api.escritas,[])

    def test_empresa_sem_integracao_ativa_bloqueia_fluxo(self):
        IntegracaoOmie.objects.filter(empresa=self.destino).update(ativa=False)
        with self.assertRaises(PermissionDenied): solicitar_comparacao(self.plano,self.superuser)

    def test_aplicativos_iguais_na_matriz_e_destino_sao_rejeitados(self):
        IntegracaoOmie.objects.filter(empresa=self.destino).update(app_key=self.matriz.integracao_omie.app_key)
        with self.assertRaises(PermissionDenied): solicitar_comparacao(self.plano,self.superuser)

    def test_menu_e_views_somente_para_master_em_duas_empresas(self):
        url=reverse('replicacao:lista')
        for user in (self.lider,self.viewer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertNotContains(self.client.get(reverse('empresas:lista')), 'href="'+url+'"')
        self.client.force_login(self.gestor)
        self.assertContains(self.client.get(url),'Padronização')
        self.assertContains(self.client.get(reverse('empresas:lista')),'href="'+url+'"')

    def test_detalhe_e_revisao_exibem_comparacao_sem_escrever(self):
        comp=self.comparar()
        self.client.force_login(self.superuser)
        response=self.client.get(reverse('replicacao:detalhe',args=[self.plano.pk]))
        self.assertContains(response,'Categoria da matriz')
        self.assertContains(response,'Confirmar vínculo')
        self.assertContains(response,'Correspondência ambígua')
        self.assertContains(response,'name="confirmar"')
        self.assertContains(self.client.get(reverse('replicacao:resolver',args=[self.plano.pk,self.item(comp).pk])),'Resolver correspondência')
        self.assertEqual(self.api.escritas,[])

    @patch('apps.replicacao.tasks.replicar_categorias.apply_async')
    def test_envio_exige_confirmacao_explicita(self, publicar_task):
        comp=self.comparar()
        self.client.force_login(self.superuser)
        self.client.post(reverse('replicacao:enviar',args=[self.plano.pk,comp.pk]),{'itens':[self.item(comp,True).pk,self.item(comp).pk]})
        self.assertFalse(comp.itens.filter(status='fila').exists())
        publicar_task.assert_not_called()

    def test_formulario_rejeita_matriz_como_destino_e_empresas_nao_gerenciadas(self):
        for destinos in ([self.matriz.pk],[self.fora.pk]):
            form=PlanoForm({'nome':'Novo','matriz':self.matriz.pk,'destinos':destinos},usuario=self.gestor)
            self.assertFalse(form.is_valid())

    def test_graph_rejeita_matriz_que_ja_e_destino(self):
        form=PlanoForm({'nome':'Ciclo','matriz':self.destino.pk,'destinos':[self.fora.pk]},usuario=self.superuser)
        self.assertTrue(form.is_valid(),form.errors)
        with self.assertRaises(ValidationError): form.salvar()

    def test_white_label_restringe_formulario_urls_e_worker(self):
        marca=AmbienteWhiteLabel.objects.create(nome='Marca Rep',slug='marca-rep')
        marca.empresas.add(self.matriz,self.destino)
        marca.administradores.add(self.gestor)
        self.plano.marca=marca;self.plano.save()
        token=_marca_host.set(marca)
        try:
            self.assertEqual(set(empresas_gerenciaveis(self.superuser).values_list('pk',flat=True)),{self.matriz.pk,self.destino.pk})
            self.assertTrue(planos_permitidos(self.gestor).filter(pk=self.plano.pk).exists())
            form=PlanoForm({'nome':'Fora','matriz':self.matriz.pk,'destinos':[self.fora.pk]},usuario=self.superuser)
            self.assertFalse(form.is_valid())
            comp=solicitar_comparacao(self.plano,self.gestor)
        finally:
            _marca_host.reset(token)
        marca.empresas.remove(self.destino)
        executar_comparacao(comp.pk)
        comp.refresh_from_db()
        self.assertEqual(comp.status,'erro')
        self.assertIsNone(marca_host_atual())

    @override_settings(ALLOWED_HOSTS=['testserver','rep.example.com'])
    def test_host_externo_nao_abre_plano_do_site_principal(self):
        marca=AmbienteWhiteLabel.objects.create(nome='Rep domínio',slug='rep-dominio',dominio='rep.example.com',dominio_ativo=True)
        marca.empresas.add(self.matriz,self.destino)
        client=Client(HTTP_HOST='rep.example.com');client.force_login(self.superuser)
        self.assertEqual(client.get(reverse('replicacao:detalhe',args=[self.plano.pk])).status_code,404)
        self.assertEqual(client.post(reverse('replicacao:comparar',args=[self.plano.pk])).status_code,404)


class ContratoOmieTests(TestCase):
    def setUp(self):
        self.integracao=MagicMock(app_key='chave-teste')
        self.integracao.obter_app_secret.return_value='segredo-nao-exibir'

    @patch('apps.replicacao.omie.urlopen')
    def test_escrita_uma_tentativa_status_vazio_e_resposta_vazia_nao_confirmam(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value=b'{}'
        with self.assertRaises(omie.OmieIncerta): omie.chamada(self.integracao,'IncluirCategoria',{'descricao':'Nova','categoria_superior':'2.01'})
        self.assertEqual(abrir.call_count,1)

    @patch('apps.replicacao.omie.urlopen')
    def test_timeout_nao_repete_e_nao_expoe_credenciais(self, abrir):
        abrir.side_effect=TimeoutError('segredo-nao-exibir')
        with self.assertRaises(omie.OmieIncerta) as erro: omie.chamada(self.integracao,'IncluirGrupoCategoria',{'descricao':'Novo','tipo_grupo':'D'})
        self.assertEqual(abrir.call_count,1)
        self.assertNotIn('segredo',str(erro.exception))

    @patch('apps.replicacao.omie.urlopen')
    def test_recusa_explicita_diferente_de_resultado_incerto(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value=json.dumps({'codigo_status':'123','descricao_status':'privado'}).encode()
        with self.assertRaises(omie.OmieRecusada): omie.chamada(self.integracao,'AlterarCategoria',{'codigo':'2.01.01','descricao':'Nova'})

    @patch('apps.replicacao.omie.chamada')
    def test_listagem_incompleta_nao_gera_snapshot(self, chamada):
        chamada.return_value={'categoria_cadastro':[],'total_de_paginas':2,'total_de_registros':5}
        with self.assertRaises(omie.OmieIncerta): omie.listar(self.integracao)

    @patch('apps.replicacao.omie.chamada')
    def test_paginacao_valida_e_filtro_na_confirmacao(self, chamada):
        chamada.side_effect=[{'categoria_cadastro':[categoria('2.01','Novo',grupo=True)],'total_de_paginas':2,'total_de_registros':2}, {'categoria_cadastro':[categoria('2.01.01','Nova',pai='2.01')],'total_de_paginas':2,'total_de_registros':2}]
        self.assertEqual(len(omie.listar(self.integracao,descricao='Nov')),2)
        self.assertEqual(chamada.call_args_list[1].args[2]['pagina'],2)
        self.assertEqual(chamada.call_args_list[1].args[2]['descricao'],'Nov')
