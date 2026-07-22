from django.shortcuts import get_object_or_404

from .models import Empresa, EmpresaUsuario


def empresas_permitidas(usuario):
    queryset = Empresa.objects.filter(ativa=True)
    if usuario.is_superuser or usuario.is_staff:
        return queryset
    return queryset.filter(
        vinculos__usuario=usuario,
        vinculos__ativo=True,
    ).distinct()


def empresas_permitidas_no_grupo(usuario, empresa):
    grupo = (empresa.grupo or "").strip()
    queryset = empresas_permitidas(usuario)
    if not grupo:
        return queryset.filter(pk=empresa.pk)
    return queryset.filter(grupo__iexact=grupo)


def obter_empresa_permitida(usuario, slug):
    return get_object_or_404(empresas_permitidas(usuario), slug=slug)


def vinculo_empresa(usuario, empresa):
    if not usuario.is_authenticated or usuario.is_superuser or usuario.is_staff:
        return None
    return (
        EmpresaUsuario.objects.filter(
            usuario=usuario,
            empresa=empresa,
            ativo=True,
        )
        .select_related("empresa", "usuario")
        .first()
    )


def usuario_admin_empresa(usuario, empresa):
    if usuario.is_superuser or usuario.is_staff:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(vinculo and vinculo.papel == EmpresaUsuario.Papel.ADMINISTRADOR)


def usuario_gestor_empresa(usuario, empresa):
    if usuario.is_superuser or usuario.is_staff:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(
        vinculo
        and vinculo.papel
        in (EmpresaUsuario.Papel.ADMINISTRADOR, EmpresaUsuario.Papel.GESTOR)
    )


def usuario_pode_gerenciar_vinculo(usuario, empresa, vinculo_alvo=None):
    if usuario.is_superuser or usuario.is_staff:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    if not vinculo:
        return False
    if vinculo.papel == EmpresaUsuario.Papel.ADMINISTRADOR:
        return True
    if vinculo.papel == EmpresaUsuario.Papel.GESTOR:
        if not vinculo_alvo:
            return True
        return vinculo_alvo.papel != EmpresaUsuario.Papel.ADMINISTRADOR
    return False


def _vinculo_tem_area(vinculo, area_slug):
    return not vinculo.areas_permitidas or area_slug in vinculo.areas_permitidas


def usuario_pode_acessar_area(usuario, empresa, area_slug):
    if usuario.is_superuser or usuario.is_staff:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    if not vinculo:
        return False
    if vinculo.papel == EmpresaUsuario.Papel.ADMINISTRADOR:
        return True
    return _vinculo_tem_area(vinculo, area_slug)


def usuario_pode_acessar_dashboard(usuario, empresa, area_slug, dashboard_slug):
    if usuario.is_superuser or usuario.is_staff:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    if not vinculo:
        return False
    if vinculo.papel == EmpresaUsuario.Papel.ADMINISTRADOR:
        return True
    if not _vinculo_tem_area(vinculo, area_slug):
        return False
    if vinculo.papel == EmpresaUsuario.Papel.GESTOR:
        return True
    return (
        not vinculo.dashboards_permitidos
        or f"{area_slug}:{dashboard_slug}" in vinculo.dashboards_permitidos
    )


def areas_permitidas_usuario(usuario, empresa, areas):
    return {
        slug: area
        for slug, area in areas.items()
        if usuario_pode_acessar_area(usuario, empresa, slug)
    }


def dashboards_permitidos_usuario(usuario, empresa, area_slug, dashboards):
    return [
        dashboard
        for dashboard in dashboards
        if usuario_pode_acessar_dashboard(
            usuario,
            empresa,
            area_slug,
            dashboard["slug"],
        )
    ]
