"""Warn customers before reward points expire.

    manage.py send_points_expiry_reminders --days 14
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.notifications.senders import send_points_expiring
from apps.rewards.models import PointsTransaction, RewardsSettings, balance_for


class Command(BaseCommand):
    help = "Email customers whose reward points are about to expire."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=14, help="Warn this many days ahead."
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        rewards = RewardsSettings.load()
        if not rewards.is_enabled or not rewards.expiry_days:
            self.stdout.write("Points do not expire; nothing to do.")
            return

        now = timezone.now()
        horizon = now + timezone.timedelta(days=options["days"])
        expiring = (
            PointsTransaction.objects.filter(
                kind=PointsTransaction.Kind.EARNED,
                expires_at__gt=now,
                expires_at__lte=horizon,
            )
            .values("customer", "expires_at__date")
            .annotate(points=Sum("points"))
        )

        sent = 0
        for row in expiring:
            from apps.accounts.models import Customer

            customer = Customer.objects.filter(pk=row["customer"]).first()
            if customer is None:
                continue
            # Never promise more than the customer can actually spend.
            points = min(row["points"], balance_for(customer))
            if points <= 0:
                continue

            expires_on = row["expires_at__date"]
            if options["dry_run"]:
                self.stdout.write(
                    f"would warn {customer.email}: {points} points expire {expires_on}"
                )
                sent += 1
                continue
            if send_points_expiring(
                customer, points, expires_on, rewards.value_of(points)
            ) is not None:
                sent += 1

        verb = "Would send" if options["dry_run"] else "Sent"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} expiry reminders."))
