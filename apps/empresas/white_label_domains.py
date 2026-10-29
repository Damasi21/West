"""Escopo por host limitado ao request; workers independem de marca."""
import re
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError


_marca_host = ContextVar("white_label_marca_host", default=None)


def marca_host_atual():
    return _marca_host.get()


def limitar_empresas(queryset, prefixo=""):
    marca = marca_host_atual()
    if marca is not None:
        queryset = queryset.filter(**{f"{prefixo}ambientes_white_label__pk": marca.pk})
    return queryset


def convites_do_host(queryset):
    return limitar_empresas(queryset, "empresa__")


def usuario_no_host(usuario):
    if usuario is None or marca_host_atual() is None:
        return usuario
    from .services import empresas_permitidas
    return usuario if usuario.is_superuser or empresas_permitidas(usuario).exists() else None


def email_autorizado_no_host(email):
    if marca_host_atual() is None:
        return True
    from django.contrib.auth import get_user_model
    from .models import PreCadastroUsuario
    if convites_do_host(PreCadastroUsuario.objects.filter(
        email__iexact=email, ativo=True, utilizado_em__isnull=True, empresa__ativa=True
    )).exists():
        return True
    return any(usuario_no_host(usuario) for usuario in get_user_model().objects.filter(email__iexact=email, is_active=True))


def normalizar_dominio(valor):
    valor = (valor or "").strip().lower().rstrip(".")
    if not valor:
        return None
    try:
        valor = valor.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValidationError("Informe um domínio válido, sem https://, porta ou caminho.")
    labels = valor.split(".")
    if len(valor) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ) or labels[-1].isdigit():
        raise ValidationError("Informe somente o domínio completo. Ex.: app.revee.elevdata.com.br")
    if valor in settings.WHITE_LABEL_PRIMARY_HOSTS:
        raise ValidationError("Este endereço é reservado para o acesso principal da plataforma.")
    return valor
