from django.conf import settings


def brand(request):
    from apps.empresas.models import Empresa
    from apps.empresas.services import usuario_pode_gerenciar_vinculo
    from apps.empresas.white_label_services import ambientes_administraveis
    slug = getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("empresa_slug")
    empresa = Empresa.objects.filter(slug=slug, ativa=True).first() if slug else None
    pode_gerenciar = bool(empresa and request.user.is_authenticated and usuario_pode_gerenciar_vinculo(request.user, empresa))
    pode_white_label = request.user.is_authenticated and (request.user.is_superuser or ambientes_administraveis(request.user).exists())
    return {
        "pode_gerenciar_usuarios": pode_gerenciar,
        "pode_gerenciar_white_label": pode_white_label,
        "app_brand_name": settings.APP_BRAND_NAME,
        "app_brand_navbar_text": settings.APP_BRAND_NAVBAR_TEXT,
        "app_brand_login_logo": settings.APP_BRAND_LOGIN_LOGO,
        "app_brand_navbar_logo": settings.APP_BRAND_NAVBAR_LOGO,
        "app_brand_hero_eyebrow": settings.APP_BRAND_HERO_EYEBROW,
        "app_brand_hero_title": settings.APP_BRAND_HERO_TITLE,
        "app_brand_hero_subtitle": settings.APP_BRAND_HERO_SUBTITLE,
        "app_brand_register_eyebrow": settings.APP_BRAND_REGISTER_EYEBROW,
        "app_brand_register_title": settings.APP_BRAND_REGISTER_TITLE,
        "app_brand_register_subtitle": settings.APP_BRAND_REGISTER_SUBTITLE,
        "app_brand_meta_description": settings.APP_BRAND_META_DESCRIPTION,
        "app_brand_footer_text": settings.APP_BRAND_FOOTER_TEXT,
        "app_brand_footer_subtitle": settings.APP_BRAND_FOOTER_SUBTITLE,
        "static_asset_version": settings.STATIC_ASSET_VERSION,
    }
