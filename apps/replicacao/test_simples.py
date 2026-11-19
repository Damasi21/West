from copy import deepcopy
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import json

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse

from apps.empresas.models import CategoriaOmie, AmbienteWhiteLabel
from apps.empresas.omie import _salvar_categorias
from . import central, simples, test_central as fixtures
from .forms import ReplicaSimplesForm
from .models import CadastroCategoria, DestinoReplicacao
from .tests import categoria


TIPOS = [{'cCodigo': 'FC', 'cDescricao': 'Serviço tomado', 'cTipo': 'P', 'cGrupo': 'Gastos'},
         {'cCodigo': 'RV', 'cDescricao': 'Venda', 'cTipo': 'R', 'cGrupo': 'Receitas'}]


class ReplicaSimplesTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)
        cache.clear()
        p = patch('apps.replicacao.omie.listar_tipos', return_value=TIPOS)
        self.ler_tipos = p.start(); self.addCleanup(p.stop)
        self.origem = CategoriaOmie.objects.get(empresa=self.matriz, codigo='2.01.01')

    def nova(self, descricao='Condomínio', destinos=None, tipo=''):
        return simples.solicitar(self.plano, self.superuser, 'nova', destinos or [self.destino.pk],
                                 grupo=self.pai, descricao=descricao, tipo_categoria=tipo)

    def executar(self, op):
        central.executar_cadastro(op.pk); op.refresh_from_db(); return op

    def fonte(self, codigo='2.01.09', descricao='Condomínio', **extra):
        registro = categoria(codigo, descricao, pai='2.01', codigo_dre='4.01', **extra)
        self.api.catalogos[self.matriz.pk].append(registro); _salvar_categorias(self.matriz, [registro])
        return CategoriaOmie.objects.get(empresa=self.matriz, codigo=codigo)

    def test_nova_apenas_nas_bases_marcadas_tipo_opcional(self):
        antes = deepcopy(self.api.catalogos[self.matriz.pk])
        op = self.executar(self.nova())
        self.assertEqual(op.empresas.get().status, 'sucesso', op.empresas.get().mensagem)
        self.assertEqual(self.api.catalogos[self.matriz.pk], antes)
        self.assertEqual([e for e, _, _ in self.api.escritas], [self.destino.pk])
        self.assertEqual(self.api.escritas[0][2]['tipo_categoria'], '')
        self.ler_tipos.assert_not_called()
        self.assertEqual(op.progresso_atual, op.progresso_total)
        self.executar(op); self.assertEqual(len(self.api.escritas), 1)

    def test_pai_so_recebe_quando_marcada_e_tipo_valido_preservado(self):
        op = self.executar(self.nova(destinos=[self.matriz.pk], tipo='FC'))
        self.assertEqual(op.empresas.get().status, 'sucesso', op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas[0][0], self.matriz.pk)
        self.assertEqual(self.api.escritas[0][2]['tipo_categoria'], 'FC')
        self.assertEqual(len(self.api.escritas), 1)

    def test_tipo_receita_em_despesa_nao_envia(self):
        op = self.executar(self.nova(tipo='RV'))
        self.assertEqual(op.empresas.get().status, 'erro')
        self.assertIn('não é compatível', op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_replica_uma_categoria_copia_tipo_e_dre(self):
        origem = self.fonte(tipo_categoria='FC')
        antes = deepcopy(self.api.catalogos[self.matriz.pk])
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'replicar', [self.destino.pk], categoria=origem))
        self.assertEqual(op.empresas.get().status, 'sucesso', op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas[0][2], {'descricao': 'Condomínio', 'categoria_superior': '2.08', 'tipo_categoria': 'FC', 'codigo_dre': '4.01'})
        self.assertEqual(self.api.catalogos[self.matriz.pk], antes)

    def test_ignora_exata_em_qualquer_grupo_e_inativa(self):
        origem = self.fonte()
        self.api.catalogos[self.destino.pk].append(categoria('2.99.01', origem.descricao, pai='2.99', conta_inativa='S'))
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'replicar', [self.destino.pk], categoria=origem))
        self.assertEqual(op.empresas.get().status, 'ignorada')
        self.assertIn('2.99.01', op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_diferenca_de_duas_letras_ignora_sem_revisao_ou_alteracao(self):
        origem = self.fonte(descricao='Aluguel')
        self.api.catalogos[self.destino.pk].append(categoria('2.08.09', 'Aluguéis', pai='2.08'))
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'replicar', [self.destino.pk], categoria=origem))
        self.assertEqual(op.status, 'concluido')
        self.assertEqual(op.empresas.get().status, 'ignorada')
        self.assertEqual(self.api.escritas, [])
        self.assertTrue(simples.parecido('Energia elétrica', 'Energia elétirca'))
        self.assertFalse(simples.parecido('Marketing', 'Honorários'))

    def test_grupo_ausente_nao_cria_automaticamente(self):
        self.api.catalogos[self.destino.pk] = []
        op = self.executar(self.nova())
        self.assertEqual(op.empresas.get().status, 'erro')
        self.assertIn('grupo superior', op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_inativar_pai_e_filho_preserva_historico_e_metadados(self):
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'inativar', [self.matriz.pk, self.destino.pk], categoria=self.origem))
        self.assertEqual(set(op.empresas.values_list('status', flat=True)), {'sucesso'})
        self.assertEqual(len(self.api.escritas), 2)
        for _, metodo, payload in self.api.escritas:
            self.assertEqual(metodo, 'AlterarCategoria')
            self.assertEqual(set(payload), {'codigo', 'descricao', 'conta_inativa'})
            self.assertEqual(payload['conta_inativa'], 'S')
        self.assertEqual(self.api.catalogos[self.destino.pk][-1]['codigo_dre'], 'LOCAL')

    def test_inativacao_nao_adivinha_nome_parecido(self):
        self.api.catalogos[self.destino.pk][-1]['descricao'] = 'Energia eletrica adicional'
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'inativar', [self.destino.pk], categoria=self.origem))
        self.assertEqual(op.empresas.get().status, 'ignorada')
        self.assertEqual(self.api.escritas, [])

    def test_inativacao_ambigua_bloqueia(self):
        self.api.catalogos[self.destino.pk].append(categoria('2.08.09', self.origem.descricao, pai='2.08'))
        op = self.executar(simples.solicitar(self.plano, self.superuser, 'inativar', [self.destino.pk], categoria=self.origem))
        self.assertEqual(op.empresas.get().status, 'erro')
        self.assertEqual(self.api.escritas, [])

    def test_incerteza_nao_repete_envio_e_verificacao_consulta_codigo(self):
        op = self.nova(); self.api.falha = 'apos_gravar'; self.executar(op)
        linha = op.empresas.get(); self.assertEqual(linha.status, 'incerto')
        with self.assertRaises(ValidationError): central.retomar(op, self.superuser)
        self.api.falha = None
        central.verificar_cadastro(linha.pk, self.superuser.pk, self.api.catalogos[self.destino.pk][-1]['codigo'])
        self.assertEqual(op.empresas.get().status, 'sucesso')
        self.executar(op); self.assertEqual(len(self.api.escritas), 1)

    def test_recusa_em_uma_base_nao_impede_outra(self):
        DestinoReplicacao.objects.create(plano=self.plano, empresa=self.fora)
        self.api.catalogos[self.fora.pk] = deepcopy(self.api.catalogos[self.destino.pk])
        def escrever(integracao, metodo, payload):
            if integracao.empresa_id == self.destino.pk:
                raise central.omie.OmieRecusada(codigo='102', detalhe='Cadastro bloqueado pelo aplicativo.')
            return self.api.chamada(integracao, metodo, payload)
        with patch('apps.replicacao.omie.chamada', side_effect=escrever):
            op = self.executar(self.nova(destinos=[self.destino.pk, self.fora.pk]))
        self.assertEqual(op.empresas.get(empresa=self.destino).status, 'erro')
        self.assertEqual(op.empresas.get(empresa=self.fora).status, 'sucesso')
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('replicacao:resultado_replica', args=[self.plano.pk, op.pk]))
        self.assertContains(response, 'Cadastro bloqueado pelo aplicativo.')
        self.assertContains(response, 'Código OMIE 102')

    def test_mudanca_na_fonte_impede_escritas(self):
        op = self.nova(); self.api.catalogos[self.matriz.pk][1]['descricao'] = 'Outro grupo'
        self.executar(op)
        self.assertEqual(op.status, 'erro')
        self.assertIn('mudou na base PAI', op.mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_falha_publicacao_nao_deixa_fila_infinita_nem_repete_entrega_incerta(self):
        op = self.nova()
        with patch('apps.replicacao.tasks.cadastrar_categoria.apply_async', side_effect=RuntimeError('broker indisponível')):
            central.publicar_cadastro(op)
        op.refresh_from_db(); self.assertEqual(op.status, 'erro')
        self.executar(op)  # A potentially queued delivery must not execute after the publish failed.
        self.assertEqual(self.api.escritas, [])
        self.executar(central.retomar(op, self.superuser))
        self.assertEqual(len(self.api.escritas), 1)

    def test_erro_publicacao_nao_sobrepoe_worker_que_ja_assumiu(self):
        op = self.nova()
        def publicar(*args, **kwargs):
            CadastroCategoria.objects.filter(pk=op.pk).update(status='consultando')
            raise RuntimeError('ack perdido')
        with patch('apps.replicacao.tasks.cadastrar_categoria.apply_async', side_effect=publicar):
            central.publicar_cadastro(op)
        op.refresh_from_db(); self.assertEqual(op.status, 'consultando')

    def test_permissoes_origens_e_destinos_forjados(self):
        for usuario in [self.viewer, self.lider]:
            with self.assertRaises(PermissionDenied): simples.solicitar(self.plano, usuario, 'nova', [self.destino.pk], grupo=self.pai, descricao='Nova')
        with self.assertRaises(PermissionDenied): self.nova(destinos=[self.fora.pk])
        with self.assertRaises(ValidationError): self.nova(destinos=[self.destino.pk, self.destino.pk])
        with self.assertRaises(ValidationError): simples.solicitar(self.plano, self.superuser, 'replicar', [self.destino.pk], categoria=self.pai)

    def test_formulario_so_uma_categoria_e_inativas_ocultas(self):
        inativa = self.fonte(conta_inativa='S')
        # QueryDict is required to represent duplicate fields in a real request.
        self.client.force_login(self.superuser)
        with patch('apps.replicacao.central.publicar_cadastro') as publicar:
            response = self.client.post(reverse('replicacao:replica', args=[self.plano.pk, 'replicar']), {'categoria': [self.origem.pk, self.origem.pk], 'destinos': [self.destino.pk]})
        publicar.assert_not_called(); self.assertContains(response, 'apenas uma categoria')
        response = self.client.get(reverse('replicacao:replica', args=[self.plano.pk, 'replicar']))
        self.assertNotContains(response, f'value="{inativa.pk}"')
        self.assertContains(response, 'type="radio"')
        self.assertContains(response, 'Executar a réplica')

    def test_post_csrf_e_somente_destino_marcado_sem_criar_pai(self):
        self.client.force_login(self.superuser)
        url = reverse('replicacao:replica', args=[self.plano.pk, 'nova'])
        dados = {'grupo': self.pai.pk, 'descricao': 'Condomínio', 'tipo_categoria': '', 'destinos': [self.destino.pk]}
        client = Client(enforce_csrf_checks=True); client.force_login(self.superuser)
        self.assertEqual(client.post(url, dados).status_code, 403)
        with patch('apps.replicacao.central.publicar_cadastro') as publicar, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, dados)
        publicar.assert_called_once()
        op = CadastroCategoria.objects.latest('pk')
        self.assertEqual(list(op.empresas.values_list('empresa_id', flat=True)), [self.destino.pk])
        self.assertRedirects(response, reverse('replicacao:resultado_replica', args=[self.plano.pk, op.pk]))

    def test_get_nao_cria_pedido_nem_envia_e_tipos_tem_cache(self):
        self.client.force_login(self.superuser)
        for acao in ['nova', 'replicar', 'inativar']:
            self.assertEqual(self.client.get(reverse('replicacao:replica', args=[self.plano.pk, acao])).status_code, 200)
        self.assertFalse(CadastroCategoria.objects.exists())
        self.assertEqual(self.api.escritas, [])
        url = reverse('replicacao:tipos_categoria', args=[self.plano.pk])
        self.assertEqual(self.client.get(url).json()['tipos'], TIPOS)
        self.client.get(url); self.ler_tipos.assert_called_once()

    def test_tipo_indisponivel_nao_expoe_credenciais(self):
        self.client.force_login(self.superuser)
        self.ler_tipos.side_effect = RuntimeError('segredo-teste app_secret')
        response = self.client.get(reverse('replicacao:tipos_categoria', args=[self.plano.pk]))
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'segredo-teste', status_code=503)

    def test_atualizar_pai_consulta_somente_a_fonte_e_retorna_ao_formulario(self):
        self.client.force_login(self.superuser)
        with patch('apps.replicacao.central.publicar_cadastro'), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('replicacao:atualizar_arvore', args=[self.plano.pk]), {'voltar_replica': 'nova'})
        op = CadastroCategoria.objects.latest('pk')
        self.assertEqual(list(op.empresas.values_list('empresa_id', flat=True)), [self.matriz.pk])
        with patch('apps.replicacao.omie.listar', side_effect=self.api.listar) as ler:
            self.executar(op)
        self.assertEqual({c.args[0].empresa_id for c in ler.call_args_list}, {self.matriz.pk})
        self.assertRedirects(response, reverse('replicacao:resultado_replica', args=[self.plano.pk, op.pk]))
        self.assertEqual(self.api.escritas, [])

    @override_settings(ALLOWED_HOSTS=['testserver', 'marca.example.com'])
    def test_isolamento_white_label(self):
        marca = AmbienteWhiteLabel.objects.create(nome='Marca', slug='marca', dominio='marca.example.com', dominio_ativo=True)
        marca.empresas.add(self.matriz, self.destino); self.plano.marca = marca; self.plano.save()
        self.client.force_login(self.superuser)
        url = reverse('replicacao:replica', args=[self.plano.pk, 'nova'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url, HTTP_HOST='marca.example.com').status_code, 200)


class TiposCategoriaContratoTests(SimpleTestCase):
    def resposta(self, lista, pagina, paginas, total):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'cCodStatus': '0', 'listaTipoCategoria': lista,
            'nPagina': pagina, 'nRegistros': len(lista), 'nTotPaginas': paginas, 'nTotRegistros': total}).encode()
        return response

    def test_endpoint_paginado_e_tipo_receita_despesa_preservado(self):
        integracao = SimpleNamespace(app_key='chave-teste', obter_app_secret=lambda: 'segredo-teste')
        with patch('apps.replicacao.omie._abrir_requisicao_omie', side_effect=[self.resposta(TIPOS[:1], 1, 2, 2), self.resposta(TIPOS[1:], 2, 2, 2)]) as abrir:
            self.assertEqual(central.omie.listar_tipos(integracao), TIPOS)
        self.assertEqual(abrir.call_count, 2)
        for i, chamada in enumerate(abrir.call_args_list, 1):
            request = chamada.args[0]
            self.assertEqual(request.full_url, 'https://app.omie.com.br/api/v1/geral/tipocategoria/')
            dados = json.loads(request.data)
            self.assertEqual(dados['call'], 'ListarTipoCategoria')
            self.assertEqual(dados['param'], [{'nPagina': i, 'nRegPorPagina': 500}])

    def test_lista_incompleta_nao_e_usada(self):
        integracao = SimpleNamespace(app_key='chave-teste', obter_app_secret=lambda: 'segredo-teste')
        with patch('apps.replicacao.omie._abrir_requisicao_omie', return_value=self.resposta(TIPOS[:1], 1, 1, 2)):
            with self.assertRaises(central.omie.ConsultaRecusada): central.omie.listar_tipos(integracao)

    def test_tipo_invalido_nao_e_usado(self):
        integracao = SimpleNamespace(app_key='chave-teste', obter_app_secret=lambda: 'segredo-teste')
        with patch('apps.replicacao.omie._abrir_requisicao_omie', return_value=self.resposta([{**TIPOS[0], 'cTipo': 'D'}], 1, 1, 1)):
            with self.assertRaises(central.omie.ConsultaRecusada): central.omie.listar_tipos(integracao)
