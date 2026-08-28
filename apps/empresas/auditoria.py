from django.db import DatabaseError

from .models import AcaoUsuarioLog


def obter_ip(request):
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encaminhado:
        return encaminhado.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def registrar_acao(
    *,
    usuario=None,
    empresa=None,
    tipo,
    descricao,
    request=None,
    dados=None,
):
    payload = {
        "usuario": usuario if getattr(usuario, "is_authenticated", False) else None,
        "empresa": empresa,
        "tipo": tipo,
        "descricao": descricao[:255],
        "dados": dados or {},
    }
    if request:
        payload.update(
            {
                "metodo": request.method,
                "caminho": request.get_full_path()[:500],
                "ip": obter_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            }
        )
    try:
        return AcaoUsuarioLog.objects.create(**payload)
    except DatabaseError:
        return None
