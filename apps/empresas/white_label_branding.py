"""Identidade visual por marca; nao concede permissoes de acesso aos dados."""
import re

from django.utils import timezone

from .models import AmbienteWhiteLabel

SESSION_MARCA = "white_label_ambiente"
COR_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def cor_segura(valor, padrao):
    return valor.lower() if isinstance(valor, str) and COR_HEX.fullmatch(valor) else padrao


def misturar_branco(cor, proporcao=.94):
    return "#" + "".join(f"{round(int(cor[i:i+2],16)*(1-proporcao)+255*proporcao):02x}" for i in (1,3,5))


def texto_contraste(cor):
    valores = [int(cor[i:i+2],16)/255 for i in (1,3,5)]
    valores = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in valores]
    luminancia = sum(v*p for v,p in zip(valores,(.2126,.7152,.0722)))
    return "#ffffff" if 1.05/(luminancia+.05) >= (luminancia+.05)/.05 else "#111827"


def marca_do_request(request):
    if hasattr(request, "_white_label_marca"):
        return request._white_label_marca
    marca = None
    kwargs = getattr(getattr(request, "resolver_match", None), "kwargs", {})
    if kwargs.get("marca_slug"):
        marca = AmbienteWhiteLabel.objects.filter(slug=kwargs["marca_slug"], ativa=True).first()
    elif kwargs.get("slug") and getattr(request, "user", None) and request.user.is_authenticated:
        from .white_label_services import ambientes_administraveis
        marca = ambientes_administraveis(request.user).filter(slug=kwargs["slug"]).first()
    if marca is None:
        identificador = getattr(request, "session", {}).get(SESSION_MARCA)
        if isinstance(identificador, int):
            marca = AmbienteWhiteLabel.objects.filter(pk=identificador, ativa=True).first()
    empresa_slug = kwargs.get("empresa_slug")
    if empresa_slug and (marca is None or not marca.empresas.filter(slug=empresa_slug).exists()):
        marcas = list(AmbienteWhiteLabel.objects.filter(ativa=True, identidade_personalizada=True, empresas__slug=empresa_slug).distinct()[:2])
        marca = marcas[0] if len(marcas) == 1 else None
    request._white_label_marca = marca
    return marca


def contexto_identidade(marca):
    p = cor_segura(marca.cor_primaria, "#217ed4")
    s = cor_segura(marca.cor_secundaria, "#214fac")
    a = cor_segura(marca.cor_destaque, "#20cfa1")
    layout = marca.layout_login if marca.layout_login in AmbienteWhiteLabel.Layout.values else "classico"
    fundo = cor_segura(marca.cor_fundo, "#f3f7fb") if layout == "aurora" else misturar_branco(p)
    link = p if texto_contraste(p) == "#ffffff" else s if texto_contraste(s) == "#ffffff" else "#17243a"
    return {
        "white_label_marca": marca, "white_label_tema": True,
        "white_label_layout": layout,
        "wl_primaria": p, "wl_secundaria": s, "wl_destaque": a, "wl_fundo": fundo,
        "wl_link": link,
        "wl_clara": misturar_branco(p), "wl_texto_primaria": texto_contraste(p),
        "wl_texto_secundaria": texto_contraste(s), "wl_texto_fundo": texto_contraste(fundo),
        "app_brand_name": marca.nome, "app_brand_navbar_text": marca.nome,
        "app_brand_login_logo_url": marca.logo_login.url if marca.logo_login else "",
        "app_brand_navbar_logo_url": marca.logo_navbar.url if marca.logo_navbar else "",
        "app_brand_footer_text": f"{timezone.localdate().year} {marca.nome}",
        "app_brand_footer_subtitle": "Inteligência para decisões melhores.",
        "app_brand_meta_description": f"{marca.nome} — Business Intelligence",
    }
