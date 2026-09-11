from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


admin.site.site_header = settings.APP_BRAND_ADMIN_HEADER
admin.site.site_title = settings.APP_BRAND_ADMIN_TITLE
admin.site.index_title = settings.APP_BRAND_ADMIN_INDEX_TITLE

def healthz(_request):
    return HttpResponse("ok\n", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("conta/", include("apps.accounts.urls")),
    path("", include("apps.empresas.urls")),
    path("empresas/<slug:empresa_slug>/dashboard/", include("apps.dashboards.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
