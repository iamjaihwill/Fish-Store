from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("account/", include("apps.accounts.urls")),
    path("", include("apps.shop.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.reviews.urls")),
    path("", include("apps.cms.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Reef & Rift"
admin.site.site_title = "Reef & Rift CMS"
admin.site.index_title = "Store management"
