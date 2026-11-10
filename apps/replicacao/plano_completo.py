"""Chave temporária do fluxo de conciliação do plano completo."""
from django.conf import settings
from django.core.exceptions import ValidationError


def ativo():
    return getattr(settings, "REPLICACAO_PLANO_COMPLETO_ATIVO", False)


def conferir():
    if not ativo():
        raise ValidationError("O plano completo está temporariamente inativo. Utilize o cadastro avulso de categorias ou grupos. O histórico e a verificação de envios anteriores permanecem disponíveis.")
