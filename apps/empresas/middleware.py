from django.urls import Resolver404, resolve

from .auditoria import registrar_acao
from .models import AcaoUsuarioLog, Empresa


class AuditLogMiddleware:
    SKIP_PREFIXES = ("/static/", "/media/", "/admin/", "/healthz")
    SKIP_VIEW_NAMES = {"accounts:login", "accounts:logout"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._registrar_request(request, response)
        return response

    def _registrar_request(self, request, response):
        usuario = getattr(request, "user", None)
        if not getattr(usuario, "is_authenticated", False):
            return
        if response.status_code >= 400 or request.path_info.startswith(self.SKIP_PREFIXES):
            return

        match = getattr(request, "resolver_match", None)
        if match is None:
            try:
                match = resolve(request.path_info)
            except Resolver404:
                return

        view_name = match.view_name or ""
        if view_name in self.SKIP_VIEW_NAMES:
            return

        empresa = self._empresa(match.kwargs.get("empresa_slug"))
        dados = {"view": view_name, "kwargs": match.kwargs}
        tipo = None
        descricao = ""

        if request.method == "GET":
            tipo, descricao = self._classificar_acesso(view_name, match.kwargs)
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            tipo = AcaoUsuarioLog.Tipo.EXCLUSAO if self._eh_exclusao(view_name, request) else AcaoUsuarioLog.Tipo.ALTERACAO
            descricao = self._descricao_alteracao(view_name)

        if not tipo:
            return

        registrar_acao(
            usuario=usuario,
            empresa=empresa,
            tipo=tipo,
            descricao=descricao,
            request=request,
            dados=dados,
        )

    def _empresa(self, empresa_slug):
        if not empresa_slug:
            return None
        return Empresa.objects.filter(slug=empresa_slug).first()

    def _classificar_acesso(self, view_name, kwargs):
        if view_name == "empresas:lista":
            return AcaoUsuarioLog.Tipo.ACESSO_EMPRESA, "Acessou lista de empresas"
        if view_name == "empresas:configuracoes":
            return AcaoUsuarioLog.Tipo.ACESSO_EMPRESA, "Acessou configuracoes de empresas"
        if view_name == "dashboards:controle_logs":
            return AcaoUsuarioLog.Tipo.ACESSO_EMPRESA, "Acessou controle de log"
        if view_name == "dashboards:home":
            return AcaoUsuarioLog.Tipo.ACESSO_EMPRESA, "Acessou inicio da empresa"
        if view_name == "dashboards:area":
            area = kwargs.get("area_slug", "")
            return AcaoUsuarioLog.Tipo.MODULO, f"Acessou modulo {area}"
        if view_name == "dashboards:dashboard":
            area = kwargs.get("area_slug", "")
            dashboard = kwargs.get("dashboard_slug", "")
            return AcaoUsuarioLog.Tipo.DASHBOARD, f"Acessou dashboard {area}/{dashboard}"
        if view_name.startswith("dashboards:") and "/parametros/" in view_name:
            return AcaoUsuarioLog.Tipo.MODULO, "Acessou parametros"
        return None, ""

    def _eh_exclusao(self, view_name, request):
        alvo = f"{view_name} {request.path_info}".lower()
        return request.method == "DELETE" or "excluir" in alvo or "delete" in alvo

    def _descricao_alteracao(self, view_name):
        if view_name:
            return f"Executou alteracao em {view_name}"
        return "Executou alteracao"
