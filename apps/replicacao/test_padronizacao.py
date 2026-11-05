from copy import deepcopy
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from apps.empresas.models import CategoriaOmie, Empresa, AmbienteWhiteLabel
from apps.empresas.white_label_domains import _marca_host
from . import central, padronizacao, test_central as fixtures
from .tests import categoria
from .models import DestinoReplicacao, VinculoCategoria


class PadronizacaoTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)

    def executar(self, op):
        central.executar_cadastro(op.pk)
        op.refresh_from_db()
        return op

    def previa(self):
        return self.executar(padronizacao.solicitar(self.plano, self.superuser, [self.destino.pk]))

    def confirmar(self, op):
        linha = op.empresas.get(empresa=self.destino)
        return padronizacao.confirmar(op, self.superuser, {"confirmar": "sim", f"aplicar_{linha.pk}": "sim"})

    def dois_grupos(self):
        self.api.catalogos[self.matriz.pk] = [self.raiz,
            categoria("2.01", "Grupo PAI A", grupo=True, pai="2"),
            *[categoria(f"2.01.{i:02d}", f"PAI A{i}", pai="2.01") for i in range(1,6)],
            categoria("2.02", "Grupo PAI B", grupo=True, pai="2"),
            *[categoria(f"2.02.{i:02d}", f"PAI B{i}", pai="2.02") for i in range(1,4)]]
        self.api.catalogos[self.destino.pk] = [self.raiz,
            categoria("2.08", "Nome diferente", grupo=True, pai="2"),
            *[categoria(f"2.08.{i:02d}", f"FILHO A{i}", pai="2.08") for i in range(1,9)],
            categoria("2.09", "Outro grupo", grupo=True, pai="2"),
            *[categoria(f"2.09.{i:02d}", f"FILHO B{i}", pai="2.09") for i in range(1,3)]]

    def test_exemplo_5_de_8_e_3_de_2_sem_escrita_na_previa(self):
        self.dois_grupos()
        op = self.previa()
        self.assertEqual(op.status, "revisao", op.mensagem)
        self.assertEqual(self.api.escritas, [])
        self.assertEqual(list(op.empresas.values_list("empresa_id", flat=True)), [self.destino.pk])
        passos = op.empresas.get().passos
        self.assertEqual(len([p for p in passos if p["acao"] == "inativar"]), 3)
        self.assertEqual(len([p for p in passos if p["acao"] == "criar"]), 1)
        self.executar(self.confirmar(op))
        op.refresh_from_db()
        linha = op.empresas.get()
        self.assertEqual(linha.status, "sucesso", linha.mensagem)
        alvo = {c["codigo"]:c for c in self.api.catalogos[self.destino.pk]}
        self.assertEqual(alvo["2.08"]["descricao"], "Grupo PAI A")
        for i in range(1,6):
            self.assertEqual(alvo[f"2.08.{i:02d}"]["descricao"], f"PAI A{i}")
        for i in range(6,9):
            self.assertEqual(alvo[f"2.08.{i:02d}"]["conta_inativa"], "S")
        self.assertEqual(alvo["2.09.01"]["descricao"], "PAI B1")
        self.assertEqual(alvo["2.09.02"]["descricao"], "PAI B2")
        nova = next(c for c in alvo.values() if c["descricao"] == "PAI B3")
        self.assertEqual(nova["categoria_superior"], "2.09")
        self.assertTrue(all(pk == self.destino.pk for pk, _, _ in self.api.escritas))
        self.assertEqual(op.progresso_atual, op.progresso_total)
        quantidade = len(self.api.escritas)
        self.executar(op)
        self.assertEqual(len(self.api.escritas), quantidade)

    def test_ordem_e_numerica_nao_nome_ou_lista_recebida(self):
        self.dois_grupos()
        self.api.catalogos[self.destino.pk].reverse()
        op = self.previa()
        passo = op.empresas.get().passos[1]
        self.assertEqual(passo["alvo"]["codigo"], "2.08.01")
        self.assertEqual(passo["origem"]["codigo"], "2.01.01")

    def test_nao_confunde_receita_com_despesa(self):
        receita = lambda cod, nome, **kw: categoria(cod,nome,conta_receita="S",conta_despesa="N",**kw)
        self.api.catalogos[self.matriz.pk] += [receita("1.01","Receita PAI",grupo=True,pai="1"),receita("1.01.01","Venda PAI",pai="1.01")]
        self.api.catalogos[self.destino.pk] += [receita("1.09","Receita FILHO",grupo=True,pai="1"),receita("1.09.01","Venda FILHO",pai="1.09")]
        op = self.previa()
        passos = op.empresas.get().passos
        self.assertEqual(passos[0]["alvo"]["codigo"], "1.09")
        self.executar(self.confirmar(op))
        linha = op.empresas.get()
        self.assertEqual(linha.status, "sucesso", linha.mensagem)
        self.assertEqual(next(c for c in self.api.catalogos[self.destino.pk] if c["codigo"] == "1.09.01")["descricao"], "Venda PAI")

    def test_grupo_faltante_e_criado_antes_dos_filhos(self):
        self.api.catalogos[self.destino.pk] = [self.raiz]
        op = self.previa()
        self.executar(self.confirmar(op))
        linha = op.empresas.get()
        self.assertEqual(linha.status, "sucesso", linha.mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas], ["IncluirGrupoCategoria","IncluirCategoria"])
        self.assertEqual(self.api.escritas[1][2]["categoria_superior"], linha.passos[0]["codigo"])

    def test_copia_codigo_dre_e_reativa_filha_conforme_matriz(self):
        self.api.catalogos[self.destino.pk][-1]["conta_inativa"] = "S"
        op = self.previa()
        self.executar(self.confirmar(op))
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)
        alvo = self.api.catalogos[self.destino.pk][-1]
        self.assertEqual(alvo["codigo_dre"], "MATRIZ")
        self.assertEqual(alvo["conta_inativa"], "N")

    def test_inclusao_inativa_e_separada_e_confirmada(self):
        self.api.catalogos[self.matriz.pk][-1]["conta_inativa"] = "S"
        self.api.catalogos[self.destino.pk] = [self.raiz,self.grupo_destino]
        op = self.previa()
        self.executar(self.confirmar(op))
        linha = op.empresas.get()
        self.assertEqual(linha.status, "sucesso", linha.mensagem)
        self.assertEqual([m for _,m,_ in self.api.escritas], ["IncluirCategoria","AlterarCategoria"])
        self.assertEqual(self.api.catalogos[self.destino.pk][-1]["conta_inativa"], "S")

    def test_grupo_excedente_ou_situacao_incompativel_bloqueia_sem_gravar(self):
        self.api.catalogos[self.destino.pk].append(categoria("2.09","Excedente",grupo=True,pai="2"))
        op = self.previa()
        self.assertEqual(op.empresas.get().status, "bloqueada")
        with self.assertRaises(ValidationError): self.confirmar(op)
        self.assertEqual(self.api.escritas, [])

    def test_grupo_pai_inativo_nao_e_reativado_por_metodo_indevido(self):
        self.api.catalogos[self.destino.pk][1]["conta_inativa"] = "S"
        op = self.previa()
        self.assertEqual(op.empresas.get().status, "bloqueada")
        self.assertEqual(self.api.escritas, [])

    def test_mudanca_destino_depois_previa_interrompe_sem_escrita(self):
        op = self.previa()
        self.confirmar(op)
        self.api.catalogos[self.destino.pk][-1]["descricao"] = "Alteração externa"
        self.executar(op)
        self.assertEqual(op.empresas.get().status, "erro")
        self.assertEqual(self.api.escritas, [])

    def test_mudanca_matriz_depois_previa_interrompe_sem_escrita(self):
        op = self.previa()
        self.confirmar(op)
        self.api.catalogos[self.matriz.pk][-1]["descricao"] = "Alteração externa"
        self.executar(op)
        self.assertEqual(op.status, "erro")
        self.assertEqual(self.api.escritas, [])

    def test_timeout_apos_gravar_e_reconciliado_sem_reenviar(self):
        self.api.catalogos[self.destino.pk][1]["descricao"] = "Outro grupo"
        op = self.previa()
        self.confirmar(op)
        self.api.falha = "apos_gravar"
        self.executar(op)
        linha = op.empresas.get()
        self.assertEqual(linha.status, "incerto", linha.mensagem)
        self.assertEqual(len(self.api.escritas), 1)
        with self.assertRaises(ValidationError): central.retomar(op, self.superuser)
        central.verificar_cadastro(linha.pk, self.superuser.pk)
        linha.refresh_from_db()
        self.assertEqual(linha.status, "erro", linha.mensagem)
        self.api.falha = None
        self.executar(central.retomar(op, self.superuser))
        linha.refresh_from_db()
        self.assertEqual(linha.status, "sucesso", linha.mensagem)
        self.assertEqual(len([m for _,m,_ in self.api.escritas if m == "AlterarGrupoCategoria"]), 1)

    def test_recusa_explicita_pode_retomar_sem_repetir_confirmados(self):
        op = self.previa()
        self.confirmar(op)
        self.api.falha = "recusada"
        self.executar(op)
        self.assertEqual(op.empresas.get().status, "erro")
        self.api.falha = None
        self.executar(central.retomar(op, self.superuser))
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)

    def test_cancelar_previa_nao_grava(self):
        op = self.previa()
        op = padronizacao.confirmar(op,self.superuser,{"cancelar":"sim"})
        self.executar(op)
        self.assertEqual(op.empresas.get().status, "ignorada")
        self.assertEqual(self.api.escritas, [])

    def test_confirmacao_exigida_e_matriz_nao_pode_ser_destino(self):
        with self.assertRaises(PermissionDenied): padronizacao.solicitar(self.plano,self.superuser,[self.matriz.pk])
        with self.assertRaises(PermissionDenied): padronizacao.solicitar(self.plano,self.superuser,[self.fora.pk])
        op = self.previa()
        with self.assertRaises(ValidationError): padronizacao.confirmar(op,self.superuser,{})
        self.assertEqual(self.api.escritas, [])

    def test_sem_acesso_nao_pode_solicitar_ou_confirmar(self):
        with self.assertRaises(PermissionDenied): padronizacao.solicitar(self.plano,self.viewer,[self.destino.pk])
        op = self.previa()
        with self.assertRaises(PermissionDenied): padronizacao.confirmar(op,self.lider,{"confirmar":"sim"})
        self.plano.ativo = False
        self.plano.save()
        self.executar(self.confirmar_sem_worker(op))
        op.refresh_from_db()
        self.assertEqual(op.status, "erro")
        self.assertEqual(self.api.escritas, [])

    def confirmar_sem_worker(self, op):
        # Access revocation is independently rechecked by the worker.
        op.status = "fila"
        op.save()
        return op

    def test_tela_previa_mostra_antes_depois_e_aviso_historico(self):
        op = self.previa()
        self.client.force_login(self.superuser)
        resposta = self.client.get(reverse("replicacao:detalhe",args=[self.plano.pk]),{"cadastro":op.pk})
        self.assertContains(resposta,"Prévia do plano por sequência")
        self.assertContains(resposta,"Destino atual")
        self.assertContains(resposta,"lançamentos antigos")
        self.assertContains(resposta,"grupo não será criado automaticamente")
        cliente_csrf = Client(enforce_csrf_checks=True)
        cliente_csrf.force_login(self.superuser)
        self.assertEqual(cliente_csrf.post(reverse("replicacao:confirmar_padronizacao",args=[self.plano.pk,op.pk])).status_code,403)

    def test_white_label_nao_acessa_plano_de_outra_marca(self):
        marca = AmbienteWhiteLabel.objects.create(nome="Marca teste espelho",slug="marca-espelho")
        token = _marca_host.set(marca)
        try:
            with self.assertRaises(PermissionDenied): padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk])
        finally:
            _marca_host.reset(token)

    def test_avulso_bloqueia_pai_ausente_sem_cria_lo_e_demais_seguem(self):
        self.api.catalogos[self.destino.pk] = [self.raiz]
        op = central.solicitar(self.plano,self.superuser,"Aluguel",self.pai,destinos_ids=[self.destino.pk],estrito=True)
        self.executar(op)
        self.assertEqual(op.empresas.get(empresa=self.destino).status,"bloqueada")
        self.assertEqual(op.empresas.get(empresa=self.matriz).status,"sucesso")
        self.assertTrue(all(pk == self.matriz.pk for pk,_,_ in self.api.escritas))
        self.api.catalogos[self.destino.pk].append(self.grupo_destino)
        self.executar(central.retomar(op,self.superuser))
        self.assertEqual(op.empresas.get(empresa=self.destino).status,"sucesso")
        self.assertEqual(len([pk for pk,_,_ in self.api.escritas if pk == self.matriz.pk]),1)

    def test_avulso_pai_parecido_nao_pode_ser_sobrescrito(self):
        self.api.catalogos[self.destino.pk][1]["descricao"] = "Operacional"
        op = central.solicitar(self.plano,self.superuser,"Aluguel",self.pai,destinos_ids=[self.destino.pk],estrito=True)
        self.executar(op)
        self.assertEqual(op.empresas.get(empresa=self.destino).status,"bloqueada")
        self.assertFalse(any(pk == self.destino.pk for pk,_,_ in self.api.escritas))

    def test_avulso_novo_grupo_pode_ser_criado_sem_grupo_previo(self):
        raiz = CategoriaOmie.objects.get(empresa=self.matriz,codigo="2")
        op = central.solicitar(self.plano,self.superuser,"Novo grupo",raiz,destinos_ids=[self.destino.pk],estrito=True)
        self.executar(op)
        self.assertEqual(set(op.empresas.values_list("status",flat=True)),{"sucesso"})
        self.assertEqual([m for _,m,_ in self.api.escritas],["IncluirGrupoCategoria","IncluirGrupoCategoria"])

    def test_inclusao_sem_resposta_exige_codigo_e_nunca_reenvia(self):
        self.api.catalogos[self.destino.pk] = [self.raiz,self.grupo_destino]
        op = self.previa()
        self.confirmar(op)
        self.api.falha = "apos_gravar"
        self.executar(op)
        linha = op.empresas.get()
        self.assertEqual(linha.status, "incerto")
        self.assertEqual(len(self.api.escritas), 1)
        central.verificar_cadastro(linha.pk, self.superuser.pk)
        linha.refresh_from_db()
        self.assertEqual(linha.status,"incerto")
        codigo = self.api.catalogos[self.destino.pk][-1]["codigo"]
        central.verificar_cadastro(linha.pk, self.superuser.pk, codigo)
        linha.refresh_from_db()
        self.assertEqual(linha.status,"erro",linha.mensagem)
        self.api.falha = None
        self.executar(central.retomar(op,self.superuser))
        linha.refresh_from_db()
        self.assertEqual(linha.status,"sucesso",linha.mensagem)
        self.assertEqual(len(self.api.escritas), 1)

    def test_falha_de_um_destino_nao_interrompe_outro_e_pai_nunca_escrito(self):
        Empresa.objects.filter(pk=self.fora.pk).update(grupo=self.plano.grupo)
        DestinoReplicacao.objects.create(plano=self.plano,empresa=self.fora)
        self.api.catalogos[self.fora.pk] = [deepcopy(self.raiz),deepcopy(self.grupo_destino),deepcopy(self.filha_destino)]
        op = self.executar(padronizacao.solicitar(self.plano,self.superuser,[self.destino.pk,self.fora.pk]))
        escolhas = {"confirmar":"sim", **{f"aplicar_{l.pk}":"sim" for l in op.empresas.all()}}
        padronizacao.confirmar(op,self.superuser,escolhas)
        original = self.api.chamada
        def escrita(integracao, metodo, payload):
            if integracao.empresa_id == self.destino.pk:
                raise central.omie.OmieRecusada()
            return original(integracao,metodo,payload)
        with patch('apps.replicacao.omie.chamada',side_effect=escrita): self.executar(op)
        self.assertEqual(op.empresas.get(empresa=self.destino).status,"erro")
        self.assertEqual(op.empresas.get(empresa=self.fora).status,"sucesso")
        self.assertTrue(all(pk==self.fora.pk for pk,_,_ in self.api.escritas))

    def test_empresa_desmarcada_nao_e_consultada_nem_recebe_linha(self):
        Empresa.objects.filter(pk=self.fora.pk).update(grupo=self.plano.grupo)
        DestinoReplicacao.objects.create(plano=self.plano,empresa=self.fora)
        with patch('apps.replicacao.omie.listar',side_effect=self.api.listar) as consulta:
            op = self.previa()
            self.executar(self.confirmar(op))
        self.assertNotIn(self.fora.pk,[c.args[0].empresa_id for c in consulta.call_args_list])
        self.assertEqual(list(op.empresas.values_list("empresa_id",flat=True)),[self.destino.pk])

    def test_vinculos_antigos_substituidos_pela_posicao_confirmada(self):
        from apps.empresas.omie import _salvar_categorias
        self.api.catalogos[self.destino.pk].append(categoria("2.08.08","Outra",pai="2.08"))
        _salvar_categorias(self.destino,self.api.catalogos[self.destino.pk])
        origem = CategoriaOmie.objects.get(empresa=self.matriz,codigo="2.01.01")
        errado = CategoriaOmie.objects.get(empresa=self.destino,codigo="2.08.08")
        VinculoCategoria.objects.create(destino=self.alvo,origem=origem,categoria=errado,confirmado_por=self.superuser)
        op = self.previa()
        self.executar(self.confirmar(op))
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        self.assertEqual(VinculoCategoria.objects.get(destino=self.alvo,origem=origem).categoria.codigo,"2.08.07")

    def test_grupo_novo_de_receita_usa_tipo_r_e_preserva_separacao(self):
        receita = lambda cod, nome, **kw: categoria(cod,nome,conta_receita="S",conta_despesa="N",**kw)
        self.api.catalogos[self.matriz.pk] += [receita("1.01","Receitas novas",grupo=True,pai="1"),receita("1.01.01","Venda nova",pai="1.01")]
        op = self.previa()
        self.executar(self.confirmar(op))
        self.assertEqual(op.empresas.get().status,"sucesso",op.empresas.get().mensagem)
        grupo = next(p for _,m,p in self.api.escritas if m=="IncluirGrupoCategoria")
        self.assertEqual(grupo["tipo_grupo"],"R")

    def test_previa_grupo_com_pai_invalido_nao_autoriza_escritas(self):
        self.api.catalogos[self.destino.pk][1]["categoria_superior"] = "1"
        op = self.previa()
        self.assertEqual(op.empresas.get().status,"bloqueada")
        self.assertEqual(self.api.escritas,[])

    def test_limite_identifica_empresa_categoria_campo_e_quantidade_sem_cortar(self):
        descricao = "Á" * 51
        self.api.catalogos[self.matriz.pk][-1]["descricao"] = descricao
        self.api.catalogos[self.matriz.pk][-1]["natureza"] = "N" * 54
        op = self.previa()
        self.assertEqual(op.status, "erro")
        for trecho in ("Base PAI — Matriz", "2.01.01", descricao, "Campo Descrição: 51", "excede em 1", "retome a consulta"):
            self.assertIn(trecho, op.mensagem)
        self.assertEqual(self.api.catalogos[self.matriz.pk][-1]["descricao"], descricao)
        self.assertEqual(self.api.escritas, [])

    def test_limite_na_filha_identifica_base_e_todos_os_cadastros(self):
        self.api.catalogos[self.destino.pk][1]["descricao"] = "G" * 52
        self.api.catalogos[self.destino.pk][-1]["descricao"] = "D" * 55
        op = self.previa()
        linha = op.empresas.get()
        self.assertEqual(linha.status, "bloqueada")
        for trecho in ("Base FILHO — Destino B", "Grupo 2.08", "Campo Descrição: 52", "Categoria 2.08.07", "Campo Descrição: 55"):
            self.assertIn(trecho, linha.mensagem)
        self.assertIn("\n", linha.mensagem)
        self.assertEqual(self.api.escritas, [])

    def test_cinquenta_caracteres_permitidos_e_mensagem_escapada_na_tela(self):
        self.api.catalogos[self.matriz.pk][-1]["descricao"] = "D" * 50
        self.api.catalogos[self.matriz.pk][-1]["natureza"] = "N" * 50
        op = self.previa()
        self.assertEqual(op.status, "revisao", op.mensagem)
        padronizacao.confirmar(op, self.superuser, {"cancelar": "sim"})
        self.api.catalogos[self.matriz.pk][-1]["descricao"] = "<script>alert(1)</script>" * 3
        erro = self.previa()
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("replicacao:detalhe",args=[self.plano.pk]), {"cadastro": erro.pk})
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(self.api.escritas, [])

    def test_observacoes_longas_diferentes_nao_bloqueiam_nem_geram_alteracao(self):
        for c in self.api.catalogos[self.matriz.pk]:
            c["natureza"] = "Observação da matriz " * 30
        for c in self.api.catalogos[self.destino.pk]:
            c["natureza"] = "Observação local " * 40
        self.api.catalogos[self.destino.pk][-1]["codigo_dre"] = "MATRIZ"
        op = self.previa()
        self.assertEqual(op.status, "revisao", op.mensagem)
        self.assertTrue(all(p["acao"] == "manter" for p in op.empresas.get().passos))
        self.executar(self.confirmar(op))
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)
        self.assertEqual(self.api.escritas, [])
        self.assertEqual(self.api.catalogos[self.destino.pk][-1]["natureza"], "Observação local " * 40)

    def test_renomear_e_inativar_preservam_observacoes_locais_sem_enviar_campo(self):
        self.dois_grupos()
        self.api.catalogos[self.matriz.pk] = deepcopy(self.api.catalogos[self.matriz.pk])
        self.api.catalogos[self.destino.pk] = deepcopy(self.api.catalogos[self.destino.pk])
        antes = {c["codigo"]:c["codigo"]+" nota local "*30 for c in self.api.catalogos[self.destino.pk]}
        for c in self.api.catalogos[self.destino.pk]: c["natureza"] = antes[c["codigo"]]
        for c in self.api.catalogos[self.matriz.pk]: c["natureza"] = "Nota matriz "*60
        op = self.previa()
        self.executar(self.confirmar(op))
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)
        self.assertTrue(self.api.escritas)
        self.assertTrue(all("natureza" not in payload for _,_,payload in self.api.escritas))
        for c in self.api.catalogos[self.destino.pk]:
            self.assertEqual(c["natureza"], antes.get(c["codigo"], ""))

    def test_novo_grupo_e_filha_nao_copiam_observacao_e_aceitam_padrao_da_omie(self):
        self.api.catalogos[self.destino.pk] = [self.raiz]
        for c in self.api.catalogos[self.matriz.pk]: c["natureza"] = "Notas da matriz "*50
        op = self.previa()
        self.confirmar(op)
        chamada = self.api.chamada
        def incluir(integracao, metodo, payload):
            resultado = chamada(integracao, metodo, payload)
            if metodo.startswith("Incluir"):
                self.api.catalogos[integracao.empresa_id][-1]["natureza"] = "Padrão da OMIE "*50
            return resultado
        with patch('apps.replicacao.omie.chamada', side_effect=incluir): self.executar(op)
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)
        self.assertTrue(all("natureza" not in payload for _,_,payload in self.api.escritas))

    def test_mudanca_apenas_em_observacoes_apos_previa_nao_interrompe_envio(self):
        op = self.previa()
        self.confirmar(op)
        self.api.catalogos[self.matriz.pk][1]["natureza"] = "Mudou a nota PAI "*50
        self.api.catalogos[self.destino.pk][-1]["natureza"] = "Mudou a nota FILHO "*50
        self.executar(op)
        self.assertEqual(op.empresas.get().status, "sucesso", op.empresas.get().mensagem)
        self.assertEqual(self.api.catalogos[self.destino.pk][-1]["natureza"], "Mudou a nota FILHO "*50)

    def test_avulso_grupo_com_observacao_longa_nao_bloqueia_e_nao_envia_observacoes(self):
        self.pai.natureza = "Observação local PAI "*50
        self.pai.save()
        self.api.catalogos[self.matriz.pk][1]["natureza"] = self.pai.natureza
        self.api.catalogos[self.destino.pk][1]["natureza"] = "Observação local FILHO "*50
        op = central.solicitar(self.plano,self.superuser,"Aluguel",self.pai,destinos_ids=[self.destino.pk])
        self.executar(op)
        self.assertEqual(set(op.empresas.values_list("status",flat=True)), {"sucesso"})
        self.assertTrue(all("natureza" not in payload for _,_,payload in self.api.escritas))
