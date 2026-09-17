"""Payment backend contract.

A backend turns an order into a charge. Everything the storefront needs from a
provider is these four methods, so swapping Stripe for anything else is a
settings change rather than a checkout rewrite.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ChargeResult:
    """What a backend reports back about a charge attempt."""

    success: bool
    status: str
    reference: str = ""
    client_secret: str = ""
    error_message: str = ""
    requires_action: bool = False
    redirect_url: str = ""
    raw: dict = field(default_factory=dict)


class PaymentBackend:
    #: Shown on the checkout page.
    name = "base"
    label = "Payment"
    #: True when the customer completes payment away from this site.
    is_offsite = False

    def __init__(self, **config):
        self.config = config

    def charge(self, order, amount, **kwargs):  # pragma: no cover - interface
        raise NotImplementedError

    def refund(self, payment, amount, reason=""):  # pragma: no cover - interface
        raise NotImplementedError

    def handle_webhook(self, request):  # pragma: no cover - interface
        """Process a provider callback. Returns (handled, message)."""
        return False, "This backend does not accept webhooks."

    def supports_amount(self, amount):
        return Decimal(amount) >= Decimal("0.00")
