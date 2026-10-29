from django.shortcuts import get_object_or_404
from django.db.models import Q

from .models import Empresa, EmpresaUsuario
from .white_label_services import administra_empresa_por_ambiente
from .white_label_domains import limitar_empresas, marca_host_atual

PERFIS_MASTER = {EmpresaUsuario.Papel.ADM_WHITE_LABEL, EmpresaUsuario.Papel.GESTOR}


def empresas_permitidas(usuario):
    queryset = limitar_empresas(Empresa.objects.filter(ativa=True))
    if not usuario.is_authenticated or not usuario.is_active:
        return queryset.none()
    if usuario.is_superuser:
        return queryset
    administracao_marca = Q(ambientes_white_label__ativa=True, ambientes_white_label__administradores=usuario)
    marca = marca_host_atual()
    if marca is not None:
        administracao_marca &= Q(ambientes_white_label__pk=marca.pk)
    return queryset.filter(
        Q(vinculos__usuario=usuario, vinculos__ativo=True)
        | administracao_marca
    ).distinct()


def empresas_permitidas_no_grupo(usuario, empresa, area_slug=None, dashboard_slug=None):
    grupo = (empresa.grupo or "").strip()
    queryset = empresas_permitidas(usuario)
    queryset = queryset.filter(grupo__iexact=grupo) if grupo else queryset.filter(pk=empresa.pk)
    if area_slug and dashboard_slug and not usuario.is_superuser:
        permitidas = [item.pk for item in queryset if usuario_pode_acessar_dashboard(usuario, item, area_slug, dashboard_slug)]
        queryset = queryset.filter(pk__in=permitidas)
    return queryset


def obter_empresa_permitida(usuario, slug):
    return get_object_or_404(empresas_permitidas(usuario), slug=slug)


def vinculo_empresa(usuario, empresa):
    marca = marca_host_atual()
    if marca is not None and not marca.empresas.filter(pk=empresa.pk).exists():
        return None
    if not usuario.is_authenticated or not usuario.is_active or usuario.is_superuser:
        return None
    if administra_empresa_por_ambiente(usuario, empresa):
        return EmpresaUsuario(empresa=empresa, usuario=usuario, papel=EmpresaUsuario.Papel.ADM_WHITE_LABEL, ativo=True)
    return EmpresaUsuario.objects.filter(usuario=usuario, empresa=empresa, ativo=True).select_related("empresa", "usuario").first()


def usuario_admin_empresa(usuario, empresa):
    if usuario.is_superuser:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(vinculo and vinculo.papel in PERFIS_MASTER)


def usuario_gestor_empresa(usuario, empresa):
    return usuario_admin_empresa(usuario, empresa)


def usuario_pode_personalizar_marca(usuario, empresa):
    if usuario.is_superuser:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(vinculo and vinculo.papel == EmpresaUsuario.Papel.ADM_WHITE_LABEL)


def papeis_gerenciaveis(usuario, empresa):
    if usuario.is_superuser:
        return set(EmpresaUsuario.Papel.values)
    vinculo = vinculo_empresa(usuario, empresa)
    if not vinculo:
        return set()
    if vinculo.papel == EmpresaUsuario.Papel.ADM_WHITE_LABEL:
        return set(EmpresaUsuario.Papel.values)
    if vinculo.papel == EmpresaUsuario.Papel.GESTOR:
        return {EmpresaUsuario.Papel.GESTOR, EmpresaUsuario.Papel.LIDER, EmpresaUsuario.Papel.VISUALIZADOR}
    if vinculo.papel == EmpresaUsuario.Papel.LIDER:
        return {EmpresaUsuario.Papel.VISUALIZADOR}
    return set()


def usuario_pode_gerenciar_vinculo(usuario, empresa, vinculo_alvo=None):
    papeis = papeis_gerenciaveis(usuario, empresa)
    if not papeis:
        return False
    if vinculo_alvo is None:
        return True
    if vinculo_alvo.empresa_id != empresa.pk:
        return False
    if usuario.is_superuser:
        return True
    if isinstance(vinculo_alvo, EmpresaUsuario):
        if vinculo_alvo.usuario_id == usuario.pk or vinculo_alvo.usuario.is_superuser:
            return False
    vinculo = vinculo_empresa(usuario, empresa)
    if vinculo.papel == EmpresaUsuario.Papel.LIDER:
        return vinculo_alvo.papel in papeis and vinculo_alvo.delegado_por_id == vinculo.pk
    return vinculo_alvo.papel in papeis


def _vinculo_tem_acesso(vinculo, area, dashboard=None):
    if not vinculo.ativo or not vinculo.usuario.is_active:
        return False
    if vinculo.papel in PERFIS_MASTER:
        return True
    if vinculo.papel not in EmpresaUsuario.Papel.values:
        return False
    if vinculo.areas_permitidas and area not in vinculo.areas_permitidas:
        return False
    if vinculo.dashboards_permitidos:
        if dashboard and f"{area}:{dashboard}" not in vinculo.dashboards_permitidos:
            return False
        if not dashboard and not any(d.startswith(f"{area}:") for d in vinculo.dashboards_permitidos):
            return False
    if vinculo.delegado_por_id:
        lider = vinculo.delegado_por
        if lider.empresa_id != vinculo.empresa_id or lider.delegado_por_id:
            return False
        if lider.papel not in PERFIS_MASTER | {EmpresaUsuario.Papel.LIDER}:
            return False
        return _vinculo_tem_acesso(lider, area, dashboard)
    return True


def usuario_pode_acessar_area(usuario, empresa, area_slug):
    if usuario.is_superuser:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(vinculo and _vinculo_tem_acesso(vinculo, area_slug))


def usuario_pode_acessar_dashboard(usuario, empresa, area_slug, dashboard_slug):
    if usuario.is_superuser:
        return True
    vinculo = vinculo_empresa(usuario, empresa)
    return bool(vinculo and _vinculo_tem_acesso(vinculo, area_slug, dashboard_slug))


def escopo_delegavel(usuario, empresa, areas):
    vinculo = vinculo_empresa(usuario, empresa)
    def permitido(area, dashboard=None):
        return usuario.is_superuser or bool(vinculo and _vinculo_tem_acesso(vinculo, area, dashboard))
    modulos = {slug for slug in areas if permitido(slug)}
    dashboards = {f"{slug}:{dashboard['slug']}" for slug in modulos
                  for dashboard in areas[slug]["dashboards"] if permitido(slug, dashboard["slug"])}
    return modulos, dashboards


def areas_permitidas_usuario(usuario, empresa, areas):
    return {slug: area for slug, area in areas.items() if usuario_pode_acessar_area(usuario, empresa, slug)}


def dashboards_permitidos_usuario(usuario, empresa, area_slug, dashboards):
    return [dashboard for dashboard in dashboards if usuario_pode_acessar_dashboard(usuario, empresa, area_slug, dashboard["slug"])]
