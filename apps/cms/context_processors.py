"""Make site chrome (settings, nav, announcement) available to every template."""

from apps.catalog.models import Category
from apps.cms.models import NavigationLink, Page, SiteSettings


def site_chrome(request):
    settings_obj = SiteSettings.load()
    nav_links = NavigationLink.objects.filter(is_active=True).select_related("page")
    return {
        "site": settings_obj,
        "nav_categories": Category.objects.active()
        .top_level()
        .filter(show_in_nav=True)
        .prefetch_related("children"),
        "header_links": [
            link
            for link in nav_links
            if link.placement == NavigationLink.Placement.HEADER
        ],
        "footer_shop_links": [
            link
            for link in nav_links
            if link.placement == NavigationLink.Placement.FOOTER_SHOP
        ],
        "footer_support_links": [
            link
            for link in nav_links
            if link.placement == NavigationLink.Placement.FOOTER_SUPPORT
        ],
        "footer_pages": Page.objects.filter(is_published=True, show_in_footer=True),
    }
