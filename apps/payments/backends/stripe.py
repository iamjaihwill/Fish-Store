"""Stripe backend.

Talks to Stripe over its REST API with the standard library, so the store does
not take a dependency on the SDK. Set DJANGO_STRIPE_SECRET_KEY and
DJANGO_STRIPE_WEBHOOK_SECRET, and switch PAYMENT_BACKEND to "stripe".

The flow is a PaymentIntent: this creates one, the browser confirms it with the
publishable key, and the webhook (or the return view) settles the order. Card
details never touch this server.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings

from apps.payments.backends.base import ChargeResult, PaymentBackend
from apps.payments.models import Payment

API_ROOT = "https://api.stripe.com/v1"


class StripeError(Exception):
    pass


class StripeBackend(PaymentBackend):
    name = "stripe"
    label = "Credit or debit card"

    def __init__(self, **config):
        super().__init__(**config)
        self.secret_key = config.get("secret_key") or getattr(
            settings, "STRIPE_SECRET_KEY", ""
        )
        self.webhook_secret = config.get("webhook_secret") or getattr(
            settings, "STRIPE_WEBHOOK_SECRET", ""
        )

    # --- transport -------------------------------------------------------
    def _request(self, path, data=None, method="POST"):
        if not self.secret_key:
            raise StripeError("STRIPE_SECRET_KEY is not configured.")
        url = f"{API_ROOT}/{path}"
        body = urllib.parse.urlencode(data or {}, doseq=True).encode()
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.secret_key}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            message = payload.get("error", {}).get("message", str(exc))
            raise StripeError(message) from exc
        except urllib.error.URLError as exc:
            raise StripeError(f"Could not reach Stripe: {exc.reason}") from exc

    @staticmethod
    def to_minor_units(amount):
        """Stripe works in cents; never send a float."""
        return int((Decimal(amount) * 100).to_integral_value())

    # --- backend API -----------------------------------------------------
    def charge(self, order, amount, **kwargs):
        try:
            payload = self._request(
                "payment_intents",
                {
                    "amount": self.to_minor_units(amount),
                    "currency": "usd",
                    "automatic_payment_methods[enabled]": "true",
                    "metadata[order_number]": order.number,
                    "metadata[order_id]": order.pk,
                    "receipt_email": order.email,
                    "description": f"{order.number} — livestock order",
                },
            )
        except StripeError as exc:
            return ChargeResult(
                success=False,
                status=Payment.Status.FAILED,
                error_message=str(exc),
            )

        status = payload.get("status", "")
        settled = status == "succeeded"
        return ChargeResult(
            success=True,
            status=Payment.Status.PAID if settled else Payment.Status.REQUIRES_ACTION,
            reference=payload.get("id", ""),
            client_secret=payload.get("client_secret", ""),
            requires_action=not settled,
            raw=payload,
        )

    def refund(self, payment, amount, reason=""):
        try:
            payload = self._request(
                "refunds",
                {
                    "payment_intent": payment.reference,
                    "amount": self.to_minor_units(amount),
                },
            )
        except StripeError as exc:
            return ChargeResult(
                success=False, status=Payment.Status.FAILED, error_message=str(exc)
            )
        return ChargeResult(
            success=True,
            status=Payment.Status.REFUNDED,
            reference=payload.get("id", ""),
            raw=payload,
        )

    # --- webhooks --------------------------------------------------------
    def verify_signature(self, payload, signature_header, tolerance=300):
        """Verify Stripe's signature header.

        Implements the documented scheme: the signed payload is
        "<timestamp>.<body>", compared with a constant-time digest, and old
        timestamps are refused so a captured request cannot be replayed.
        """
        if not self.webhook_secret:
            raise StripeError("STRIPE_WEBHOOK_SECRET is not configured.")
        parts = dict(
            piece.split("=", 1) for piece in signature_header.split(",") if "=" in piece
        )
        timestamp = parts.get("t")
        provided = parts.get("v1")
        if not timestamp or not provided:
            return False
        if abs(time.time() - int(timestamp)) > tolerance:
            return False

        signed = f"{timestamp}.".encode() + payload
        expected = hmac.new(
            self.webhook_secret.encode(), signed, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    def handle_webhook(self, request):
        signature = request.headers.get("Stripe-Signature", "")
        try:
            if not self.verify_signature(request.body, signature):
                return False, "Invalid signature."
        except StripeError as exc:
            return False, str(exc)

        event = json.loads(request.body.decode() or "{}")
        kind = event.get("type", "")
        intent = event.get("data", {}).get("object", {})
        reference = intent.get("id", "")
        if not reference:
            return False, "No payment intent on the event."

        payment = Payment.objects.filter(reference=reference).first()
        if payment is None:
            return False, f"No local payment for {reference}."

        if kind == "payment_intent.succeeded":
            payment.mark_paid(reference=reference, raw=intent)
            return True, "Payment settled."
        if kind == "payment_intent.payment_failed":
            message = intent.get("last_payment_error", {}).get("message", "Card declined.")
            payment.mark_failed(message, raw=intent)
            return True, "Payment failed recorded."
        return True, f"Ignored event {kind}."
