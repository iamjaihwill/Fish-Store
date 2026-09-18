"""Deployment checks for the email subsystem."""

from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_site_base_url(app_configs, **kwargs):
    """Email links are useless if they are relative.

    In development a relative path is fine -- nothing is really being posted.
    In production every link in every transactional email would be broken, and
    that is not something to discover from a customer complaint.
    """
    if settings.DEBUG or getattr(settings, "SITE_BASE_URL", ""):
        return []
    return [
        Warning(
            "SITE_BASE_URL is not set, so links in transactional email will be "
            "relative paths and will not work in a mail client.",
            hint="Set DJANGO_SITE_BASE_URL to the storefront's public origin, "
            "e.g. https://shop.example.com",
            id="notifications.W001",
        )
    ]
