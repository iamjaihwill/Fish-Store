from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Customer
from apps.catalog.models import Category, Product, ProductType, ProductVariant
from apps.cms.models import SiteSettings
from apps.notifications.models import AbandonedCart, EmailLog, EmailTemplate
from apps.notifications.senders import send_order_confirmation, send_welcome
from apps.notifications.services import capture_cart, send_transactional
from apps.shop.models import DoaClaim, Order

User = get_user_model()

CHECKOUT = {
    "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
    "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
    "state": "NC", "postal_code": "28401", "country": "United States",
    "accepts_livestock_terms": "on",
}


class NotificationBase(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.free_shipping_threshold = Decimal("999.00")
        site.livestock_shipping_rate = Decimal("59.00")
        site.tax_rate_percent = Decimal("0.00")
        site.save()
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=10,
        )
        mail.outbox = []

    def make_order(self, **kwargs):
        defaults = dict(
            email="sam@example.com", first_name="Sam", last_name="Rivera",
            phone="555-0100", address_line1="12 Coral Way", city="Wilmington",
            state="NC", postal_code="28401", subtotal=Decimal("100.00"),
            grand_total=Decimal("159.00"),
        )
        defaults.update(kwargs)
        return Order.objects.create(**defaults)


class TemplateResolutionTests(NotificationBase):
    def test_built_in_template_is_used_when_no_row_exists(self):
        subject, body, enabled = EmailTemplate.resolve("order_confirmation")
        self.assertTrue(enabled)
        self.assertIn("{{ order.number }}", subject)

    def test_a_database_row_overrides_the_built_in(self):
        EmailTemplate.objects.create(
            key="order_confirmation", subject="Custom {{ order.number }}", body="Hi."
        )
        subject, body, _ = EmailTemplate.resolve("order_confirmation")
        self.assertEqual(subject, "Custom {{ order.number }}")
        self.assertEqual(body, "Hi.")

    def test_deactivating_a_template_stops_the_email(self):
        EmailTemplate.objects.create(
            key="order_confirmation", subject="x", body="y", is_active=False
        )
        send_order_confirmation(self.make_order())
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_key_sends_nothing_rather_than_raising(self):
        self.assertIsNone(send_transactional("not_a_real_template", "a@example.com"))
        self.assertEqual(len(mail.outbox), 0)

    def test_seed_defaults_is_idempotent(self):
        first = EmailTemplate.seed_defaults()
        second = EmailTemplate.seed_defaults()
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)

    def test_reset_restores_the_built_in_wording(self):
        EmailTemplate.seed_defaults()
        row = EmailTemplate.objects.get(key="welcome")
        row.subject = "Changed"
        row.save()
        row.reset_to_default()
        row.refresh_from_db()
        self.assertNotEqual(row.subject, "Changed")

    def test_plain_text_is_not_html_escaped(self):
        """An apostrophe must not arrive as &#x27; in someone's inbox."""
        EmailTemplate.objects.create(
            key="welcome", subject="Hi", body="Here's your {{ first_name }} coral"
        )
        user = User.objects.create_user("a@example.com", "a@example.com", "pw-192837", first_name="Dana")
        send_welcome(Customer.objects.create(user=user))
        self.assertIn("Here's your Dana coral", mail.outbox[0].body)
        self.assertNotIn("&#x27;", mail.outbox[0].body)


class DeduplicationTests(NotificationBase):
    def test_the_same_email_is_not_sent_twice(self):
        order = self.make_order()
        send_order_confirmation(order)
        send_order_confirmation(order)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailLog.objects.filter(key="order_confirmation").count(), 1)

    def test_different_orders_each_get_their_own_email(self):
        send_order_confirmation(self.make_order())
        send_order_confirmation(self.make_order())
        self.assertEqual(len(mail.outbox), 2)

    def test_a_failed_send_does_not_block_a_retry(self):
        order = self.make_order()
        EmailLog.objects.create(
            key="order_confirmation", recipient=order.email,
            dedupe_key=f"order_confirmation:{order.pk}",
            status=EmailLog.Status.FAILED,
        )
        send_order_confirmation(order)
        self.assertEqual(len(mail.outbox), 1)

    def test_blank_recipient_sends_nothing(self):
        self.assertIsNone(send_transactional("welcome", ""))
        self.assertEqual(len(mail.outbox), 0)

    def test_every_send_is_logged_with_its_body(self):
        order = self.make_order()
        order.items.create(
            product=self.product, name="Torch",
            unit_price=Decimal("100.00"), quantity=2,
        )
        send_order_confirmation(order)

        log = EmailLog.objects.get()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.order, order)
        self.assertEqual(log.recipient, order.email)
        self.assertIn("2 x Torch", log.body)


class LifecycleEmailTests(NotificationBase):
    def test_registration_sends_a_welcome(self):
        self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Dana", "last_name": "Reef", "email": "dana@example.com",
                "password1": "reef-keeper-91827", "password2": "reef-keeper-91827",
            },
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Welcome", mail.outbox[0].subject)

    def test_checkout_sends_a_confirmation(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any(Order.objects.get().number in s for s in subjects))

    def test_shipping_an_order_emails_tracking(self):
        order = self.make_order(contains_livestock=True)
        order.mark_shipped(carrier="FedEx", tracking_number="123456789")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("on the way", mail.outbox[0].subject)
        self.assertIn("123456789", mail.outbox[0].body)

    def test_reshipping_with_the_same_tracking_does_not_email_twice(self):
        order = self.make_order()
        order.mark_shipped(carrier="FedEx", tracking_number="123456789")
        order.mark_shipped(carrier="FedEx", tracking_number="123456789")
        self.assertEqual(len(mail.outbox), 1)

    def test_a_corrected_tracking_number_does_email_again(self):
        order = self.make_order()
        order.mark_shipped(carrier="FedEx", tracking_number="111")
        order.mark_shipped(carrier="FedEx", tracking_number="222")
        self.assertEqual(len(mail.outbox), 2)

    def test_delivery_opens_the_claim_window_and_emails(self):
        order = self.make_order(contains_livestock=True)
        order.mark_delivered()
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("8 hour", mail.outbox[0].subject)
        self.assertIn(reverse("shop:doa_claim", args=[order.number]), mail.outbox[0].body)

    def test_payment_settling_emails_a_receipt(self):
        from apps.payments.models import Payment

        order = self.make_order()
        payment = Payment.objects.create(
            order=order, provider="stripe", amount=Decimal("159.00")
        )
        payment.mark_paid(reference="pi_1")
        self.assertTrue(any("Payment received" in m.subject for m in mail.outbox))

    def test_doa_claim_is_acknowledged(self):
        order = self.make_order(contains_livestock=True, delivered_at=timezone.now())
        session = self.client.session
        session["recent_orders"] = [order.number]
        session.save()
        self.client.post(
            reverse("shop:doa_claim", args=[order.number]),
            {"items_affected": "One torch", "details": "Arrived closed and melting."},
        )
        self.assertEqual(DoaClaim.objects.count(), 1)
        self.assertTrue(any("arrival claim" in m.subject for m in mail.outbox))


class AbandonedCartCaptureTests(NotificationBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            "sam@example.com", "sam@example.com", "reef-pass-19283", first_name="Sam"
        )
        self.customer = Customer.objects.create(user=self.user)

    def test_a_signed_in_visitors_cart_is_captured(self):
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})
        self.client.get(reverse("shop:cart"))

        cart = AbandonedCart.objects.get()
        self.assertEqual(cart.email, "sam@example.com")
        self.assertEqual(cart.item_count, 2)
        self.assertEqual(cart.subtotal, Decimal("200.00"))

    def test_anonymous_visitors_leave_nothing_behind(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.get(reverse("shop:cart"))
        self.assertEqual(AbandonedCart.objects.count(), 0)

    def test_emptying_the_cart_removes_the_stored_copy(self):
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.get(reverse("shop:cart"))
        self.assertEqual(AbandonedCart.objects.count(), 1)

        self.client.post(
            reverse("shop:remove_from_cart", args=[self.product.slug]),
            {"next": reverse("shop:cart")},
        )
        self.client.get(reverse("shop:cart"))
        self.assertEqual(AbandonedCart.objects.count(), 0)

    def test_wysiwyg_carts_are_flagged(self):
        wysiwyg = Product.objects.create(
            name="One Off", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("300.00"), status=Product.Status.ACTIVE,
            stock_quantity=1, is_wysiwyg=True,
        )
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[wysiwyg.slug]), {"quantity": 1})
        self.client.get(reverse("shop:cart"))
        self.assertTrue(AbandonedCart.objects.get().contains_wysiwyg)

    def test_completing_the_order_marks_the_cart_recovered(self):
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.get(reverse("shop:cart"))
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        cart = AbandonedCart.objects.get()
        self.assertTrue(cart.is_recovered)
        self.assertEqual(cart.placed_order, Order.objects.get())

    def test_one_open_cart_per_email(self):
        self.client.force_login(self.user)
        for _ in range(3):
            self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
            self.client.get(reverse("shop:cart"))
        self.assertEqual(AbandonedCart.objects.count(), 1)


class AbandonedCartReminderTests(NotificationBase):
    def setUp(self):
        super().setUp()
        self.cart = AbandonedCart.objects.create(
            email="sam@example.com",
            items=[{"product_id": self.product.pk, "variant_id": None,
                    "name": "Torch", "slug": self.product.slug,
                    "quantity": 1, "price": "100.00"}],
            subtotal=Decimal("100.00"),
        )

    def age(self, hours):
        """Wind the clock back on the whole row.

        Both timestamps have to move: the next reminder is due a gap after the
        previous reminder, not just after the last cart change.
        """
        moment = timezone.now() - timedelta(hours=hours)
        updates = {"updated_at": moment}
        if self.cart.last_reminder_at is not None:
            updates["last_reminder_at"] = moment
        AbandonedCart.objects.filter(pk=self.cart.pk).update(**updates)
        self.cart.refresh_from_db()

    def run_command(self, **kwargs):
        call_command("send_abandoned_cart_emails", stdout=StringIO(), **kwargs)

    def test_a_fresh_cart_is_left_alone(self):
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_an_aged_cart_gets_a_reminder(self):
        self.age(8)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.reminders_sent, 1)

    def test_reminders_stop_at_the_configured_maximum(self):
        for _ in range(4):
            self.age(8)
            self.run_command(max_reminders=2)
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.reminders_sent, 2)
        self.assertEqual(len(mail.outbox), 2)

    def test_a_recovered_cart_is_never_chased(self):
        self.age(8)
        self.cart.mark_recovered()
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_sends_nothing_and_records_nothing(self):
        self.age(8)
        self.run_command(dry_run=True)
        self.assertEqual(len(mail.outbox), 0)
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.reminders_sent, 0)

    def test_recording_a_reminder_does_not_reset_the_clock(self):
        """updated_at must not move, or the next reminder never becomes due."""
        self.age(8)
        before = self.cart.updated_at
        self.cart.record_reminder()
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.updated_at, before)

    def test_the_second_reminder_waits_for_the_gap_after_the_first(self):
        self.age(8)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

        # Cart untouched since, but not enough time has passed since reminder one.
        AbandonedCart.objects.filter(pk=self.cart.pk).update(
            updated_at=timezone.now() - timedelta(hours=20)
        )
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_the_email_contains_a_working_recovery_link(self):
        self.age(8)
        self.run_command()
        self.assertIn(self.cart.get_recovery_url(), mail.outbox[0].body)


class CartRecoveryTests(NotificationBase):
    def setUp(self):
        super().setUp()
        self.variant_product = Product.objects.create(
            name="Hammer", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("90.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        self.variant = ProductVariant.objects.create(
            product=self.variant_product, name="Single head",
            price=Decimal("120.00"), stock_quantity=3, is_default=True,
        )

    def make_cart(self, items):
        return AbandonedCart.objects.create(
            email="sam@example.com", items=items, subtotal=Decimal("100.00")
        )

    def test_recovery_restores_the_cart(self):
        cart = self.make_cart([
            {"product_id": self.product.pk, "variant_id": None, "name": "Torch",
             "slug": self.product.slug, "quantity": 2, "price": "100.00"}
        ])
        response = self.client.get(cart.get_recovery_url())
        self.assertRedirects(response, reverse("shop:cart"))
        self.assertEqual(len(self.client.get(reverse("shop:cart")).context["cart"]), 2)

    def test_recovery_restores_the_right_variant(self):
        cart = self.make_cart([
            {"product_id": self.variant_product.pk, "variant_id": self.variant.pk,
             "name": "Hammer (Single head)", "slug": self.variant_product.slug,
             "quantity": 1, "price": "120.00"}
        ])
        self.client.get(cart.get_recovery_url())
        line = self.client.get(reverse("shop:cart")).context["cart"].lines[0]
        self.assertEqual(line.variant, self.variant)
        self.assertEqual(line.unit_price, Decimal("120.00"))

    def test_sold_out_items_are_skipped_with_a_warning(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        cart = self.make_cart([
            {"product_id": self.product.pk, "variant_id": None, "name": "Torch",
             "slug": self.product.slug, "quantity": 1, "price": "100.00"}
        ])
        response = self.client.get(cart.get_recovery_url(), follow=True)
        self.assertContains(response, "has sold")

    def test_partially_available_cart_restores_what_is_left(self):
        gone = Product.objects.create(
            name="Gone", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("50.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        cart = self.make_cart([
            {"product_id": self.product.pk, "variant_id": None, "name": "Torch",
             "slug": self.product.slug, "quantity": 1, "price": "100.00"},
            {"product_id": gone.pk, "variant_id": None, "name": "Gone",
             "slug": gone.slug, "quantity": 1, "price": "50.00"},
        ])
        response = self.client.get(cart.get_recovery_url(), follow=True)
        self.assertContains(response, "sold out while you were away")
        self.assertEqual(len(self.client.get(reverse("shop:cart")).context["cart"]), 1)

    def test_an_unknown_token_is_404(self):
        self.assertEqual(self.client.get(
            reverse("notifications:recover_cart", args=["nope"])
        ).status_code, 404)

    def test_an_already_recovered_cart_redirects_to_the_shop(self):
        cart = self.make_cart([])
        cart.mark_recovered()
        response = self.client.get(cart.get_recovery_url())
        self.assertRedirects(response, reverse("catalog:shop"))

    def test_recovery_does_not_sign_anyone_in(self):
        user = User.objects.create_user("sam@example.com", "sam@example.com", "pw-192837")
        Customer.objects.create(user=user)
        cart = self.make_cart([
            {"product_id": self.product.pk, "variant_id": None, "name": "Torch",
             "slug": self.product.slug, "quantity": 1, "price": "100.00"}
        ])
        self.client.get(cart.get_recovery_url())
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 302)


class ReviewRequestTests(NotificationBase):
    def make_delivered_order(self, days_ago):
        order = self.make_order(
            status=Order.Status.DELIVERED,
            delivered_at=timezone.now() - timedelta(days=days_ago),
        )
        order.items.create(
            product=self.product, name="Torch",
            unit_price=Decimal("100.00"), quantity=1,
        )
        return order

    def run_command(self, **kwargs):
        call_command("send_review_requests", stdout=StringIO(), **kwargs)

    def test_recent_deliveries_are_not_asked_yet(self):
        self.make_delivered_order(days_ago=2)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_settled_orders_are_asked(self):
        self.make_delivered_order(days_ago=20)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("settle in", mail.outbox[0].subject)

    def test_a_customer_is_only_asked_once(self):
        self.make_delivered_order(days_ago=20)
        self.run_command()
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_undelivered_orders_are_skipped(self):
        self.make_order(status=Order.Status.SHIPPED)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)


class PointsExpiryReminderTests(NotificationBase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user("sam@example.com", "sam@example.com", "pw-192837")
        self.customer = Customer.objects.create(user=user)

    def award(self, points, expires_in_days):
        from apps.rewards.models import PointsTransaction

        return PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED,
            points=points, expires_at=timezone.now() + timedelta(days=expires_in_days),
        )

    def run_command(self, **kwargs):
        call_command("send_points_expiry_reminders", stdout=StringIO(), **kwargs)

    def test_points_expiring_soon_trigger_a_warning(self):
        self.award(500, expires_in_days=7)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("500 reward points expire soon", mail.outbox[0].subject)

    def test_points_expiring_later_are_left_alone(self):
        self.award(500, expires_in_days=90)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_a_customer_is_warned_once_per_expiry_date(self):
        self.award(500, expires_in_days=7)
        self.run_command()
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_nothing_is_sent_when_points_do_not_expire(self):
        from apps.rewards.models import RewardsSettings

        rewards = RewardsSettings.load()
        rewards.expiry_days = 0
        rewards.save()
        self.award(500, expires_in_days=7)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)


class DeploymentCheckTests(TestCase):
    """The relative-link footgun must not be discoverable only in production."""

    @override_settings(DEBUG=False, SITE_BASE_URL="")
    def test_missing_base_url_is_flagged_in_production(self):
        from apps.notifications.checks import check_site_base_url

        warnings = check_site_base_url(None)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "notifications.W001")

    @override_settings(DEBUG=False, SITE_BASE_URL="https://shop.example.com")
    def test_configured_base_url_passes(self):
        from apps.notifications.checks import check_site_base_url

        self.assertEqual(check_site_base_url(None), [])

    @override_settings(DEBUG=True, SITE_BASE_URL="")
    def test_development_is_not_nagged(self):
        from apps.notifications.checks import check_site_base_url

        self.assertEqual(check_site_base_url(None), [])

    @override_settings(SITE_BASE_URL="https://shop.example.com")
    def test_email_links_are_absolute_when_configured(self):
        from apps.notifications.services import absolute_url

        self.assertEqual(
            absolute_url("/cart/recover/abc/"),
            "https://shop.example.com/cart/recover/abc/",
        )
