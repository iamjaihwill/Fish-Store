import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import SiteSettings
from apps.payments.backends.base import ChargeResult
from apps.payments.backends.invoice import InvoiceBackend, StoreCreditBackend
from apps.payments.backends.stripe import StripeBackend, StripeError
from apps.payments.gateway import charge_order, get_backend
from apps.payments.models import Payment
from apps.rewards.models import GiftCard
from apps.shop.models import Order

CHECKOUT = {
    "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
    "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
    "state": "NC", "postal_code": "28401", "country": "United States",
    "accepts_livestock_terms": "on",
}


class PaymentBase(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.free_shipping_threshold = Decimal("299.00")
        site.livestock_shipping_rate = Decimal("59.00")
        site.tax_rate_percent = Decimal("0.00")
        site.save()
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=10,
        )

    def make_order(self, total=Decimal("159.00")):
        return Order.objects.create(
            email="sam@example.com", first_name="Sam", last_name="Rivera",
            phone="555-0100", address_line1="12 Coral Way", city="Wilmington",
            state="NC", postal_code="28401", grand_total=total, subtotal=total,
        )


class BackendSelectionTests(PaymentBase):
    def test_default_backend_is_invoice(self):
        self.assertIsInstance(get_backend(), InvoiceBackend)

    @override_settings(PAYMENT_BACKEND="stripe")
    def test_backend_is_selected_from_settings(self):
        self.assertIsInstance(get_backend(), StripeBackend)

    def test_backend_can_be_named_explicitly(self):
        self.assertIsInstance(get_backend("credit"), StoreCreditBackend)


class InvoiceBackendTests(PaymentBase):
    def test_invoice_charge_leaves_the_order_pending(self):
        order = self.make_order()
        payment = charge_order(order)
        order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.method, Payment.Method.INVOICE)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertTrue(payment.reference.startswith("INV-"))

    def test_outstanding_amount_reflects_unpaid_orders(self):
        order = self.make_order(Decimal("159.00"))
        charge_order(order)
        self.assertEqual(order.amount_outstanding, Decimal("159.00"))

    def test_marking_a_payment_paid_advances_the_order(self):
        order = self.make_order()
        payment = charge_order(order)
        payment.mark_paid()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertTrue(order.is_paid)

    def test_marking_paid_does_not_downgrade_a_shipped_order(self):
        order = self.make_order()
        order.mark_shipped()
        order.mark_paid()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SHIPPED)


class StoreCreditTests(PaymentBase):
    def test_zero_total_orders_settle_on_store_credit(self):
        order = self.make_order(Decimal("0.00"))
        payment = charge_order(order)
        order.refresh_from_db()
        self.assertEqual(payment.provider, "credit")
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(order.status, Order.Status.PAID)

    def test_store_credit_refuses_a_nonzero_balance(self):
        order = self.make_order(Decimal("50.00"))
        result = StoreCreditBackend().charge(order, Decimal("50.00"))
        self.assertFalse(result.success)

    def test_fully_covered_checkout_is_paid_immediately(self):
        card = GiftCard.objects.create(initial_balance=Decimal("500.00"))
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.post(reverse("shop:apply_gift_card"), {"code": card.code})
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        order = Order.objects.get()
        self.assertEqual(order.grand_total, Decimal("0.00"))
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.payments.get().provider, "credit")


class StripeBackendTests(PaymentBase):
    def test_amounts_are_converted_to_cents_without_floats(self):
        self.assertEqual(StripeBackend.to_minor_units(Decimal("159.99")), 15999)
        self.assertEqual(StripeBackend.to_minor_units(Decimal("0.10")), 10)

    def test_missing_key_is_reported_not_crashed(self):
        backend = StripeBackend(secret_key="")
        result = backend.charge(self.make_order(), Decimal("159.00"))
        self.assertFalse(result.success)
        self.assertIn("STRIPE_SECRET_KEY", result.error_message)

    def test_successful_intent_requires_customer_action(self):
        backend = StripeBackend(secret_key="sk_test_x")
        fake = {"id": "pi_123", "client_secret": "pi_123_secret", "status": "requires_payment_method"}
        with patch.object(StripeBackend, "_request", return_value=fake):
            result = backend.charge(self.make_order(), Decimal("159.00"))
        self.assertTrue(result.success)
        self.assertEqual(result.status, Payment.Status.REQUIRES_ACTION)
        self.assertEqual(result.reference, "pi_123")
        self.assertEqual(result.client_secret, "pi_123_secret")

    def test_already_succeeded_intent_is_marked_paid(self):
        backend = StripeBackend(secret_key="sk_test_x")
        fake = {"id": "pi_9", "client_secret": "s", "status": "succeeded"}
        with patch.object(StripeBackend, "_request", return_value=fake):
            result = backend.charge(self.make_order(), Decimal("159.00"))
        self.assertEqual(result.status, Payment.Status.PAID)

    def test_api_errors_become_failed_results(self):
        backend = StripeBackend(secret_key="sk_test_x")
        with patch.object(StripeBackend, "_request", side_effect=StripeError("Card declined.")):
            result = backend.charge(self.make_order(), Decimal("159.00"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Card declined.")


class StripeWebhookTests(PaymentBase):
    SECRET = "whsec_test_secret"

    def setUp(self):
        super().setUp()
        self.order = self.make_order()
        self.payment = Payment.objects.create(
            order=self.order, provider="stripe", amount=Decimal("159.00"),
            reference="pi_abc", status=Payment.Status.REQUIRES_ACTION,
        )

    def signed(self, body, secret=None, timestamp=None):
        timestamp = timestamp or int(time.time())
        signed = f"{timestamp}.".encode() + body
        digest = hmac.new((secret or self.SECRET).encode(), signed, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    def post_event(self, event, **sig_kwargs):
        body = json.dumps(event).encode()
        return self.client.post(
            reverse("payments:webhook"), data=body, content_type="application/json",
            HTTP_STRIPE_SIGNATURE=self.signed(body, **sig_kwargs),
        )

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_valid_success_event_settles_the_order(self):
        response = self.post_event(
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_abc"}}}
        )
        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.status, Order.Status.PAID)

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_failure_event_records_the_error(self):
        self.post_event(
            {
                "type": "payment_intent.payment_failed",
                "data": {"object": {"id": "pi_abc", "last_payment_error": {"message": "Declined"}}},
            }
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.payment.error_message, "Declined")

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_a_forged_signature_is_rejected(self):
        response = self.post_event(
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_abc"}}},
            secret="whsec_wrong",
        )
        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_a_replayed_old_event_is_rejected(self):
        response = self.post_event(
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_abc"}}},
            timestamp=int(time.time()) - 3600,
        )
        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_event_for_an_unknown_payment_is_refused(self):
        response = self.post_event(
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_unknown"}}}
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(PAYMENT_BACKEND="stripe", STRIPE_WEBHOOK_SECRET=SECRET)
    def test_unrelated_events_are_acknowledged_without_changes(self):
        response = self.post_event(
            {"type": "charge.updated", "data": {"object": {"id": "pi_abc"}}}
        )
        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)

    def test_webhook_needs_no_csrf_token_but_still_needs_a_signature(self):
        response = self.client.post(
            reverse("payments:webhook"), data=b"{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class CheckoutPaymentFlowTests(PaymentBase):
    def test_checkout_creates_a_payment_record(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        order = Order.objects.get()
        self.assertEqual(order.payments.count(), 1)
        self.assertEqual(order.payments.get().amount, order.grand_total)

    @override_settings(PAYMENT_BACKEND="stripe")
    def test_card_checkout_redirects_to_the_payment_page(self):
        fake = {"id": "pi_1", "client_secret": "cs_1", "status": "requires_payment_method"}
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        with patch.object(StripeBackend, "_request", return_value=fake):
            response = self.client.post(reverse("shop:checkout"), CHECKOUT)
        order = Order.objects.get()
        self.assertRedirects(response, reverse("payments:pay", args=[order.number]))

    @override_settings(PAYMENT_BACKEND="stripe")
    def test_a_provider_failure_still_keeps_the_order(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        with patch.object(StripeBackend, "_request", side_effect=StripeError("boom")):
            response = self.client.post(reverse("shop:checkout"), CHECKOUT, follow=True)
        order = Order.objects.get()
        self.assertEqual(order.payments.get().status, Payment.Status.FAILED)
        self.assertContains(response, "couldn&#x27;t start the payment")

    def test_pay_page_is_private_to_the_ordering_session(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        order = Order.objects.get()
        other = self.client.__class__()
        response = other.get(reverse("payments:pay", args=[order.number]))
        self.assertRedirects(response, reverse("shop:order_lookup"))
