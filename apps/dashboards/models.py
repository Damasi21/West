from django.db import models
from django.conf import settings


class Dashboard(models.Model):
    class Area(models.TextChoices):
        COMERCIAL = "comercial", "Comercial"
        FINANCEIRO = "financeiro", "Financeiro"
        COMPRAS = "compras", "Compras"
        ESTOQUE = "estoque", "Estoque"
        CRM = "crm", "CRM"

    area = models.CharField(max_length=20, choices=Area.choices, unique=True)
    titulo = models.CharField(max_length=100)
    descricao = models.CharField(max_length=240, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["area"]

    def __str__(self):
        return self.titulo


class AprovacaoPagamento(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADO = "aprovado", "Aprovado"
        REAGENDADO = "reagendado", "Reagendado"
        ERRO_OMIE = "erro_omie", "Erro OMIE"

    conta_pagar = models.OneToOneField(
        "empresas.ContaPagarOmie",
        on_delete=models.CASCADE,
        related_name="aprovacao_pagamento",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    data_previsao_original = models.DateField(null=True, blank=True)
    data_previsao_aprovada = models.DateField(null=True, blank=True)
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="aprovacoes_pagamentos",
        null=True,
        blank=True,
    )
    resposta_omie = models.JSONField(default=dict, blank=True)
    erro_omie = models.TextField(blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-atualizado_em"]
        indexes = [
            models.Index(fields=["status"], name="aprov_pag_status_idx"),
            models.Index(fields=["data_previsao_aprovada"], name="aprov_pag_prev_idx"),
        ]
        verbose_name = "aprovacao de pagamento"
        verbose_name_plural = "aprovacoes de pagamentos"

    def __str__(self):
        return f"{self.conta_pagar_id} - {self.get_status_display()}"
