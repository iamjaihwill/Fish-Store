from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import SiteSettings
from apps.shop.models import Order
from apps.shop.services import OutOfStock, place_order
from apps.shop.tests.test_cart import request_with_session
from apps.shop.cart import Cart

VALID_DETAILS = {
    "email": "reefer@example.com",
    "first_name": "Sam",
    "last_name": "Rivera",
    "phone": "555-0100",
    "address_line1": "12 Coral Way",
    "address_line2": "",
    "city": "Wilmington",
    "state": "NC",
    "postal_code": "28401",
    "country": "United States",
    "hold_for_weather": True,
    "customer_notes": "Please double-bag the torch.",
}


class PlaceOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        settings_obj = SiteSettings.load()
        settings_obj.free_shipping_threshold = Decimal("299.00")
        settings_obj.livestock_shipping_rate = Decimal("59.00")
        settings_obj.tax_rate_percent = Decimal("0.00")
        settings_obj.save()

    def setUp(self):
        self.coral = Product.objects.create(
            name="Torch", category=self.corals, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=3,
        )
        self.cart = Cart(request_with_session())

    def test_order_totals_and_stock_decrement(self):
        self.cart.add(self.coral, 2)
        order = place_order(self.cart, dict(VALID_DETAILS))

        self.assertEqual(order.subtotal, Decimal("200.00"))
        self.assertEqual(order.shipping_total, Decimal("59.00"))
        self.assertEqual(order.grand_total, Decimal("259.00"))
        self.assertTrue(order.contains_livestock)
        self.assertEqual(order.status, Order.Status.PENDING)

        self.coral.refresh_from_db()
        self.assertEqual(self.coral.stock_quantity, 1)
        self.assertTrue(self.cart.is_empty)

    def test_order_number_is_unique_and_prefixed(self):
        self.cart.add(self.coral, 1)
        first = place_order(self.cart, dict(VALID_DETAILS))
        self.cart.add(self.coral, 1)
        second = place_order(self.cart, dict(VALID_DETAILS))
        self.assertTrue(first.number.startswith("RR-"))
        self.assertNotEqual(first.number, second.number)

    def test_line_items_snapshot_name_and_price(self):
        self.cart.add(self.coral, 1)
        order = place_order(self.cart, dict(VALID_DETAILS))
        item = order.items.get()
        self.assertEqual(item.name, "Torch")
        self.assertEqual(item.unit_price, Decimal("100.00"))
        self.assertTrue(item.is_livestock)

        # Renaming the catalog product does not rewrite order history.
        self.coral.name = "Renamed Torch"
        self.coral.save()
        item.refresh_from_db()
        self.assertEqual(item.name, "Torch")

    def test_free_shipping_threshold_applies(self):
        self.cart.add(self.coral, 3)  # $300 > $299
        order = place_order(self.cart, dict(VALID_DETAILS))
        self.assertEqual(order.shipping_total, Decimal("0.00"))

    def test_out_of_stock_aborts_the_whole_order(self):
        self.cart.add(self.coral, 3)
        # Someone else buys the stock between the cart page and the submit.
        Product.objects.filter(pk=self.coral.pk).update(stock_quantity=1)

        with self.assertRaises(OutOfStock):
            place_order(self.cart, dict(VALID_DETAILS))

        self.assertEqual(Order.objects.count(), 0)
        self.coral.refresh_from_db()
        self.assertEqual(self.coral.stock_quantity, 1)

    def test_empty_cart_is_rejected(self):
        with self.assertRaises(ValueError):
            place_order(self.cart, dict(VALID_DETAILS))

    def test_restock_returns_inventory(self):
        self.cart.add(self.coral, 2)
        order = place_order(self.cart, dict(VALID_DETAILS))
        order.restock()
        self.coral.refresh_from_db()
        self.assertEqual(self.coral.stock_quantity, 3)


class CheckoutFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.gear = Category.objects.create(name="Gear", product_type=ProductType.DRY_GOODS)
        cls.coral = Product.objects.create(
            name="Torch", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=3,
        )
        cls.wysiwyg = Product.objects.create(
            name="One Off", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("250.00"), status=Product.Status.ACTIVE,
            stock_quantity=1, is_wysiwyg=True,
        )
        cls.pump = Product.objects.create(
            name="Pump", category=cls.gear, product_type=ProductType.DRY_GOODS,
            price=Decimal("50.00"), status=Product.Status.ACTIVE, stock_quantity=10,
        )

    def add(self, product, quantity=1):
        return self.client.post(
            reverse("shop:add_to_cart", args=[product.slug]), {"quantity": quantity}
        )

    def test_add_to_cart_redirects_and_updates_the_badge(self):
        response = self.add(self.coral, 2)
        self.assertEqual(response.status_code, 302)
        cart_page = self.client.get(reverse("shop:cart"))
        self.assertContains(cart_page, "Torch")

    def test_add_to_cart_rejects_get(self):
        response = self.client.get(reverse("shop:add_to_cart", args=[self.coral.slug]))
        self.assertEqual(response.status_code, 405)

    def test_checkout_redirects_when_the_cart_is_empty(self):
        response = self.client.get(reverse("shop:checkout"))
        self.assertRedirects(response, reverse("catalog:shop"))

    def test_livestock_checkout_requires_accepting_terms(self):
        self.add(self.coral)
        response = self.client.post(reverse("shop:checkout"), dict(VALID_DETAILS))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "accepts_livestock_terms", "This field is required."
        )
        self.assertEqual(Order.objects.count(), 0)

    def test_dry_goods_only_checkout_does_not_require_terms(self):
        self.add(self.pump)
        response = self.client.post(reverse("shop:checkout"), dict(VALID_DETAILS))
        self.assertEqual(Order.objects.count(), 1)
        self.assertRedirects(
            response,
            reverse("shop:order_confirmation", args=[Order.objects.get().number]),
        )

    def test_successful_livestock_checkout_sends_confirmation(self):
        self.add(self.coral, 2)
        payload = dict(VALID_DETAILS, accepts_livestock_terms="on")
        response = self.client.post(reverse("shop:checkout"), payload)
        order = Order.objects.get()
        self.assertRedirects(
            response, reverse("shop:order_confirmation", args=[order.number])
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(order.number, mail.outbox[0].subject)

    def test_past_ship_date_is_rejected(self):
        self.add(self.coral)
        payload = dict(
            VALID_DETAILS,
            accepts_livestock_terms="on",
            requested_ship_date="2020-01-01",
        )
        response = self.client.post(reverse("shop:checkout"), payload)
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn("requested_ship_date", response.context["form"].errors)

    def test_confirmation_is_private_to_the_ordering_session(self):
        self.add(self.pump)
        self.client.post(reverse("shop:checkout"), dict(VALID_DETAILS))
        order = Order.objects.get()

        other = self.client.__class__()
        response = other.get(reverse("shop:order_confirmation", args=[order.number]))
        self.assertRedirects(response, reverse("shop:order_lookup"))

    def test_order_lookup_finds_an_order_by_number_and_email(self):
        self.add(self.pump)
        self.client.post(reverse("shop:checkout"), dict(VALID_DETAILS))
        order = Order.objects.get()

        other = self.client.__class__()
        response = other.post(
            reverse("shop:order_lookup"),
            {"number": order.number, "email": VALID_DETAILS["email"]},
        )
        self.assertRedirects(response, reverse("shop:order_detail", args=[order.number]))

    def test_order_lookup_rejects_a_mismatched_email(self):
        self.add(self.pump)
        self.client.post(reverse("shop:checkout"), dict(VALID_DETAILS))
        order = Order.objects.get()
        other = self.client.__class__()
        response = other.post(
            reverse("shop:order_lookup"),
            {"number": order.number, "email": "wrong@example.com"},
        )
        self.assertEqual(response.status_code, 200)

    def test_wysiwyg_item_cannot_be_ordered_twice(self):
        self.add(self.wysiwyg)
        payload = dict(VALID_DETAILS, accepts_livestock_terms="on")
        self.client.post(reverse("shop:checkout"), payload)
        self.assertEqual(Order.objects.count(), 1)

        second = self.client.__class__()
        second.post(reverse("shop:add_to_cart", args=[self.wysiwyg.slug]), {"quantity": 1})
        response = second.get(reverse("shop:checkout"))
        # The sold piece is gone, so checkout bounces back to the shop.
        self.assertRedirects(response, reverse("catalog:shop"))
        self.assertEqual(Order.objects.count(), 1)
