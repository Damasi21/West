from django.db.models import Q

from .models import AmbienteWhiteLabel, Empresa, EmpresaUsuario


def ambientes_administraveis(usuario):
    qs = AmbienteWhiteLabel.objects.all()
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
        return Empresa.objects.all()
    if not usuario.is_authenticated or not usuario.is_active:
        return Empresa.objects.none()
    return Empresa.objects.filter(
        Q(ambientes_white_label__ativa=True, ambientes_white_label__administradores=usuario)
        | Q(vinculos__usuario=usuario, vinculos__ativo=True, vinculos__papel=EmpresaUsuario.Papel.ADM_WHITE_LABEL)
    ).distinct()
