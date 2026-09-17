from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.contrib.sessions.middleware import SessionMiddleware

from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import SiteSettings
from apps.shop.cart import Cart


def request_with_session():
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    return request


class CartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.gear = Category.objects.create(name="Gear", product_type=ProductType.DRY_GOODS)
        cls.coral = Product.objects.create(
            name="Torch", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=5,
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

    def setUp(self):
        self.cart = Cart(request_with_session())

    def test_add_accumulates_quantity(self):
        self.cart.add(self.coral, 2)
        self.cart.add(self.coral, 1)
        self.assertEqual(len(self.cart), 3)

    def test_add_is_clamped_to_available_stock(self):
        placed = self.cart.add(self.coral, 99)
        self.assertEqual(placed, 5)
        self.assertEqual(len(self.cart), 5)

    def test_wysiwyg_cannot_exceed_one(self):
        self.assertEqual(self.cart.add(self.wysiwyg, 5), 1)
        self.assertEqual(self.cart.add(self.wysiwyg, 3), 1)

    def test_set_quantity_replaces_rather_than_adds(self):
        self.cart.add(self.coral, 3)
        self.cart.set_quantity(self.coral, 1)
        self.assertEqual(len(self.cart), 1)

    def test_zero_quantity_removes_the_line(self):
        self.cart.add(self.coral, 2)
        self.cart.set_quantity(self.coral, 0)
        self.assertTrue(self.cart.is_empty)

    def test_remove_and_clear(self):
        self.cart.add(self.coral, 1)
        self.cart.add(self.pump, 1)
        self.cart.remove(self.coral)
        self.assertEqual(len(self.cart), 1)
        self.cart.clear()
        self.assertTrue(self.cart.is_empty)

    def test_subtotal_uses_live_catalog_prices(self):
        self.cart.add(self.coral, 2)
        self.assertEqual(self.cart.subtotal, Decimal("200.00"))
        # A price change in the catalog is reflected immediately.
        Product.objects.filter(pk=self.coral.pk).update(price=Decimal("120.00"))
        self.assertEqual(self.cart.subtotal, Decimal("240.00"))

    def test_unpublished_products_drop_out_of_the_cart(self):
        self.cart.add(self.coral, 1)
        Product.objects.filter(pk=self.coral.pk).update(status=Product.Status.DRAFT)
        self.assertEqual(self.cart.lines, [])
        self.assertTrue(self.cart.is_empty)

    def test_livestock_detection_drives_shipping_rate(self):
        settings_obj = SiteSettings.load()
        settings_obj.free_shipping_threshold = Decimal("299.00")
        settings_obj.livestock_shipping_rate = Decimal("59.00")
        settings_obj.drygoods_shipping_rate = Decimal("12.00")
        settings_obj.save()

        self.cart.add(self.pump, 1)
        self.assertFalse(self.cart.contains_livestock)
        self.assertEqual(self.cart.shipping_total, Decimal("12.00"))

        self.cart.add(self.coral, 1)
        self.assertTrue(self.cart.contains_livestock)
        self.assertEqual(self.cart.shipping_total, Decimal("59.00"))

    def test_free_shipping_above_threshold(self):
        settings_obj = SiteSettings.load()
        settings_obj.free_shipping_threshold = Decimal("299.00")
        settings_obj.save()
        self.cart.add(self.coral, 3)  # $300
        self.assertEqual(self.cart.shipping_total, Decimal("0.00"))
        self.assertEqual(self.cart.amount_to_free_shipping, Decimal("0.00"))

    def test_amount_to_free_shipping(self):
        settings_obj = SiteSettings.load()
        settings_obj.free_shipping_threshold = Decimal("299.00")
        settings_obj.save()
        self.cart.add(self.coral, 1)
        self.assertEqual(self.cart.amount_to_free_shipping, Decimal("199.00"))

    def test_tax_is_applied_to_the_subtotal(self):
        settings_obj = SiteSettings.load()
        settings_obj.tax_rate_percent = Decimal("7.50")
        settings_obj.save()
        self.cart.add(self.coral, 1)
        self.assertEqual(self.cart.tax_total, Decimal("7.50"))
        self.assertEqual(self.cart.grand_total, self.cart.subtotal + self.cart.shipping_total + Decimal("7.50"))

    def test_sync_to_stock_clamps_lines_that_sold_out(self):
        self.cart.add(self.coral, 4)
        Product.objects.filter(pk=self.coral.pk).update(stock_quantity=2)
        adjusted = self.cart.sync_to_stock()
        self.assertEqual(len(adjusted), 1)
        self.assertEqual(len(self.cart), 2)

    def test_problems_reports_over_stock_lines(self):
        self.cart.add(self.coral, 4)
        Product.objects.filter(pk=self.coral.pk).update(stock_quantity=1)
        self.assertEqual(len(self.cart.problems()), 1)
