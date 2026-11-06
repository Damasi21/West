from copy import deepcopy
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.urls import reverse
from apps.empresas.models import EmpresaUsuario
from . import central, conciliacao, padronizacao, test_central as fixtures
from .models import VinculoCategoria
from .tests import categoria


def decisoes_padrao(op):
    linha=op.empresas.get();dados={"confirmar":"sim"}
    for i,item in enumerate(linha.passos):
        valores=[o["valor"] for o in item["opcoes"]]
        valor=item["escolha"] or ("criar" if "criar" in valores else valores[0])
        if item["secao"]=="destino":valor="manter"
        dados[f"decisao_{linha.pk}_{i}"]=valor
        if item.get("tem_divergencias"):dados[f"aceitar_{linha.pk}_{i}"]="sim"
    return dados


class ConciliacaoTests(TestCase):
    def setUp(self):fixtures.CadastroCentralTests.setUp(self)
    def executar(self,op):
        central.executar_cadastro(op.pk);op.refresh_from_db();return op
    def previa(self):return self.executar(conciliacao.solicitar(self.plano,self.superuser,[self.destino.pk]))
    def indice(self,op,codigo,secao="origem"):
        return next(i for i,p in enumerate(op.empresas.get().passos) if p["origem"]["codigo"]==codigo and p["secao"]==secao)
    def escolher(self,op,dados,codigo,valor,secao="origem"):
        dados[f"decisao_{op.empresas.get().pk}_{self.indice(op,codigo,secao)}"]=valor
    def enviar(self,op,dados=None):return self.executar(conciliacao.confirmar(op,self.superuser,dados or decisoes_padrao(op)))
    def nova_categoria(self):self.api.catalogos[self.destino.pk][-1]["descricao"]="Cadastro antigo"

    def test_previa_sem_escritas_com_origem_destino_e_decisoes(self):
        op=self.previa();self.assertEqual(op.status,"revisao",op.mensagem)
        self.assertEqual(op.modo,"conciliacao");self.assertEqual(self.api.escritas,[])
        self.assertEqual(len(op.empresas.get().passos),4)
        self.client.force_login(self.superuser)
        resposta=self.client.get(reverse("replicacao:detalhe",args=[self.plano.pk]))
        self.assertContains(resposta,"Prévia completa de conciliação")
        self.assertContains(resposta,"Cadastros atuais do FILHO")
        self.assertNotContains(resposta,"Adicionar ponto")

    def test_reaproveitar_preserva_nome_dre_tipo_e_observacoes(self):
        antes=deepcopy(self.api.catalogos[self.destino.pk]);op=self.enviar(self.previa())
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual(self.api.catalogos[self.destino.pk],antes);self.assertEqual(self.api.escritas,[])
        self.assertEqual(VinculoCategoria.objects.filter(destino=self.alvo).count(),2)

    def test_divergencia_exige_confirmacao_adicional(self):
        op=self.previa();dados={k:v for k,v in decisoes_padrao(op).items() if not k.startswith("aceitar_")}
        with self.assertRaises(ValidationError):conciliacao.confirmar(op,self.superuser,dados)
        op.refresh_from_db();self.assertEqual(op.status,"revisao");self.assertEqual(self.api.escritas,[])

    def test_criacao_antes_da_inativacao_sem_reclassificar_antigos(self):
        self.nova_categoria();antes=deepcopy(self.api.catalogos[self.destino.pk][-1])
        op=self.previa();dados=decisoes_padrao(op);self.escolher(op,dados,"2.08.07","inativar","destino")
        self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas],["IncluirCategoria","AlterarCategoria"])
        self.assertEqual(next(c for c in self.api.catalogos[self.destino.pk] if c["codigo"]=="2.08.07"),{**antes,"conta_inativa":"S"})

    def test_falha_na_inclusao_nao_inativa_antigos(self):
        self.nova_categoria();op=self.previa();dados=decisoes_padrao(op)
        self.escolher(op,dados,"2.08.07","inativar","destino");self.api.falha="recusada";self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,"erro")
        self.assertEqual([m for _,m,_ in self.api.escritas],["IncluirCategoria"])
        self.assertEqual(self.api.catalogos[self.destino.pk][-1]["conta_inativa"],"N")

    def test_incerto_bloqueia_e_retomada_nao_repete_inclusao_confirmada(self):
        self.nova_categoria();op=self.previa();dados=decisoes_padrao(op)
        self.escolher(op,dados,"2.08.07","inativar","destino");self.api.falha="apos_gravar";self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,"incerto")
        with self.assertRaises(ValidationError):central.retomar(op,self.superuser)
        self.assertEqual(len(self.api.escritas),1)
        codigo=self.api.catalogos[self.destino.pk][-1]["codigo"];self.api.falha=None
        central.verificar_cadastro(op.empresas.get().pk,self.superuser.pk,codigo)
        self.executar(central.retomar(op,self.superuser))
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas],["IncluirCategoria","AlterarCategoria"])

    def test_drift_na_preparacao_bloqueia_inativacoes(self):
        self.nova_categoria();op=self.previa();dados=decisoes_padrao(op)
        self.escolher(op,dados,"2.08.07","inativar","destino");original=self.api.chamada
        def escrever(i,m,p):
            resultado=original(i,m,p)
            if m=="IncluirCategoria":self.api.catalogos[self.destino.pk][1]["descricao"]="Mudanca externa"
            return resultado
        with patch('apps.replicacao.omie.chamada',side_effect=escrever):self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,"erro")
        self.assertFalse(any(m=="AlterarCategoria" for _,m,_ in self.api.escritas))

    def test_reaproveitada_nao_pode_ser_inativada(self):
        op=self.previa();dados=decisoes_padrao(op);self.escolher(op,dados,"2.08.07","inativar","destino")
        with self.assertRaises(ValidationError):conciliacao.confirmar(op,self.superuser,dados)
        self.assertEqual(self.api.escritas,[])

    def test_inativacao_sem_substituto_ativo_e_recusada(self):
        op=self.previa();dados=decisoes_padrao(op)
        self.escolher(op,dados,"2.01.01","ignorar");self.escolher(op,dados,"2.08.07","inativar","destino")
        with self.assertRaises(ValidationError):conciliacao.confirmar(op,self.superuser,dados)

    def test_inativo_e_reativado_explicitamente_sem_alterar_classificacao(self):
        alvo=self.api.catalogos[self.destino.pk][-1];alvo.update(conta_inativa="S",codigo_dre="MATRIZ")
        op=self.previa();self.assertEqual(op.empresas.get().passos[self.indice(op,"2.01.01")]["escolha"],"")
        antes=deepcopy(alvo);self.enviar(op)
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual(alvo,{**antes,"conta_inativa":"N"})
        self.assertEqual(self.api.escritas[0][2],{"codigo":"2.08.07","descricao":"Energia elétrica","conta_inativa":"N"})

    def test_grupo_faltante_criado_sem_renomear_grupos_antigos(self):
        self.api.catalogos[self.matriz.pk][1]["descricao"]="Novo grupo"
        antes=deepcopy(self.api.catalogos[self.destino.pk]);op=self.enviar(self.previa())
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas],["IncluirGrupoCategoria","IncluirCategoria"])
        self.assertEqual(self.api.catalogos[self.destino.pk][:len(antes)],antes)

    def test_grupo_inativo_de_mesmo_nome_nao_autoriza_duplicacao(self):
        self.api.catalogos[self.destino.pk][1]["conta_inativa"]="S"
        op=self.previa();self.assertEqual([o["valor"] for o in op.empresas.get().passos[0]["opcoes"]],["ignorar"])

    def test_categoria_inativa_com_mesmo_nome_nao_e_nome_livre(self):
        self.api.catalogos[self.destino.pk][-1]["conta_inativa"]="S"
        op=self.previa();item=op.empresas.get().passos[self.indice(op,"2.01.01")]
        self.assertNotIn("criar",[o["valor"] for o in item["opcoes"]])
        self.assertTrue(any(o["valor"].startswith("usar:") for o in item["opcoes"]))

    def test_ignorar_grupo_preserva_filhos(self):
        op=self.previa();dados=decisoes_padrao(op);self.escolher(op,dados,"2.01","ignorar");self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas,[])

    def test_ambiguidade_nao_e_escolhida_automaticamente(self):
        self.api.catalogos[self.destino.pk][-1]["codigo_dre"]="MATRIZ"
        self.api.catalogos[self.destino.pk].append(categoria("2.08.08","Energia elétrica",pai="2.08",codigo_dre="MATRIZ"))
        op=self.previa();self.assertEqual(op.empresas.get().passos[self.indice(op,"2.01.01")]["escolha"],"")

    def test_inativos_e_disponiveis_na_origem_nao_sao_copiados(self):
        self.api.catalogos[self.matriz.pk]+=[categoria("2.01.95","&lt;Disponível&gt;",pai="2.01"),categoria("2.01.96","Antiga",pai="2.01",conta_inativa="S")]
        op=self.previa();self.assertEqual({p["origem"]["codigo"] for p in op.empresas.get().passos if p["secao"]=="origem"},{"2.01","2.01.01"})

    def test_uma_empresa_e_escopo_administrativo_obrigatorios(self):
        with self.assertRaises(ValidationError):conciliacao.solicitar(self.plano,self.superuser,[self.destino.pk,self.fora.pk])
        with self.assertRaises(PermissionDenied):conciliacao.solicitar(self.plano,self.superuser,[self.fora.pk])
        with self.assertRaises(PermissionDenied):conciliacao.solicitar(self.plano,self.viewer,[self.destino.pk])

    def test_revogacao_apos_previa_bloqueia_confirmacao(self):
        op=self.previa();EmpresaUsuario.objects.filter(usuario=self.gestor,empresa=self.destino).delete()
        with self.assertRaises(PermissionDenied):conciliacao.confirmar(op,self.gestor,decisoes_padrao(op))
        self.assertEqual(self.api.escritas,[])

    def test_origem_mudou_antes_de_enviar(self):
        op=self.previa();dados=decisoes_padrao(op);self.api.catalogos[self.matriz.pk][-1]["descricao"]="Alterada"
        op=self.enviar(op,dados);self.assertEqual(op.status,"erro");self.assertEqual(self.api.escritas,[])

    def test_legacy_reescrita_nao_e_executada(self):
        op=padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk]);self.executar(op)
        self.assertEqual(op.status,"erro");self.assertIn("substituída",op.mensagem);self.assertEqual(self.api.escritas,[])

    def test_post_invalido_preserva_escolhas_sem_publicar_worker(self):
        op=self.previa();dados=decisoes_padrao(op);dados.pop("confirmar");self.client.force_login(self.superuser)
        with patch('apps.replicacao.tasks.cadastrar_categoria.apply_async') as publicar:
            resposta=self.client.post(reverse('replicacao:confirmar_padronizacao',args=[self.plano.pk,op.pk]),dados)
        self.assertEqual(resposta.status_code,200);self.assertContains(resposta,"Prévia completa de conciliação")
        publicar.assert_not_called();op.refresh_from_db();self.assertEqual(op.status,"revisao")

    def test_destino_fora_das_opcoes_nao_e_autorizado(self):
        op=self.previa();dados=decisoes_padrao(op);self.escolher(op,dados,"2.01.01","usar:2.99.99")
        with self.assertRaises(ValidationError):conciliacao.confirmar(op,self.superuser,dados)
        self.assertEqual(self.api.escritas,[])

    def test_duas_inclusoes_do_mesmo_nome_no_mesmo_grupo_sao_recusadas(self):
        self.nova_categoria()
        self.api.catalogos[self.matriz.pk].append(categoria('2.01.02','Energia elétrica',pai='2.01',codigo_dre='MATRIZ'))
        op=self.previa()
        with self.assertRaises(ValidationError):conciliacao.confirmar(op,self.superuser,decisoes_padrao(op))
        self.assertEqual(self.api.escritas,[])

    def test_texto_codificado_na_inativacao_preserva_nome_original(self):
        from html import escape
        self.api.catalogos[self.matriz.pk][-1]['descricao']='Serviços &amp; Materiais'
        antigo=self.api.catalogos[self.destino.pk][-1]
        antigo['descricao']='Compra &amp; Venda'
        antes=deepcopy(antigo)
        op=self.previa();dados=decisoes_padrao(op)
        self.escolher(op,dados,'2.08.07','inativar','destino')
        original=self.api.chamada
        def escrever(i,m,p):
            resposta=original(i,m,p)
            registro=next(c for c in self.api.catalogos[i.empresa_id] if c['codigo']==resposta['codigo'])
            registro['descricao']=escape(registro['descricao'],quote=False)
            return resposta
        with patch('apps.replicacao.omie.chamada',side_effect=escrever):op=self.enviar(op,dados)
        self.assertEqual(op.empresas.get().status,'sucesso',op.empresas.get().mensagem)
        self.assertEqual(antigo,{**antes,'conta_inativa':'S'})
