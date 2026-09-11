from django.conf import settings


def brand(request):
    return {
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
    }
