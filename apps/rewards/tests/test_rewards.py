from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Customer
from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import LiveSaleEvent, SiteSettings
from apps.rewards.models import (
    DiscountCode,
    DiscountRedemption,
    GiftCard,
    PointsTransaction,
    RewardsSettings,
    award_points,
    balance_for,
    redeem_points,
)
from apps.shop.models import Order
from apps.shop.pricing import quote

User = get_user_model()

CHECKOUT = {
    "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
    "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
    "state": "NC", "postal_code": "28401", "country": "United States",
    "accepts_livestock_terms": "on",
}


class RewardsBase(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.free_shipping_threshold = Decimal("299.00")
        site.livestock_shipping_rate = Decimal("59.00")
        site.tax_rate_percent = Decimal("0.00")
        site.save()

        self.rewards = RewardsSettings.load()
        self.user = User.objects.create_user(
            "sam@example.com", "sam@example.com", "reef-pass-19283"
        )
        self.customer = Customer.objects.create(user=self.user)
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=10,
        )

    def make_order(self, subtotal=Decimal("200.00")):
        return Order.objects.create(
            customer=self.customer, email="sam@example.com", first_name="Sam",
            last_name="Rivera", phone="555-0100", address_line1="12 Coral Way",
            city="Wilmington", state="NC", postal_code="28401", subtotal=subtotal,
        )


class PointsTests(RewardsBase):
    def test_points_are_earned_per_dollar_of_merchandise(self):
        order = self.make_order(Decimal("200.00"))
        award_points(self.customer, order)
        self.assertEqual(balance_for(self.customer), 200)

    def test_awarding_twice_for_one_order_is_a_no_op(self):
        order = self.make_order(Decimal("200.00"))
        award_points(self.customer, order)
        award_points(self.customer, order)
        self.assertEqual(balance_for(self.customer), 200)

    def test_expired_points_leave_the_balance(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=500,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(balance_for(self.customer), 0)

    def test_unexpired_points_count(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=500,
            expires_at=timezone.now() + timedelta(days=10),
        )
        self.assertEqual(balance_for(self.customer), 500)

    def test_award_sets_an_expiry_from_settings(self):
        order = self.make_order()
        row = award_points(self.customer, order)
        self.assertIsNotNone(row.expires_at)
        expected = timezone.now() + timedelta(days=self.rewards.expiry_days)
        self.assertAlmostEqual(row.expires_at, expected, delta=timedelta(minutes=1))

    def test_zero_expiry_days_means_points_never_expire(self):
        self.rewards.expiry_days = 0
        self.rewards.save()
        row = award_points(self.customer, self.make_order())
        self.assertIsNone(row.expires_at)

    def test_redeeming_more_than_the_balance_is_refused(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=50
        )
        with self.assertRaises(ValidationError):
            redeem_points(self.customer, 100)

    def test_redeeming_debits_the_balance(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=500
        )
        redeem_points(self.customer, 200)
        self.assertEqual(balance_for(self.customer), 300)

    def test_points_value_conversion(self):
        self.assertEqual(self.rewards.value_of(100), Decimal("5.00"))

    def test_disabled_programme_awards_nothing(self):
        self.rewards.is_enabled = False
        self.rewards.save()
        award_points(self.customer, self.make_order())
        self.assertEqual(balance_for(self.customer), 0)


class GiftCardTests(RewardsBase):
    def test_code_is_generated_and_balance_seeded(self):
        card = GiftCard.objects.create(initial_balance=Decimal("100.00"))
        self.assertTrue(card.code.startswith("RR-"))
        self.assertEqual(card.balance, Decimal("100.00"))

    def test_redeeming_draws_down_the_balance(self):
        card = GiftCard.objects.create(initial_balance=Decimal("100.00"))
        taken = card.redeem(Decimal("30.00"))
        card.refresh_from_db()
        self.assertEqual(taken, Decimal("30.00"))
        self.assertEqual(card.balance, Decimal("70.00"))

    def test_a_card_cannot_overdraw(self):
        card = GiftCard.objects.create(initial_balance=Decimal("25.00"))
        taken = card.redeem(Decimal("100.00"))
        card.refresh_from_db()
        self.assertEqual(taken, Decimal("25.00"))
        self.assertEqual(card.balance, Decimal("0.00"))

    def test_expired_card_is_not_redeemable(self):
        card = GiftCard.objects.create(
            initial_balance=Decimal("50.00"),
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(card.is_redeemable)
        self.assertEqual(card.redeem(Decimal("10.00")), Decimal("0.00"))

    def test_deactivated_card_is_not_redeemable(self):
        card = GiftCard.objects.create(initial_balance=Decimal("50.00"), is_active=False)
        self.assertFalse(card.is_redeemable)


class DiscountCodeTests(RewardsBase):
    def test_percentage_discount(self):
        code = DiscountCode.objects.create(code="reef10", kind=DiscountCode.Kind.PERCENT, value=10)
        self.assertEqual(code.code, "REEF10")  # normalised on save
        self.assertEqual(code.discount_for(Decimal("200.00")), Decimal("20.00"))

    def test_fixed_discount_cannot_exceed_the_subtotal(self):
        code = DiscountCode.objects.create(code="FIFTY", kind=DiscountCode.Kind.FIXED, value=50)
        self.assertEqual(code.discount_for(Decimal("30.00")), Decimal("30.00"))

    def test_percentage_above_100_is_invalid(self):
        code = DiscountCode(code="BAD", kind=DiscountCode.Kind.PERCENT, value=150)
        with self.assertRaises(ValidationError):
            code.clean()

    def test_minimum_subtotal_is_enforced(self):
        code = DiscountCode.objects.create(
            code="BIG", kind=DiscountCode.Kind.PERCENT, value=10,
            minimum_subtotal=Decimal("300.00"),
        )
        ok, message = code.check_usable(Decimal("100.00"))
        self.assertFalse(ok)
        self.assertIn("300", message)

    def test_expired_code_is_not_live(self):
        code = DiscountCode.objects.create(
            code="OLD", value=10, ends_at=timezone.now() - timedelta(days=1)
        )
        self.assertFalse(code.is_live)

    def test_exhausted_code_is_not_live(self):
        code = DiscountCode.objects.create(code="ONCE", value=10, max_uses=1, times_used=1)
        self.assertFalse(code.is_live)

    def test_per_customer_limit(self):
        code = DiscountCode.objects.create(code="ONEPER", value=10, max_uses_per_customer=1)
        DiscountRedemption.objects.create(code=code, customer=self.customer)
        ok, message = code.check_usable(Decimal("100.00"), customer=self.customer)
        self.assertFalse(ok)
        self.assertIn("already used", message)


class PricingTests(RewardsBase):
    def test_credits_stack_in_order(self):
        code = DiscountCode.objects.create(code="TEN", kind=DiscountCode.Kind.PERCENT, value=10)
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=200
        )
        card = GiftCard.objects.create(initial_balance=Decimal("20.00"))

        totals = quote(
            Decimal("100.00"),
            contains_livestock=True,
            discount_code=code,
            points=200,
            gift_cards=[card],
            customer=self.customer,
        )
        # 100 - 10 discount + 59 shipping = 149; minus $10 of points = 139;
        # minus $20 gift card = 119.
        self.assertEqual(totals.discount_total, Decimal("10.00"))
        self.assertEqual(totals.points_value, Decimal("10.00"))
        self.assertEqual(totals.gift_card_total, Decimal("20.00"))
        self.assertEqual(totals.grand_total, Decimal("119.00"))

    def test_free_shipping_code_zeroes_shipping_not_goods(self):
        code = DiscountCode.objects.create(
            code="FREESHIP", kind=DiscountCode.Kind.FREE_SHIPPING
        )
        totals = quote(Decimal("100.00"), contains_livestock=True, discount_code=code)
        self.assertEqual(totals.shipping_total, Decimal("0.00"))
        self.assertEqual(totals.discount_total, Decimal("0.00"))
        self.assertEqual(totals.grand_total, Decimal("100.00"))

    def test_tax_is_charged_on_the_discounted_goods(self):
        site = SiteSettings.load()
        site.tax_rate_percent = Decimal("10.00")
        site.save()
        code = DiscountCode.objects.create(code="TEN", kind=DiscountCode.Kind.PERCENT, value=10)
        totals = quote(Decimal("100.00"), discount_code=code)
        self.assertEqual(totals.tax_total, Decimal("9.00"))

    def test_credits_never_push_the_total_below_zero(self):
        card = GiftCard.objects.create(initial_balance=Decimal("500.00"))
        totals = quote(Decimal("50.00"), gift_cards=[card])
        self.assertEqual(totals.grand_total, Decimal("0.00"))
        self.assertTrue(totals.is_fully_covered)
        # Gift cards are money: the card covers the $12 dry-goods shipping too,
        # and only draws what the order actually needed.
        self.assertEqual(totals.gift_card_total, Decimal("62.00"))

    def test_a_gift_card_only_draws_what_the_order_needs(self):
        card = GiftCard.objects.create(initial_balance=Decimal("500.00"))
        totals = quote(Decimal("50.00"), gift_cards=[card])
        allocated = sum(amount for _, amount in totals.gift_card_allocations)
        self.assertEqual(allocated, Decimal("62.00"))

    def test_gift_cards_are_drawn_in_order_until_the_total_is_met(self):
        small = GiftCard.objects.create(initial_balance=Decimal("20.00"))
        large = GiftCard.objects.create(initial_balance=Decimal("500.00"))
        totals = quote(Decimal("50.00"), gift_cards=[small, large])
        self.assertEqual(totals.gift_card_total, Decimal("62.00"))
        self.assertEqual(
            [amount for _, amount in totals.gift_card_allocations],
            [Decimal("20.00"), Decimal("42.00")],
        )

    def test_points_below_the_minimum_are_ignored(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=50
        )
        totals = quote(Decimal("100.00"), points=50, customer=self.customer)
        self.assertEqual(totals.points_value, Decimal("0.00"))

    def test_points_are_capped_by_the_balance(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=100
        )
        totals = quote(Decimal("100.00"), points=99999, customer=self.customer)
        self.assertEqual(totals.points_value, Decimal("5.00"))


class CheckoutCreditTests(RewardsBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})

    def test_applying_a_discount_code_reduces_the_order(self):
        DiscountCode.objects.create(code="REEF10", kind=DiscountCode.Kind.PERCENT, value=10)
        self.client.post(reverse("shop:apply_discount"), {"code": "reef10"})
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        order = Order.objects.get()
        self.assertEqual(order.subtotal, Decimal("200.00"))
        self.assertEqual(order.discount_total, Decimal("20.00"))
        self.assertEqual(order.grand_total, Decimal("239.00"))  # 180 + 59 shipping
        self.assertEqual(order.discount_code.code, "REEF10")

    def test_unknown_code_is_rejected(self):
        response = self.client.post(reverse("shop:apply_discount"), {"code": "NOPE"}, follow=True)
        self.assertContains(response, "don&#x27;t recognise that code")

    def test_discount_records_a_redemption_and_increments_usage(self):
        code = DiscountCode.objects.create(code="REEF10", kind=DiscountCode.Kind.PERCENT, value=10)
        self.client.post(reverse("shop:apply_discount"), {"code": "REEF10"})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        code.refresh_from_db()
        self.assertEqual(code.times_used, 1)
        self.assertEqual(DiscountRedemption.objects.count(), 1)

    def test_points_are_spent_and_debited(self):
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=400
        )
        self.client.post(reverse("shop:apply_points"), {"points": "400"})
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        order = Order.objects.get()
        self.assertEqual(order.points_redeemed, 400)
        self.assertEqual(order.points_value, Decimal("20.00"))
        # 400 spent, then 200 earned on the $200 of merchandise.
        self.assertEqual(balance_for(self.customer), 200)

    def test_points_cannot_be_spent_during_a_live_sale(self):
        LiveSaleEvent.objects.create(
            title="Flash sale",
            starts_at=timezone.now() - timedelta(minutes=5),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        PointsTransaction.objects.create(
            customer=self.customer, kind=PointsTransaction.Kind.EARNED, points=400
        )
        response = self.client.post(reverse("shop:apply_points"), {"points": "400"}, follow=True)
        self.assertContains(response, "cannot be redeemed during a live sale")
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        self.assertEqual(Order.objects.get().points_redeemed, 0)

    def test_points_are_still_earned_during_a_live_sale(self):
        LiveSaleEvent.objects.create(
            title="Flash sale",
            starts_at=timezone.now() - timedelta(minutes=5),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        self.assertEqual(balance_for(self.customer), 200)

    def test_gift_card_covers_the_balance_and_is_drawn_down(self):
        card = GiftCard.objects.create(initial_balance=Decimal("300.00"))
        self.client.post(reverse("shop:apply_gift_card"), {"code": card.code})
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        order = Order.objects.get()
        card.refresh_from_db()
        self.assertEqual(order.gift_card_total, Decimal("259.00"))
        self.assertEqual(order.grand_total, Decimal("0.00"))
        self.assertEqual(card.balance, Decimal("41.00"))

    def test_credits_are_cleared_after_the_order(self):
        DiscountCode.objects.create(code="REEF10", kind=DiscountCode.Kind.PERCENT, value=10)
        self.client.post(reverse("shop:apply_discount"), {"code": "REEF10"})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        self.assertNotIn("checkout_discount", self.client.session)

    def test_guest_cannot_apply_points(self):
        self.client.logout()
        response = self.client.post(reverse("shop:apply_points"), {"points": "400"}, follow=True)
        self.assertContains(response, "Sign in to spend reward points")
