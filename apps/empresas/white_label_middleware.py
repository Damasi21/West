from django.conf import settings
from django.http import HttpResponseNotFound
from django.utils.deprecation import MiddlewareMixin

from .models import AmbienteWhiteLabel
from .white_label_branding import SESSION_MARCA
from .white_label_domains import _marca_host


class WhiteLabelDomainMiddleware(MiddlewareMixin):
    """Host validado pelo Django, nunca X-Forwarded-Host ou parametros do cliente."""

    async_capable = False

    def __call__(self, request):
        # This project uses the synchronous WSGI stack. ContextVar isolates requests
        # and reset in finally also covers errors; tasks have no ambient host scope.
        token = _marca_host.set(None)
        try:
            host = request.get_host().split(":", 1)[0].lower().rstrip(".")
            request.white_label_host = None
            if host not in settings.WHITE_LABEL_PRIMARY_HOSTS:
                marca = AmbienteWhiteLabel.objects.filter(dominio=host).first()
                if not marca or not marca.ativa or not marca.dominio_ativo:
                    return self.indisponivel()
                request.white_label_host = marca
                request._white_label_marca = marca
                request._white_label_forcar_tema = True
                request.session[SESSION_MARCA] = marca.pk
                _marca_host.set(marca)
            response = super().__call__(request)
            if request.white_label_host:
                if response.streaming:
                    response.streaming_content = self.conteudo_no_ambiente(response.streaming_content, marca)
                response["Cache-Control"] = "private, no-store"
                response["Vary"] = ", ".join(dict.fromkeys(
                    [v.strip() for v in response.get("Vary", "").split(",") if v.strip()] + ["Host", "Cookie"]
                ))
            return response
        finally:
            _marca_host.reset(token)

    @staticmethod
    def conteudo_no_ambiente(conteudo, marca):
        # Exports may evaluate permissions lazily while the response is streamed.
        iterator = iter(conteudo)
        try:
            while True:
                token = _marca_host.set(marca)
                try:
                    chunk = next(iterator)
                except StopIteration:
                    return
                finally:
                    _marca_host.reset(token)
                yield chunk
        finally:
            if hasattr(iterator, "close"):
                iterator.close()

    @staticmethod
    def indisponivel():
        response = HttpResponseNotFound("Endereço indisponível.")
        response["Cache-Control"] = "private, no-store"
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        marca = request.white_label_host
        if marca is None:
            return None
        match = request.resolver_match
        # Platform administration and independent trial signup belong to the main
        # host. No superuser bypass on a branded host, including guessed URLs.
        if match.app_name == "admin" or match.view_name in {
            "empresas:configuracoes", "empresas:cadastrar", "empresas:editar",
            "empresas:trial", "empresas:white_label_novo",
        }:
            return self.indisponivel()
        slug = view_kwargs.get("empresa_slug")
        if slug and not marca.empresas.filter(slug=slug).exists():
            return self.indisponivel()
        marca_slug = view_kwargs.get("marca_slug") or (
            view_kwargs.get("slug") if match.view_name.startswith("empresas:white_label") else None
        )
        if marca_slug and marca_slug != marca.slug:
            return self.indisponivel()
        return None
