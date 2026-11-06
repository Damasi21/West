from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.empresas.models import Empresa, EmpresaUsuario, AmbienteWhiteLabel
from apps.empresas.white_label_domains import _marca_host
from . import central, test_central as fixtures
from .forms import PlanoForm, PadronizacaoForm
from .models import PlanoReplicacao


class SelecaoLivreTests(TestCase):
    def setUp(self):
        fixtures.CadastroCentralTests.setUp(self)
        self.plano.ativo = False
        self.plano.save()
        Empresa.objects.filter(pk=self.matriz.pk).update(grupo="")
        Empresa.objects.filter(pk=self.destino.pk).update(grupo="Outro grupo")

    def formulario(self, usuario=None, destinos=None):
        return PlanoForm({"nome": "Bases escolhidas", "matriz": self.matriz.pk,
                          "destinos": [self.destino.pk] if destinos is None else destinos},
                         usuario=usuario or self.gestor)

    def criar(self):
        form = self.formulario()
        self.assertTrue(form.is_valid(), form.errors)
        return form.salvar()

    def test_cria_com_grupos_diferentes_sem_campo_grupo_e_somente_destino_marcado(self):
        plano = self.criar()
        self.assertTrue(plano.selecao_livre)
        self.assertTrue(plano.cadastro_central)
        self.assertEqual(plano.grupo, "")
        self.assertEqual(list(plano.destinos.values_list("empresa_id", flat=True)), [self.destino.pk])
        self.assertNotIn("grupo", self.formulario().fields)
        self.assertEqual(set(PadronizacaoForm(plano=plano).fields["destinos"].queryset.values_list("pk", flat=True)), {self.destino.pk})
        self.assertEqual(self.api.escritas, [])
        self.client.force_login(self.gestor)
        response = self.client.get(reverse("replicacao:detalhe", args=[plano.pk]))
        self.assertContains(response, "Preparar prévia do plano")
        self.assertContains(response, "Categorias da conta principal")

    def test_worker_usa_participantes_configurados_e_ignora_mudancas_de_grupo(self):
        plano = self.criar()
        op = central.solicitar(plano, self.gestor, catalogo=True)
        Empresa.objects.filter(pk=self.destino.pk).update(grupo="")
        Empresa.objects.filter(pk=self.fora.pk).update(grupo="Outro grupo")
        with patch("apps.replicacao.omie.listar", side_effect=self.api.listar) as consultar:
            central.executar_cadastro(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "concluido", op.mensagem)
        self.assertEqual({c.args[0].empresa_id for c in consultar.call_args_list}, {self.matriz.pk, self.destino.pk})
        self.assertEqual(self.api.escritas, [])

    def test_destinos_obrigatorios_e_pai_nao_pode_ser_filho(self):
        self.assertFalse(self.formulario(destinos=[]).is_valid())
        self.assertFalse(self.formulario(destinos=[self.matriz.pk]).is_valid())

    def test_vinculo_como_usuario_simples_nao_libera_administracao_da_base(self):
        EmpresaUsuario.objects.create(usuario=self.gestor, empresa=self.fora, papel="viewer")
        form = self.formulario(destinos=[self.fora.pk])
        self.assertFalse(form.is_valid())
        self.assertNotIn(self.fora.pk, form.fields["destinos"].queryset.values_list("pk", flat=True))
        for usuario in [self.lider, self.viewer]:
            self.assertFalse(self.formulario(usuario=usuario).is_valid())

    def test_revogacao_entre_validacao_e_salvamento_nao_cria_configuracao(self):
        form = self.formulario()
        self.assertTrue(form.is_valid(), form.errors)
        EmpresaUsuario.objects.filter(usuario=self.gestor, empresa=self.destino).delete()
        antes = PlanoReplicacao.objects.count()
        with self.assertRaises(ValidationError):
            form.salvar()
        self.assertEqual(PlanoReplicacao.objects.count(), antes)

    def test_revogacao_antes_do_worker_interrompe_sem_consulta_omie(self):
        plano = self.criar()
        op = central.solicitar(plano, self.gestor, catalogo=True)
        EmpresaUsuario.objects.filter(usuario=self.gestor, empresa=self.destino).delete()
        with patch("apps.replicacao.omie.listar") as consultar:
            central.executar_cadastro(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "erro")
        consultar.assert_not_called()

    def test_white_label_so_lista_bases_da_marca_inclusive_para_superuser(self):
        marca = AmbienteWhiteLabel.objects.create(nome="Marca escolhida", slug="marca-escolhida")
        marca.empresas.add(self.matriz, self.destino)
        marca.administradores.add(self.gestor)
        token = _marca_host.set(marca)
        try:
            for usuario in [self.gestor, self.superuser]:
                self.assertFalse(self.formulario(usuario=usuario, destinos=[self.fora.pk]).is_valid())
            plano = self.criar()
            self.assertEqual(plano.marca_id, marca.pk)
            self.assertEqual({e.pk for e in central.conferir_empresas(plano, self.gestor)}, {self.matriz.pk, self.destino.pk})
        finally:
            _marca_host.reset(token)
