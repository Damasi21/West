from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


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
