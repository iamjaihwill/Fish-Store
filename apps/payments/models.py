"""Payment records.

A Payment is this store's own record of a charge attempt, independent of the
provider. The provider's identifier is kept so a charge can always be traced
back, but the order's state is driven by rows here rather than by live API
calls, so the store still works when the provider is unreachable.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

MONEY = {"max_digits": 10, "decimal_places": 2}
ZERO = Decimal("0.00")


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        REQUIRES_ACTION = "requires_action", "Requires customer action"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    class Method(models.TextChoices):
        CARD = "card", "Card"
        INVOICE = "invoice", "Invoice / pay on approval"
        CREDIT = "credit", "Covered by store credit"
        MANUAL = "manual", "Recorded by staff"

    order = models.ForeignKey(
        "shop.Order", on_delete=models.CASCADE, related_name="payments"
    )
    provider = models.CharField(
        max_length=40, help_text="Backend that handled it, e.g. 'stripe'."
    )
    method = models.CharField(max_length=12, choices=Method.choices, default=Method.CARD)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="USD")
    reference = models.CharField(
        max_length=120, blank=True, help_text="Provider's id for this charge."
    )
    client_secret = models.CharField(max_length=255, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.number}: {self.amount} {self.currency} ({self.get_status_display()})"

    @property
    def is_settled(self):
        return self.status == self.Status.PAID

    def mark_paid(self, reference="", raw=None):
        self.status = self.Status.PAID
        self.reference = reference or self.reference
        self.paid_at = self.paid_at or timezone.now()
        if raw is not None:
            self.raw_response = raw
        self.save(update_fields=["status", "reference", "paid_at", "raw_response"])
        self.order.mark_paid()

        from apps.notifications.senders import send_payment_received

        send_payment_received(self)
        return self

    def mark_failed(self, message="", raw=None):
        self.status = self.Status.FAILED
        self.error_message = message[:300]
        if raw is not None:
            self.raw_response = raw
        self.save(update_fields=["status", "error_message", "raw_response"])
        return self


class Refund(models.Model):
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="refunds"
    )
    amount = models.DecimalField(**MONEY)
    reason = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.amount} on {self.payment.order.number}"
