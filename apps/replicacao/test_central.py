from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa, CategoriaOmie, EmpresaUsuario
from apps.empresas.omie import _salvar_categorias
from . import tests as fixtures
from .tests import categoria
from . import central
from .forms import PlanoForm
from .models import CadastroCategoria, CadastroCategoriaEmpresa, DestinoReplicacao


class CadastroCentralTests(TestCase):
    def setUp(self):
        fixtures.ReplicacaoTests.setUp(self)
        Empresa.objects.filter(pk__in=[self.matriz.pk, self.destino.pk]).update(grupo="Grupo teste")
        self.matriz.refresh_from_db()
        self.destino.refresh_from_db()
        self.plano.grupo = "Grupo teste"
        self.plano.save()
        _salvar_categorias(self.matriz, self.api.catalogos[self.matriz.pk])
        self.pai = CategoriaOmie.objects.get(empresa=self.matriz, codigo="2.01")

    def solicitar(self, descricao="Aluguel", pai=None):
        return central.solicitar(self.plano, self.superuser, descricao, pai or self.pai)

    def executar(self, op):
        central.executar_cadastro(op.pk)
        op.refresh_from_db()
        return op

    def test_cria_em_todos_os_omies_incluindo_pai_e_progresso_real(self):
        op = self.solicitar()
        self.assertEqual(self.api.escritas, [])
        self.executar(op)
        self.assertEqual(op.status, "concluido", op.mensagem)
        self.assertEqual(set(op.empresas.values_list("status", flat=True)), {"sucesso"})
        self.assertEqual(op.progresso_atual, op.progresso_total)
        self.assertEqual(op.progresso_total, 4)
        self.assertEqual({e[0] for e in self.api.escritas}, {self.matriz.pk, self.destino.pk})
        self.assertEqual(len(self.api.escritas), 2)
        codigos = {e: p["categoria_superior"] for e, _, p in self.api.escritas}
        self.assertEqual(codigos, {self.matriz.pk:"2.01", self.destino.pk:"2.08"})
        self.executar(op)
        self.assertEqual(len(self.api.escritas), 2)

    def test_semelhanca_interrompe_toda_varredura_antes_de_gravar(self):
        self.api.catalogos[self.destino.pk].append(categoria("2.08.09", "Aluguéis", pai="2.08"))
        op = self.executar(self.solicitar())
        self.assertEqual(op.status, "revisao", op.mensagem)
        self.assertEqual(self.api.escritas, [])
        self.assertEqual(op.progresso_atual, 2)
        linha = op.empresas.get(empresa=self.destino)
        self.assertEqual(linha.passos[1]["acao"], "conflito")
        op = central.resolver_cadastro(op, self.superuser, {f"empresa_{linha.pk}": "sobrescrever", f"passo_{linha.pk}_1": "2.08.09"})
        self.executar(op)
        self.assertEqual(op.status, "concluido", op.mensagem)
        escritas = [w for w in self.api.escritas if w[0] == self.destino.pk]
        self.assertEqual(escritas[0][1], "AlterarCategoria")
        self.assertEqual(escritas[0][2]["codigo"], "2.08.09")
        self.assertEqual(escritas[0][2]["descricao"], "Aluguel")
        self.assertEqual(len(self.api.catalogos[self.destino.pk]), 4)

    def test_ignorar_destino_nao_impede_demais_empresas(self):
        self.api.catalogos[self.destino.pk].append(categoria("2.08.09", "Aluguéis", pai="2.08"))
        op = self.executar(self.solicitar())
        linha = op.empresas.get(empresa=self.destino)
        op = central.resolver_cadastro(op, self.superuser, {f"empresa_{linha.pk}": "ignorar"})
        self.executar(op)
        self.assertEqual(op.status, "concluido")
        self.assertEqual([e for e, _, _ in self.api.escritas], [self.matriz.pk])
        self.assertEqual(op.empresas.get(empresa=self.destino).status, "ignorada")

    def test_detecta_semelhanca_na_propria_matriz(self):
        self.api.catalogos[self.matriz.pk].append(categoria("2.01.09", "Aluguéis", pai="2.01"))
        op = self.executar(self.solicitar())
        self.assertEqual(op.empresas.get(empresa=self.matriz).status, "revisao")
        self.assertEqual(self.api.escritas, [])

    def test_existente_exato_aproveitado_sem_escrita(self):
        op = self.executar(self.solicitar("Energia elétrica"))
        self.assertEqual(op.status, "concluido", op.mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_sobrescrever_preserva_natureza_tipo_e_dre(self):
        registro = categoria("2.08.09", "Aluguéis", pai="2.08", natureza="LOCAL", tipo_categoria="LOC", codigo_dre="DRE-LOCAL")
        self.api.catalogos[self.destino.pk].append(registro)
        op = self.executar(self.solicitar())
        linha = op.empresas.get(empresa=self.destino)
        op = central.resolver_cadastro(op, self.superuser, {f"passo_{linha.pk}_1": "2.08.09"})
        self.executar(op)
        final = next(c for c in self.api.catalogos[self.destino.pk] if c["codigo"] == "2.08.09")
        self.assertEqual((final["natureza"], final["tipo_categoria"], final["codigo_dre"]), ("LOCAL", "LOC", "DRE-LOCAL"))

    def test_outro_grupo_mesmo_nome_notifica_sem_permitir_sobrescrever(self):
        self.api.catalogos[self.destino.pk].append(categoria("2.99.01", "Aluguel", pai="2.99"))
        op = self.executar(self.solicitar())
        linha = op.empresas.get(empresa=self.destino)
        self.assertEqual(linha.status, "revisao")
        self.assertFalse(linha.passos[1]["candidatos"][0]["compativel"])
        with self.assertRaises(ValidationError):
            central.resolver_cadastro(op, self.superuser, {f"passo_{linha.pk}_1":"2.99.01"})
        self.assertEqual(self.api.escritas, [])

    def test_candidato_mudou_apos_decisao_exige_nova_revisao(self):
        self.api.catalogos[self.destino.pk].append(categoria("2.08.09", "Aluguéis", pai="2.08"))
        op = self.executar(self.solicitar())
        linha = op.empresas.get(empresa=self.destino)
        op = central.resolver_cadastro(op, self.superuser, {f"passo_{linha.pk}_1":"2.08.09"})
        self.api.catalogos[self.destino.pk][-1]["natureza"] = "ALTERADA"
        self.executar(op)
        self.assertEqual(op.status, "revisao")
        self.assertEqual(self.api.escritas, [])

    def test_grupo_ausente_mudou_ou_sem_permissao_nao_envia(self):
        self.plano.grupo = ""
        self.plano.save()
        with self.assertRaises(ValidationError): self.solicitar()
        self.plano.grupo = "Grupo teste"
        self.plano.save()
        Empresa.objects.filter(pk=self.destino.pk).update(grupo="Outro")
        with self.assertRaises(ValidationError): self.solicitar()
        Empresa.objects.filter(pk=self.destino.pk).update(grupo="Grupo teste")
        EmpresaUsuario.objects.filter(empresa=self.destino, usuario=self.gestor).delete()
        with self.assertRaises(PermissionDenied): central.solicitar(self.plano, self.gestor, "Aluguel", self.pai)
        self.assertEqual(self.api.escritas, [])

    def test_formulario_grupo_inclui_todos_destinos_e_rejeita_pai_externo(self):
        form = PlanoForm({"nome":"Grupo", "grupo":"Grupo teste", "matriz":self.matriz.pk}, usuario=self.superuser)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual([e.pk for e in form.cleaned_data["destinos"]], [self.destino.pk])
        form = PlanoForm({"nome":"Grupo", "grupo":"Grupo teste", "matriz":self.fora.pk}, usuario=self.superuser)
        self.assertFalse(form.is_valid())

    def test_somente_consulta_atualiza_arvore_sem_escritas(self):
        op = central.solicitar(self.plano, self.superuser, catalogo=True)
        self.executar(op)
        self.assertEqual(op.status, "concluido")
        self.assertEqual(op.progresso_total, 2)
        self.assertEqual(self.api.escritas, [])

    def test_cria_grupo_e_pai_ausente_antes_da_filha(self):
        self.api.catalogos[self.destino.pk] = [self.raiz]
        op = self.executar(self.solicitar())
        self.assertEqual(op.status, "concluido", op.mensagem)
        alvo = op.empresas.get(empresa=self.destino)
        self.assertEqual(alvo.status, "sucesso", alvo.mensagem)
        escritas = [w for w in self.api.escritas if w[0] == self.destino.pk]
        self.assertEqual([w[1] for w in escritas], ["IncluirGrupoCategoria", "IncluirCategoria"])
        self.assertEqual(escritas[1][2]["categoria_superior"], alvo.passos[0]["codigo"])

    def test_resposta_perdida_nao_reenvia_e_verificacao_apenas_leitura(self):
        op = self.solicitar()
        self.api.falha = "apos_gravar"
        self.executar(op)
        self.assertEqual(set(op.empresas.values_list("status", flat=True)), {"incerto"})
        n = len(self.api.escritas)
        with self.assertRaises(ValidationError): central.retomar(op, self.superuser)
        self.api.falha = None
        for linha in op.empresas.all():
            codigo = next(c["codigo"] for c in self.api.catalogos[linha.empresa_id] if c["descricao"] == "Aluguel")
            central.verificar_cadastro(linha.pk, self.superuser.pk, codigo)
            linha.refresh_from_db()
            self.assertEqual(linha.status, "sucesso", linha.mensagem)
        self.assertEqual(len(self.api.escritas), n)

    def test_recusa_confirmada_permite_retomar_so_pendencias(self):
        original = self.api.chamada
        def falha(integracao, metodo, payload):
            if integracao.empresa_id == self.destino.pk:
                raise central.omie.OmieRecusada()
            return original(integracao, metodo, payload)
        with patch("apps.replicacao.omie.chamada", side_effect=falha):
            op = self.executar(self.solicitar())
        self.assertEqual(op.empresas.get(empresa=self.matriz).status, "sucesso")
        self.assertEqual(op.empresas.get(empresa=self.destino).status, "erro")
        central.retomar(op, self.superuser)
        self.executar(op)
        self.assertEqual([e for e,_,_ in self.api.escritas].count(self.matriz.pk), 1)

    def test_tela_arvore_modal_progresso_e_acessos(self):
        self.client.force_login(self.superuser)
        op = self.solicitar()
        url = reverse("replicacao:detalhe", args=[self.plano.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        for texto in ["Categorias da base PAI", "Nova categoria", "data-rep-progress", "Operacionais", "Energia elétrica"]:
            self.assertContains(response, texto)
        endpoint = reverse("replicacao:progresso_cadastro", args=[self.plano.pk, op.pk])
        data = self.client.get(endpoint).json()
        self.assertEqual(data["percentual"], 0)
        self.assertTrue(data["ativo"])
        self.assertIn("no-store", self.client.get(endpoint)["Cache-Control"])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(endpoint).status_code, 403)

    def test_csrf_obrigatorio_e_get_nao_cadastra(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("replicacao:cadastrar",args=[self.plano.pk])).status_code, 405)
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post(reverse("replicacao:cadastrar",args=[self.plano.pk]), {}).status_code, 403)
        self.assertFalse(CadastroCategoria.objects.exists())

    def test_grupo_ambiguo_resolvido_antes_de_apresentar_filhos(self):
        self.api.catalogos[self.destino.pk][1]["descricao"] = "Operacional"
        self.api.catalogos[self.destino.pk].append(categoria("2.08.09", "Aluguéis", pai="2.08"))
        op = self.executar(self.solicitar())
        linha = op.empresas.get(empresa=self.destino)
        self.assertEqual(linha.passos[0]["acao"], "conflito")
        op = central.resolver_cadastro(op, self.superuser, {f"passo_{linha.pk}_0":"2.08"})
        self.executar(op)
        self.assertEqual(op.status, "revisao", op.mensagem)
        self.assertEqual(self.api.escritas, [])
        linha.refresh_from_db()
        self.assertTrue(linha.passos[1]["candidatos"][0]["compativel"])
        op = central.resolver_cadastro(op, self.superuser, {f"passo_{linha.pk}_1":"2.08.09"})
        self.executar(op)
        self.assertEqual(op.status, "concluido", op.mensagem)
        self.assertEqual(op.empresas.get(empresa=self.destino).status, "sucesso")

    def test_worker_perdido_mantem_intencao_incerta_apos_retornar_erro(self):
        op = self.solicitar()
        linha = op.empresas.get(empresa=self.destino)
        linha.status = "executando"
        linha.passos = [{"status":"executando"}]
        linha.save()
        CadastroCategoria.objects.filter(pk=op.pk).update(status="enviando", atualizada_em=timezone.now()-timedelta(minutes=40))
        with self.assertRaises(ValidationError): central.retomar(op, self.superuser)
        linha.refresh_from_db()
        op.refresh_from_db()
        self.assertEqual(linha.status, "incerto")
        self.assertEqual(op.status, "erro")
        self.assertEqual(self.api.escritas, [])

    def test_lider_viewer_nao_criam_e_grupo_com_membro_invisivel_e_recusado(self):
        for usuario in [self.lider, self.viewer]:
            with self.assertRaises(PermissionDenied): central.solicitar(self.plano, usuario, "Aluguel", self.pai)
        Empresa.objects.filter(pk=self.fora.pk).update(grupo="Grupo teste")
        with self.assertRaises(PermissionDenied): central.empresas_grupo(self.gestor, "Grupo teste")
        self.assertEqual(self.api.escritas, [])

    def test_semelhanca_surgida_imediatamente_antes_da_escrita_volta_para_revisao(self):
        listar = self.api.listar
        consultas_destino = 0
        def consultar(integracao, descricao=""):
            nonlocal consultas_destino
            if integracao.empresa_id == self.destino.pk:
                consultas_destino += 1
                if consultas_destino == 4:
                    self.api.catalogos[self.destino.pk].append(categoria("2.08.09", "Aluguéis", pai="2.08"))
            return listar(integracao, descricao)
        with patch("apps.replicacao.omie.listar", side_effect=consultar):
            op = self.executar(self.solicitar())
        self.assertEqual(op.status, "revisao", op.mensagem)
        self.assertEqual(op.empresas.get(empresa=self.destino).status, "revisao")
        self.assertFalse(any(e == self.destino.pk for e, _, _ in self.api.escritas))
        self.assertEqual(op.empresas.get(empresa=self.matriz).status, "sucesso")

    def test_lock_de_worker_vivo_impede_retomada_mesmo_com_heartbeat_antigo(self):
        from django.db import connection
        op = self.solicitar()
        CadastroCategoria.objects.filter(pk=op.pk).update(status="enviando", atualizada_em=timezone.now()-timedelta(minutes=40))
        outro = connection.copy(alias="rep-lock-test")
        chave = f"west-cadastro-categoria:{op.pk}"
        try:
            with outro.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
            with self.assertRaises(ValidationError): central.retomar(op, self.superuser)
            op.refresh_from_db()
            self.assertEqual(op.status, "enviando")
        finally:
            with outro.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
            outro.close()
