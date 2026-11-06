import uuid

from django.conf import settings
from django.db import models


class PlanoReplicacao(models.Model):
    nome = models.CharField(max_length=120)
    grupo = models.CharField(max_length=120, blank=True, default="", db_default="")
    selecao_livre = models.BooleanField(default=False)
    matriz = models.ForeignKey("empresas.Empresa", on_delete=models.PROTECT, related_name="planos_matriz")
    marca = models.ForeignKey("empresas.AmbienteWhiteLabel", null=True, blank=True, on_delete=models.PROTECT)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome

    @property
    def cadastro_central(self):
        return self.selecao_livre or bool(self.grupo)


class DestinoReplicacao(models.Model):
    plano = models.ForeignKey(PlanoReplicacao, on_delete=models.CASCADE, related_name="destinos")
    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plano", "empresa"], name="rep_destino_plano_empresa")]
        ordering = ["empresa__nome_fantasia", "pk"]


class VinculoCategoria(models.Model):
    destino = models.ForeignKey(DestinoReplicacao, on_delete=models.PROTECT, related_name="vinculos")
    origem = models.ForeignKey("empresas.CategoriaOmie", on_delete=models.PROTECT, related_name="vinculos_replicados_origem")
    categoria = models.ForeignKey("empresas.CategoriaOmie", on_delete=models.PROTECT, related_name="vinculos_replicados_destino")
    confirmado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["destino", "origem"], name="rep_vinculo_origem"),
            models.UniqueConstraint(fields=["destino", "categoria"], name="rep_vinculo_categoria"),
        ]


class ComparacaoReplicacao(models.Model):
    class Status(models.TextChoices):
        FILA = "fila", "Aguardando comparação"
        COMPARANDO = "comparando", "Consultando OMIE"
        PRONTA = "pronta", "Pronta para revisão"
        ENVIANDO = "enviando", "Replicando selecionados"
        CONCLUIDA = "concluida", "Processamento finalizado"
        ERRO = "erro", "Comparação não concluída"

    plano = models.ForeignKey(PlanoReplicacao, on_delete=models.PROTECT, related_name="comparacoes")
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.FILA)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mensagem = models.TextField(blank=True)
    aplicativos = models.JSONField(default=dict)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)
    iniciada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pk"]


class ItemReplicacao(models.Model):
    class Situacao(models.TextChoices):
        CRIAR = "criar", "Não existe"
        ALTERAR = "alterar", "Dados diferentes"
        IGUAL = "igual", "Já corresponde"
        AMBIGUO = "ambiguo", "Correspondência ambígua"
        BLOQUEADO = "bloqueado", "Revisão necessária"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Aguardando seleção"
        FILA = "fila", "Selecionado para envio"
        EXECUTANDO = "executando", "Em processamento"
        SUCESSO = "sucesso", "Confirmado na OMIE"
        ERRO = "erro", "Não enviado"
        INCERTO = "incerto", "Aguardando confirmação"

    comparacao = models.ForeignKey(ComparacaoReplicacao, on_delete=models.CASCADE, related_name="itens")
    destino = models.ForeignKey(DestinoReplicacao, on_delete=models.PROTECT)
    origem = models.ForeignKey("empresas.CategoriaOmie", on_delete=models.PROTECT, related_name="itens_replicacao_origem")
    categoria = models.ForeignKey("empresas.CategoriaOmie", null=True, blank=True, on_delete=models.PROTECT, related_name="itens_replicacao_destino")
    situacao = models.CharField(max_length=15, choices=Situacao.choices)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDENTE)
    caminho = models.CharField(max_length=500)
    matriz_dados = models.JSONField(default=dict)
    destino_dados = models.JSONField(default=dict)
    candidatos = models.JSONField(default=list)
    revisao_inclusao = models.JSONField(default=dict, db_default={})
    mensagem = models.TextField(blank=True)
    metodo = models.CharField(max_length=30, blank=True)
    parametros = models.JSONField(default=dict)
    codigo_confirmado = models.CharField(max_length=80, blank=True)
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    aprovado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["destino_id", "origem__codigo", "pk"]
        constraints = [models.UniqueConstraint(fields=["comparacao", "destino", "origem"], name="rep_item_comparacao_origem")]


class CadastroCategoria(models.Model):
    """One explicit request, including the matrix; workers never replay writes."""
    plano = models.ForeignKey(PlanoReplicacao, on_delete=models.PROTECT, related_name="cadastros")
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    modo = models.CharField(max_length=12, default="cadastro")
    pedido = models.JSONField(default=dict)
    aplicativos = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="fila", choices=[("fila", "Na fila"), ("consultando", "Verificando OMIEs"), ("revisao", "Aguardando sua decisão"), ("enviando", "Cadastrando no grupo"), ("concluido", "Processamento concluído"), ("erro", "Consulta não concluída"), ("cancelada", "Requisição cancelada")])
    mensagem = models.TextField(blank=True)
    progresso_atual = models.PositiveIntegerField(default=0)
    progresso_total = models.PositiveIntegerField(default=0)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)
    iniciada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pk"]

    def get_status_display(self):
        if self.status == "concluido" and self.empresas.filter(status__in=["erro", "incerto", "bloqueada", "pendente", "pronta", "executando"]).exists():
            return "Processamento interrompido: há pendências"
        return dict(self._meta.get_field("status").choices).get(self.status, self.status)


class CadastroCategoriaEmpresa(models.Model):
    cadastro = models.ForeignKey(CadastroCategoria, on_delete=models.CASCADE, related_name="empresas")
    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="pendente", choices=[("pendente", "Aguardando consulta"), ("pronta", "Verificada"), ("revisao", "Revisar semelhanças"), ("executando", "Cadastrando"), ("sucesso", "Confirmado"), ("ignorada", "Ignorada"), ("bloqueada", "Bloqueada"), ("erro", "Pendente de conclusão"), ("incerto", "Verificar resultado")])
    mensagem = models.TextField(blank=True)
    passos = models.JSONField(default=list)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["cadastro", "empresa"], name="rep_cadastro_empresa_unico")]
