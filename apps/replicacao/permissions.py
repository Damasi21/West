from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.empresas.models import Empresa, IntegracaoOmie, AmbienteWhiteLabel
from apps.empresas.services import empresas_permitidas, PERFIS_MASTER
from apps.empresas.white_label_domains import marca_host_atual, _marca_host
from .models import PlanoReplicacao, DestinoReplicacao


def empresas_gerenciaveis(usuario):
    empresas = empresas_permitidas(usuario)
    if not usuario.is_authenticated or not usuario.is_active:
        return empresas.none()
    if usuario.is_superuser:
        return empresas
    administracao = Q(ambientes_white_label__ativa=True, ambientes_white_label__administradores=usuario)
    marca = marca_host_atual()
    if marca is not None:
        administracao &= Q(ambientes_white_label__pk=marca.pk)
    return empresas.filter(Q(vinculos__usuario=usuario, vinculos__ativo=True, vinculos__papel__in=PERFIS_MASTER) | administracao).distinct()


def planos_permitidos(usuario):
    ids = empresas_gerenciaveis(usuario).values("pk")
    planos = PlanoReplicacao.objects.filter(matriz_id__in=ids).exclude(
        pk__in=DestinoReplicacao.objects.exclude(empresa_id__in=ids).values("plano_id")
    )
    marca = marca_host_atual()
    if marca is not None:
        planos = planos.filter(marca=marca)
    else:
        # Branded plans are managed in their own environment, never through an
        # administrator assignment from a different brand sharing the same CNPJ.
        planos = planos.filter(marca__isnull=True)
    return planos


def conferir_acesso(plano, usuario):
    if usuario is None:
        raise PermissionDenied("O solicitante não está disponível.")
    usuario.refresh_from_db(fields=["is_active", "is_superuser"])
    if not planos_permitidos(usuario).filter(pk=plano.pk).exists():
        raise PermissionDenied("Acesso à matriz ou a um dos destinos foi revogado.")
    if not PlanoReplicacao.objects.filter(pk=plano.pk, ativo=True, arquivado=False).exists():
        raise PermissionDenied("Este plano está pausado.")
    if plano.marca_id and not AmbienteWhiteLabel.objects.filter(pk=plano.marca_id, ativa=True).exists():
        raise PermissionDenied("O ambiente White Label está inativo.")
    empresas = [plano.matriz, *[d.empresa for d in plano.destinos.select_related("empresa")]]
    if len(empresas) < 2:
        raise PermissionDenied("Selecione ao menos uma empresa destino.")
    ids = [empresa.pk for empresa in empresas]
    if Empresa.objects.filter(pk__in=ids, ativa=True).count() != len(ids):
        raise PermissionDenied("Uma das empresas está inativa.")
    chaves = list(IntegracaoOmie.objects.filter(empresa_id__in=ids, ativa=True).exclude(app_key="").values_list("app_key", flat=True))
    if len(chaves) != len(ids):
        raise PermissionDenied("Uma das empresas está sem integração OMIE ativa.")
    if len(set(chaves)) != len(chaves):
        raise PermissionDenied("Matriz e destinos devem usar aplicativos OMIE distintos.")


def contexto_plano(plano):
    # Worker tasks restore the immutable plan scope and recheck current authority.
    return _marca_host.set(plano.marca)
