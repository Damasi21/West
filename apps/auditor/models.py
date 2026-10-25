from django.conf import settings
from django.db import models
from django.db.models import Q


class ExecucaoAuditoria(models.Model):
    class Status(models.TextChoices):
        FILA = "fila", "Na fila"
        EXECUTANDO = "executando", "Em analise"
        CONCLUIDA = "concluida", "Concluida"
        ERRO = "erro", "Erro"

    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    solicitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.FILA)
    criada_em = models.DateTimeField(auto_now_add=True)
    iniciada_em = models.DateTimeField(null=True)
    finalizada_em = models.DateTimeField(null=True)
    fontes = models.JSONField(default=list)
    politicas = models.JSONField(default=list)
    resumo = models.JSONField(default=dict)
    erro = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-pk"]
        constraints = [models.UniqueConstraint(
            fields=["empresa"], condition=Q(status__in=["fila", "executando"]),
            name="auditor_execucao_ativa_empresa",
        )]


class PoliticaAuditoria(models.Model):
    class Severidade(models.TextChoices):
        ATENCAO = "atencao", "Atencao"
        ALTO = "alto", "Alto"
        CRITICO = "critico", "Critico"

    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    codigo = models.CharField(max_length=40)
    ativa = models.BooleanField(default=True)
    severidade = models.CharField(max_length=12, choices=Severidade.choices, default=Severidade.ATENCAO)
    parametros = models.JSONField(default=dict)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["empresa", "codigo"], name="auditor_politica_empresa_codigo")]


class CasoAuditoria(models.Model):
    class Status(models.TextChoices):
        NOVO = "novo", "Novo"
        ANALISE = "analise", "Em analise"
        JUSTIFICADO = "justificado", "Justificado"
        CONFIRMADO = "confirmado", "Divergencia confirmada"
        RESOLVIDO = "resolvido", "Resolvido"

    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    identidade = models.CharField(max_length=64)
    regra = models.CharField(max_length=40)
    titulo = models.CharField(max_length=200)
    severidade = models.CharField(max_length=12, choices=PoliticaAuditoria.Severidade.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOVO)
    recomendacao = models.TextField()
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criada_em = models.DateTimeField(auto_now_add=True)
    ultima_deteccao = models.DateTimeField()
    ultima_execucao = models.ForeignKey(ExecucaoAuditoria, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-ultima_deteccao", "-pk"]
        constraints = [models.UniqueConstraint(fields=["empresa", "identidade"], name="auditor_caso_empresa_identidade")]
        indexes = [models.Index(fields=["empresa", "status"], name="auditor_caso_empresa_status")]


class EvidenciaAuditoria(models.Model):
    caso = models.ForeignKey(CasoAuditoria, on_delete=models.CASCADE, related_name="evidencias")
    execucao = models.ForeignKey(ExecucaoAuditoria, on_delete=models.PROTECT)
    criada_em = models.DateTimeField(auto_now_add=True)
    dados = models.JSONField(default=dict)

    class Meta:
        ordering = ["-pk"]
        constraints = [models.UniqueConstraint(fields=["caso", "execucao"], name="auditor_evidencia_caso_execucao")]


class EventoAuditoria(models.Model):
    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    caso = models.ForeignKey(CasoAuditoria, null=True, on_delete=models.CASCADE, related_name="eventos")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    criada_em = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=100)
    descricao = models.TextField()

    class Meta:
        ordering = ["-pk"]


class VersaoRegistroAuditoria(models.Model):
    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    execucao = models.ForeignKey(ExecucaoAuditoria, on_delete=models.PROTECT)
    entidade = models.CharField(max_length=24)
    codigo = models.BigIntegerField()
    versao = models.PositiveIntegerField()
    assinatura = models.CharField(max_length=64)
    dados = models.JSONField(default=dict)
    observada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pk"]
        constraints = [models.UniqueConstraint(
            fields=["empresa", "entidade", "codigo", "versao"], name="auditor_versao_registro_unica",
        )]
