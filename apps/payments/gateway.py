"""Backend selection and the charge entry point used by checkout."""

from decimal import Decimal

from django.conf import settings
from django.utils.module_loading import import_string

from apps.payments.backends.invoice import InvoiceBackend, StoreCreditBackend
from apps.payments.models import Payment

BUILTIN_BACKENDS = {
    "invoice": "apps.payments.backends.invoice.InvoiceBackend",
    "credit": "apps.payments.backends.invoice.StoreCreditBackend",
    "stripe": "apps.payments.backends.stripe.StripeBackend",
}


def get_backend(name=None):
    """Resolve the configured payment backend."""
    name = name or getattr(settings, "PAYMENT_BACKEND", "invoice")
    path = BUILTIN_BACKENDS.get(name, name)
    backend_class = import_string(path)
    return backend_class(**getattr(settings, "PAYMENT_BACKEND_CONFIG", {}))


def charge_order(order, backend=None):
    """Charge an order for whatever is still owed.

    An order already covered by gift cards and points is settled through the
    store-credit backend rather than sent to a card processor for $0.00.
    """
    amount = Decimal(order.grand_total)
    if amount <= Decimal("0.00"):
        backend = StoreCreditBackend()
        method = Payment.Method.CREDIT
    else:
        backend = backend or get_backend()
        method = (
            Payment.Method.INVOICE
            if isinstance(backend, InvoiceBackend)
            else Payment.Method.CARD
        )

    payment = Payment.objects.create(
        order=order,
        provider=backend.name,
        method=method,
        amount=amount,
        status=Payment.Status.PENDING,
    )

    result = backend.charge(order, amount)
    payment.reference = result.reference
    payment.client_secret = result.client_secret
    payment.raw_response = result.raw
    payment.error_message = result.error_message

    if not result.success:
        payment.status = Payment.Status.FAILED
        payment.save()
        return payment

    payment.status = result.status
    payment.save()
    if payment.status == Payment.Status.PAID:
        payment.mark_paid(reference=result.reference, raw=result.raw)
    return payment
