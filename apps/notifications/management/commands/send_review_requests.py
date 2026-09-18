"""Ask for a review once an order has had time to settle in.

Corals look terrible for the first week, so this deliberately waits rather than
emailing the moment a box lands.

    manage.py send_review_requests
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import EmailLog
from apps.notifications.senders import send_review_request
from apps.shop.models import Order


class Command(BaseCommand):
    help = "Email review requests for orders delivered a while ago."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=getattr(settings, "REVIEW_REQUEST_DELAY_DAYS", 14),
            help="Days after delivery before asking.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(days=options["days"])
        already = set(
            EmailLog.objects.filter(
                key="review_request", status=EmailLog.Status.SENT
            ).values_list("order_id", flat=True)
        )
        orders = (
            Order.objects.filter(
                status=Order.Status.DELIVERED, delivered_at__lte=cutoff
            )
            .exclude(pk__in=already)
            .prefetch_related("items__product")
        )

        sent = 0
        for order in orders:
            # Nothing to review if every product has since been deleted.
            if not any(item.product_id for item in order.items.all()):
                continue
            if options["dry_run"]:
                self.stdout.write(f"would ask {order.email} about {order.number}")
            elif send_review_request(order) is None:
                continue
            sent += 1

        verb = "Would send" if options["dry_run"] else "Sent"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} review requests."))
