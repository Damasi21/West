from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class ConfirmacaoCadastro(models.Model):
    email = models.EmailField(unique=True, max_length=254)
    nome = models.CharField(max_length=150)
    codigo_hash = models.CharField(max_length=128, blank=True)
    enviada_em = models.DateTimeField(null=True)
    expira_em = models.DateTimeField(null=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    consumida_em = models.DateTimeField(null=True)
    janela_envios = models.DateTimeField(null=True)
    quantidade_envios = models.PositiveSmallIntegerField(default=0)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    email_verificado_em = models.DateTimeField(null=True)


class PasswordResetCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_codes",
    )
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def is_valid(self):
        return (
            self.used_at is None
            and self.created_at >= timezone.now() - timedelta(minutes=15)
        )
