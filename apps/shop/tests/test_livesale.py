from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Customer
from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import SiteSettings
from apps.shop.additions import CannotAddToOrder, add_to_order
from apps.shop.cart import Cart
from apps.shop.models import Order
from apps.shop.tests.test_cart import request_with_session

User = get_user_model()

CHECKOUT = {
    "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
    "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
    "state": "NC", "postal_code": "28401", "country": "United States",
    "accepts_livestock_terms": "on",
}


class ShippingCalendarTests(TestCase):
    def setUp(self):
        self.site = SiteSettings.load()
        self.site.shipping_weekdays = "0,1,2"  # Mon, Tue, Wed
        self.site.shipping_cutoff_time = time(14, 0)
        self.site.save()

    def at(self, year, month, day, hour, minute=0):
        return timezone.make_aware(datetime(year, month, day, hour, minute))

    def test_before_cutoff_on_a_ship_day_goes_out_today(self):
        # Monday 2026-09-14 at 10am
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 14, 10)), date(2026, 9, 14)
        )

    def test_after_cutoff_rolls_to_the_next_ship_day(self):
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 14, 15)), date(2026, 9, 15)
        )

    def test_exactly_at_the_cutoff_is_too_late(self):
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 14, 14)), date(2026, 9, 15)
        )

    def test_weekend_orders_wait_for_monday(self):
        # Saturday 2026-09-19
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 19, 9)), date(2026, 9, 21)
        )

    def test_after_cutoff_wednesday_skips_to_monday(self):
        # Wednesday 2026-09-16 at 4pm -> next ship day is Monday the 21st
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 16, 16)), date(2026, 9, 21)
        )

    def test_custom_ship_days_are_respected(self):
        self.site.shipping_weekdays = "3"  # Thursdays only
        self.site.save()
        self.assertEqual(
            self.site.next_ship_date(self.at(2026, 9, 14, 9)), date(2026, 9, 17)
        )

    def test_malformed_weekday_config_falls_back(self):
        self.site.shipping_weekdays = "banana,9"
        self.site.save()
        self.assertEqual(self.site.shipping_weekday_numbers, [0, 1, 2])


class ShipDateValidationTests(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.shipping_weekdays = "0,1,2"
        site.save()
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=5,
        )
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})

    def next_weekday(self, weekday):
        day = timezone.localdate() + timedelta(days=1)
        while day.weekday() != weekday:
            day += timedelta(days=1)
        return day

    def test_a_non_shipping_day_is_rejected(self):
        saturday = self.next_weekday(5)
        response = self.client.post(
            reverse("shop:checkout"),
            dict(CHECKOUT, requested_ship_date=saturday.isoformat()),
        )
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn("requested_ship_date", response.context["form"].errors)

    def test_a_shipping_day_is_accepted(self):
        monday = self.next_weekday(0)
        self.client.post(
            reverse("shop:checkout"),
            dict(CHECKOUT, requested_ship_date=monday.isoformat()),
        )
        self.assertEqual(Order.objects.get().requested_ship_date, monday)


class AddToExistingOrderTests(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.free_shipping_threshold = Decimal("999.00")
        site.livestock_shipping_rate = Decimal("59.00")
        site.tax_rate_percent = Decimal("0.00")
        site.save()
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.first = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=5,
        )
        self.second = Product.objects.create(
            name="Hammer", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("80.00"), status=Product.Status.ACTIVE, stock_quantity=5,
        )

    def place_first_order(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.first.slug]), {"quantity": 1})
        self.client.post(reverse("shop:checkout"), CHECKOUT)
        return Order.objects.get()

    def test_adding_does_not_charge_shipping_twice(self):
        order = self.place_first_order()
        self.assertEqual(order.shipping_total, Decimal("59.00"))
        self.assertEqual(order.grand_total, Decimal("159.00"))

        self.client.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 1})
        self.client.post(reverse("shop:add_to_existing"), {"order": order.number})

        order.refresh_from_db()
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.subtotal, Decimal("180.00"))
        self.assertEqual(order.shipping_total, Decimal("59.00"))
        self.assertEqual(order.grand_total, Decimal("239.00"))

    def test_adding_decrements_stock(self):
        order = self.place_first_order()
        self.client.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 2})
        self.client.post(reverse("shop:add_to_existing"), {"order": order.number})
        self.second.refresh_from_db()
        self.assertEqual(self.second.stock_quantity, 3)

    def test_the_cart_is_emptied_after_adding(self):
        order = self.place_first_order()
        self.client.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 1})
        self.client.post(reverse("shop:add_to_existing"), {"order": order.number})
        cart_page = self.client.get(reverse("shop:cart"))
        self.assertTrue(cart_page.context["cart"].is_empty)

    def test_a_shipped_order_refuses_additions(self):
        order = self.place_first_order()
        order.mark_shipped()
        self.assertFalse(order.accepts_additions)

        self.client.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 1})
        response = self.client.post(
            reverse("shop:add_to_existing"), {"order": order.number}, follow=True
        )
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 1)
        self.assertContains(response, "couldn&#x27;t find that open order")

    def test_cannot_add_to_someone_elses_order(self):
        order = self.place_first_order()
        other = self.client.__class__()
        other.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 1})
        response = other.post(
            reverse("shop:add_to_existing"), {"order": order.number}, follow=True
        )
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 1)
        self.assertContains(response, "couldn&#x27;t find that open order")

    def test_adding_an_empty_cart_is_refused(self):
        order = self.place_first_order()
        request = request_with_session()
        with self.assertRaises(CannotAddToOrder):
            add_to_order(order, Cart(request))

    def test_disabling_the_feature_closes_the_door(self):
        order = self.place_first_order()
        site = SiteSettings.load()
        site.allow_order_additions = False
        site.save()
        self.assertFalse(order.accepts_additions)

    def test_cart_page_offers_the_option_when_an_order_is_open(self):
        order = self.place_first_order()
        self.client.post(reverse("shop:add_to_cart", args=[self.second.slug]), {"quantity": 1})
        response = self.client.get(reverse("shop:cart"))
        self.assertContains(response, f"Add to order {order.number}")


class WholesalePricingTests(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.wholesale_discount_percent = Decimal("30.00")
        site.free_shipping_threshold = Decimal("999.00")
        site.livestock_shipping_rate = Decimal("59.00")
        site.tax_rate_percent = Decimal("0.00")
        site.save()
        self.user = User.objects.create_user("shop@example.com", "shop@example.com", "pw-192837")
        self.customer = Customer.objects.create(user=self.user)
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=10,
        )

    def approve_wholesale(self):
        self.customer.tier = Customer.Tier.WHOLESALE
        self.customer.wholesale_approved_at = timezone.now()
        self.customer.save()

    def test_retail_customers_pay_list_price(self):
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.subtotal, Decimal("200.00"))

    def test_approved_wholesale_gets_trade_pricing_in_the_cart(self):
        self.approve_wholesale()
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.retail_subtotal, Decimal("200.00"))
        self.assertEqual(cart.subtotal, Decimal("140.00"))
        self.assertEqual(cart.wholesale_savings, Decimal("60.00"))

    def test_pending_wholesale_does_not_get_the_discount(self):
        self.customer.tier = Customer.Tier.WHOLESALE  # not approved
        self.customer.save()
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.subtotal, Decimal("200.00"))

    def test_wholesale_pricing_carries_into_the_order(self):
        self.approve_wholesale()
        self.client.force_login(self.user)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 2})
        self.client.post(reverse("shop:checkout"), CHECKOUT)

        order = Order.objects.get()
        self.assertEqual(order.items.get().unit_price, Decimal("70.00"))
        self.assertEqual(order.subtotal, Decimal("140.00"))
