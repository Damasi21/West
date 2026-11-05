from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from apps.empresas.models import CategoriaOmie, EmpresaUsuario
from . import test_central as fixtures
from .tests import categoria
from . import central, estado
from .models import CadastroCategoria, VinculoCategoria


class SituacaoCategoriaTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)
        self.origem = CategoriaOmie.objects.get(empresa=self.matriz, codigo="2.01.01")

    def preparar(self, modo="inativar", empresas=None):
        op = estado.solicitar(self.plano, self.superuser, self.origem, modo,
            empresas if empresas is not None else [self.matriz.pk, self.destino.pk])
        central.executar_cadastro(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "revisao", op.mensagem)
        return op

    def confirmar(self, op, ignorar=()):
        post = {"confirmar":"sim"}
        for linha in op.empresas.exclude(status__in=["sucesso", "ignorada"]):
            alvo = linha.passos[0]["alvo"]
            if linha.empresa_id not in ignorar and alvo:
                post[f"aplicar_{linha.pk}"] = "sim"
                post[f"categoria_{linha.pk}"] = alvo["codigo"]
        op = estado.confirmar(op, self.superuser, post)
        central.executar_cadastro(op.pk)
        op.refresh_from_db()
        return op

    def test_previa_sem_escritas_confirmacao_inativa_e_reativa_preservando_dados(self):
        antes = deepcopy(self.api.catalogos)
        op = self.preparar()
        self.assertEqual(self.api.escritas, [])
        self.assertEqual(central.situacao(op)["percentual"], 50)
        op = self.confirmar(op)
        self.assertEqual(op.status, "concluido", op.mensagem)
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"sucesso"})
        self.assertEqual(central.situacao(op)["percentual"], 100)
        self.assertEqual(len(self.api.escritas), 2)
        self.assertEqual([w[1] for w in self.api.escritas], ["AlterarCategoria"]*2)
        self.assertEqual([w[2]["codigo"] for w in self.api.escritas], ["2.01.01", "2.08.07"])
        self.assertTrue(all(w[2]["conta_inativa"] == "S" for w in self.api.escritas))
        for empresa, registros in antes.items():
            for registro in registros:
                atual = next(c for c in self.api.catalogos[empresa] if c["codigo"]==registro["codigo"])
                self.assertEqual({k:v for k,v in atual.items() if k!="conta_inativa"}, {k:v for k,v in registro.items() if k!="conta_inativa"})
        central.executar_cadastro(op.pk)
        self.assertEqual(len(self.api.escritas), 2)
        self.origem.refresh_from_db()
        self.assertTrue(self.origem.conta_inativa)
        op = self.confirmar(self.preparar("reativar"))
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"sucesso"})
        self.assertTrue(all(w[2]["conta_inativa"] == "N" for w in self.api.escritas[2:]))
        self.origem.refresh_from_db()
        self.assertFalse(self.origem.conta_inativa)

    def test_selecao_restrita_e_ignorar_empresa(self):
        op = self.preparar(empresas=[self.destino.pk])
        self.assertEqual(op.empresas.count(), 1)
        self.confirmar(op)
        self.assertEqual([w[0] for w in self.api.escritas], [self.destino.pk])
        self.origem.refresh_from_db()
        self.assertFalse(self.origem.conta_inativa)

    def test_estado_ja_desejado_e_reexecucao_nao_escrevem(self):
        for e in (self.matriz, self.destino): self.api.catalogos[e.pk][-1]["conta_inativa"]="S"
        op = self.confirmar(self.preparar())
        self.assertEqual(op.status,"concluido")
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"sucesso"})
        self.assertEqual(self.api.escritas, [])

    def test_categoria_ausente_nao_e_criada_e_pode_ser_ignorada(self):
        self.api.catalogos[self.destino.pk].pop()
        op = self.preparar()
        linha = op.empresas.get(empresa=self.destino)
        self.assertEqual(linha.passos[0]["candidatos"], [])
        op = self.confirmar(op)
        self.assertEqual(op.empresas.get(empresa=self.destino).status,"ignorada")
        self.assertEqual([w[0] for w in self.api.escritas], [self.matriz.pk])

    def test_semelhanca_ou_duplicidade_exige_escolha_explicita(self):
        self.api.catalogos[self.destino.pk][-1]["descricao"]="Energia eletrica geral"
        op = self.preparar(empresas=[self.destino.pk])
        linha = op.empresas.get()
        self.assertIsNone(linha.passos[0]["alvo"])
        with self.assertRaises(ValidationError):
            estado.confirmar(op,self.superuser,{"confirmar":"sim",f"aplicar_{linha.pk}":"sim",f"categoria_{linha.pk}":"2.01.01"})
        self.assertEqual(self.api.escritas, [])
        op=estado.confirmar(op,self.superuser,{"confirmar":"sim",f"aplicar_{linha.pk}":"sim",f"categoria_{linha.pk}":"2.08.07"})
        central.executar_cadastro(op.pk)
        self.assertEqual(self.api.escritas[0][2]["descricao"],"Energia eletrica geral")

    def test_codigo_igual_em_outra_hierarquia_nao_e_correspondencia(self):
        self.api.catalogos[self.destino.pk][-1]["codigo"]="2.01.01"
        self.api.catalogos[self.destino.pk][-1]["categoria_superior"]="2.99"
        op = self.preparar(empresas=[self.destino.pk])
        self.assertEqual(op.empresas.get().passos[0]["candidatos"], [])
        self.assertEqual(self.api.escritas, [])

    def test_reativacao_com_pai_inativo_nao_envia(self):
        self.api.catalogos[self.destino.pk][1]["conta_inativa"]="S"
        op=self.preparar("reativar", empresas=[self.destino.pk])
        self.assertEqual(op.empresas.get().passos[0]["candidatos"], [])
        self.assertEqual(self.api.escritas, [])

    def test_mudanca_apos_confirmacao_exige_nova_previa(self):
        op=self.preparar(empresas=[self.destino.pk])
        linha=op.empresas.get()
        op=estado.confirmar(op,self.superuser,{"confirmar":"sim",f"aplicar_{linha.pk}":"sim",f"categoria_{linha.pk}":"2.08.07"})
        self.api.catalogos[self.destino.pk][-1]["natureza"]="Nova natureza"
        central.executar_cadastro(op.pk);op.refresh_from_db()
        self.assertEqual(op.status,"revisao")
        self.assertEqual(self.api.escritas, [])
        op=self.confirmar(op)
        self.assertEqual(op.empresas.get().status,"sucesso")
        self.assertEqual(self.api.escritas[0][2]["natureza"],"Nova natureza")

    def test_resposta_perdida_so_verifica_e_nao_repete_escrita(self):
        op=self.preparar()
        self.api.falha="apos_gravar"
        op=self.confirmar(op)
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"incerto"})
        n=len(self.api.escritas)
        with self.assertRaises(ValidationError):central.retomar(op,self.superuser)
        self.api.falha=None
        for linha in op.empresas.all():
            central.verificar_cadastro(linha.pk,self.superuser.pk,"9.99.99")
            linha.refresh_from_db()
            self.assertEqual(linha.status,"incerto")
            central.verificar_cadastro(linha.pk,self.superuser.pk)
            linha.refresh_from_db()
            self.assertEqual(linha.status,"sucesso",linha.mensagem)
        self.assertEqual(len(self.api.escritas),n)

    def test_confirmacao_obrigatoria_e_encerramento_sem_envio(self):
        op=self.preparar()
        with self.assertRaises(ValidationError):estado.confirmar(op,self.superuser,{})
        with self.assertRaises(ValidationError):central.resolver_cadastro(op,self.superuser,{})
        op=estado.confirmar(op,self.superuser,{"cancelar":"sim"})
        self.assertEqual(op.status,"concluido")
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"ignorada"})
        self.assertEqual(self.api.escritas,[])

    def test_worker_revalida_vinculos_do_white_label(self):
        from apps.empresas.models import AmbienteWhiteLabel
        from apps.empresas.white_label_domains import _marca_host
        marca=AmbienteWhiteLabel.objects.create(nome="Marca situação",slug="marca-situacao")
        marca.empresas.add(self.matriz,self.destino)
        self.plano.marca=marca;self.plano.save()
        token=_marca_host.set(marca)
        try:
            op=estado.solicitar(self.plano,self.superuser,self.origem,"inativar",[self.destino.pk])
        finally:_marca_host.reset(token)
        marca.empresas.remove(self.destino)
        central.executar_cadastro(op.pk);op.refresh_from_db()
        self.assertEqual(op.status,"erro")
        self.assertEqual(self.api.escritas,[])

    def test_rejeita_grupos_transferencias_empresas_externas_e_usuarios_sem_papel(self):
        for cat in (self.pai,):
            with self.assertRaises(ValidationError):estado.solicitar(self.plano,self.superuser,cat,"inativar",[self.destino.pk])
        with self.assertRaises(PermissionDenied):estado.solicitar(self.plano,self.superuser,self.origem,"inativar",[self.fora.pk])
        for usuario in [self.viewer,self.lider]:
            with self.assertRaises(PermissionDenied):estado.solicitar(self.plano,usuario,self.origem,"inativar",[self.destino.pk])
        with self.assertRaises(ValidationError):estado.solicitar(self.plano,self.superuser,self.origem,"excluir",[self.destino.pk])
        self.assertEqual(self.api.escritas,[])

    def test_telas_acoes_previa_confirmacao_e_csrf(self):
        self.client.force_login(self.superuser)
        url=reverse("replicacao:situacao_categoria",args=[self.plano.pk,self.origem.pk])
        self.assertContains(self.client.get(reverse("replicacao:detalhe",args=[self.plano.pk])),url)
        response=self.client.get(url)
        self.assertContains(response,"Consultar categorias e preparar prévia")
        op=self.preparar()
        response=self.client.get(reverse("replicacao:detalhe",args=[self.plano.pk]))
        self.assertContains(response,"Conferir categorias para inativar")
        self.assertContains(response,"2.08.07")
        self.assertNotContains(response,"Sobrescrever a descrição do cadastro escolhido abaixo")
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.superuser)
        self.assertEqual(csrf.post(url,{"modo":"inativar","empresas":[self.destino.pk]}).status_code,403)
        confirmar=reverse("replicacao:confirmar_situacao",args=[self.plano.pk,op.pk])
        self.assertEqual(self.client.get(confirmar).status_code,405)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code,403)
