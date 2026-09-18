"""Email people who left a cart behind.

Run on a timer, e.g. hourly:

    manage.py send_abandoned_cart_emails
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.notifications.models import AbandonedCart
from apps.notifications.senders import send_abandoned_cart


class Command(BaseCommand):
    help = "Send reminder emails for carts that were abandoned."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=getattr(settings, "ABANDONED_CART_DELAY_HOURS", 6),
            help="Hours of inactivity before the first reminder, and between reminders.",
        )
        parser.add_argument(
            "--max-reminders",
            type=int,
            default=getattr(settings, "ABANDONED_CART_MAX_REMINDERS", 2),
            help="Never send more than this many reminders for one cart.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        carts = AbandonedCart.objects.due_for_reminder(
            after_hours=options["hours"], max_reminders=options["max_reminders"]
        ).select_related("customer__user")

        sent = 0
        for cart in carts:
            if dry_run:
                self.stdout.write(
                    f"would remind {cart.email} about ${cart.subtotal} "
                    f"(reminder {cart.reminders_sent + 1})"
                )
                sent += 1
                continue
            if send_abandoned_cart(cart) is not None:
                cart.record_reminder()
                sent += 1

        verb = "Would send" if dry_run else "Sent"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} abandoned cart reminders."))
