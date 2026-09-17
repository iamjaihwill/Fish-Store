"""Invoice backend: the order is placed, payment is collected afterwards.

This is how a lot of coral shops actually work, especially for live sale claims
where the final box is assembled from several wins and shipping is quoted once
at the end. It is also the default here because it needs no credentials.
"""

from apps.payments.backends.base import ChargeResult, PaymentBackend
from apps.payments.models import Payment


class InvoiceBackend(PaymentBackend):
    name = "invoice"
    label = "Invoice me (we'll send a payment link)"

    def charge(self, order, amount, **kwargs):
        return ChargeResult(
            success=True,
            status=Payment.Status.PENDING,
            reference=f"INV-{order.number}",
            raw={"note": "Awaiting invoice payment."},
        )

    def refund(self, payment, amount, reason=""):
        return ChargeResult(
            success=True,
            status=Payment.Status.REFUNDED,
            reference=payment.reference,
            raw={"note": "Invoice voided."},
        )


class StoreCreditBackend(PaymentBackend):
    """Used when gift cards and points already cover the whole order."""

    name = "credit"
    label = "Store credit"

    def charge(self, order, amount, **kwargs):
        if amount > 0:
            return ChargeResult(
                success=False,
                status=Payment.Status.FAILED,
                error_message="Store credit does not cover the full amount.",
            )
        return ChargeResult(
            success=True,
            status=Payment.Status.PAID,
            reference=f"CREDIT-{order.number}",
            raw={"note": "Covered by gift card and points."},
        )

    def refund(self, payment, amount, reason=""):
        return ChargeResult(
            success=True, status=Payment.Status.REFUNDED, reference=payment.reference
        )
