from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductType


class ProductModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.gear = Category.objects.create(name="Gear", product_type=ProductType.DRY_GOODS)

    def make(self, **kwargs):
        defaults = {
            "name": "Test Coral",
            "category": self.corals,
            "product_type": ProductType.CORAL,
            "price": Decimal("100.00"),
            "status": Product.Status.ACTIVE,
            "stock_quantity": 5,
        }
        return Product.objects.create(**{**defaults, **kwargs})

    def test_slug_and_sku_are_generated(self):
        product = self.make(name="Midnight Torch")
        self.assertEqual(product.slug, "midnight-torch")
        self.assertTrue(product.sku.startswith("COR-"))

    def test_slugs_stay_unique(self):
        first = self.make(name="Duplicate Name")
        second = self.make(name="Duplicate Name")
        self.assertNotEqual(first.slug, second.slug)
        self.assertNotEqual(first.sku, second.sku)

    def test_wysiwyg_products_are_capped_at_one_unit(self):
        product = self.make(is_wysiwyg=True, stock_quantity=7)
        self.assertEqual(product.stock_quantity, 1)
        self.assertTrue(product.track_inventory)
        self.assertEqual(product.max_orderable, 1)

    def test_sold_wysiwyg_reports_zero_orderable(self):
        product = self.make(is_wysiwyg=True, stock_quantity=0)
        self.assertTrue(product.is_sold_out)
        self.assertEqual(product.max_orderable, 0)

    def test_livestock_forces_overnight_shipping(self):
        coral = self.make()
        self.assertTrue(coral.requires_overnight_shipping)
        widget = self.make(
            name="Test Pump", category=self.gear, product_type=ProductType.DRY_GOODS
        )
        self.assertFalse(widget.requires_overnight_shipping)

    def test_sale_pricing_math(self):
        product = self.make(price=Decimal("75.00"), compare_at_price=Decimal("100.00"))
        self.assertTrue(product.is_on_sale)
        self.assertEqual(product.savings, Decimal("25.00"))
        self.assertEqual(product.discount_percent, 25)

    def test_compare_price_below_price_is_not_a_sale(self):
        product = self.make(price=Decimal("100.00"), compare_at_price=Decimal("90.00"))
        self.assertFalse(product.is_on_sale)
        self.assertEqual(product.discount_percent, 0)

    def test_untracked_inventory_never_sells_out(self):
        product = self.make(track_inventory=False, stock_quantity=0)
        self.assertFalse(product.is_sold_out)
        self.assertIsNone(product.available_quantity)
        self.assertTrue(product.can_fulfill(50))

    def test_can_fulfill_respects_stock_and_publication(self):
        product = self.make(stock_quantity=2)
        self.assertTrue(product.can_fulfill(2))
        self.assertFalse(product.can_fulfill(3))

        draft = self.make(name="Draft Coral", status=Product.Status.DRAFT)
        self.assertFalse(draft.can_fulfill(1))

        future = self.make(
            name="Scheduled Coral",
            published_at=timezone.now() + timezone.timedelta(days=1),
        )
        self.assertFalse(future.can_fulfill(1))

    def test_care_facts_skip_blank_fields(self):
        product = self.make(care_level="beginner", lighting="low", diet="")
        labels = [label for label, _ in product.care_facts]
        self.assertIn("Care level", labels)
        self.assertIn("Lighting", labels)
        self.assertNotIn("Diet", labels)

    def test_published_queryset_excludes_drafts_and_future(self):
        live = self.make(name="Live One")
        self.make(name="Draft One", status=Product.Status.DRAFT)
        self.make(
            name="Future One",
            published_at=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertEqual(list(Product.objects.published()), [live])
