from django.db import models


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
