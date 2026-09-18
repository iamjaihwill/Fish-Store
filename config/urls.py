from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.cms.sitemaps import SITEMAPS
from apps.cms.views import robots_txt

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": SITEMAPS},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("robots.txt", robots_txt, name="robots"),
    path("account/", include("apps.accounts.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.notifications.urls")),
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
