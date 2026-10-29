from django.db.models import Q

from .models import AmbienteWhiteLabel, Empresa, EmpresaUsuario
from .white_label_domains import limitar_empresas, marca_host_atual


def ambientes_administraveis(usuario):
    qs = AmbienteWhiteLabel.objects.all()
    marca = marca_host_atual()
    if marca is not None:
        qs = qs.filter(pk=marca.pk)
    if not usuario.is_authenticated or not usuario.is_active:
        return qs.none()
    if usuario.is_superuser:
        return qs
    # Keep the outer query free of joins/DISTINCT so row locks work in PostgreSQL.
    return qs.filter(ativa=True, pk__in=qs.filter(administradores=usuario).values("pk"))


def administra_empresa_por_ambiente(usuario, empresa):
    return ambientes_administraveis(usuario).filter(empresas=empresa).exists()


def empresas_vinculaveis(usuario):
    if usuario.is_superuser:
        return limitar_empresas(Empresa.objects.all())
    if not usuario.is_authenticated or not usuario.is_active:
        return Empresa.objects.none()
    administracao_marca = Q(ambientes_white_label__ativa=True, ambientes_white_label__administradores=usuario)
    marca = marca_host_atual()
    if marca is not None:
        administracao_marca &= Q(ambientes_white_label__pk=marca.pk)
    return limitar_empresas(Empresa.objects.filter(
        administracao_marca
        | Q(vinculos__usuario=usuario, vinculos__ativo=True, vinculos__papel=EmpresaUsuario.Papel.ADM_WHITE_LABEL)
    )).distinct()
