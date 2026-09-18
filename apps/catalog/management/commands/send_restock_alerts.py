"""Email wishlist holders when a sold-out product comes back.

Run on a schedule (cron, Celery beat, systemd timer):

    manage.py send_restock_alerts
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import WishlistItem
from apps.notifications.senders import send_back_in_stock


class Command(BaseCommand):
    help = "Notify wishlist holders about products that are back in stock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without emailing or marking anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        candidates = (
            WishlistItem.objects.filter(
                notify_when_available=True, notified_at__isnull=True
            )
            .select_related("product", "customer__user")
            .prefetch_related("product__variants")
        )

        sent = 0
        for item in candidates:
            product = item.product
            if not product.is_published or product.is_sold_out:
                continue

            if dry_run:
                self.stdout.write(f"would notify {item.customer.email} about {product.name}")
                sent += 1
                continue

            send_back_in_stock(item)
            item.mark_notified()
            sent += 1

        verb = "Would notify" if dry_run else "Notified"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} wishlist holders."))
