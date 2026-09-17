from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, Collection, CollectionItem, Product, ProductType


class BrowseViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.gear = Category.objects.create(name="Gear", product_type=ProductType.DRY_GOODS)
        cls.easy = Product.objects.create(
            name="Easy Zoa", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("40.00"), status=Product.Status.ACTIVE, stock_quantity=4,
            care_level="beginner", lighting="low", flow="low", is_aquacultured=True,
        )
        cls.hard = Product.objects.create(
            name="Hard Acro", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("400.00"), status=Product.Status.ACTIVE, stock_quantity=1,
            care_level="expert", lighting="high", flow="high", is_wysiwyg=True,
        )
        cls.pump = Product.objects.create(
            name="Return Pump", category=cls.gear, product_type=ProductType.DRY_GOODS,
            price=Decimal("120.00"), status=Product.Status.ACTIVE, stock_quantity=3,
        )
        cls.sold = Product.objects.create(
            name="Sold Coral", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("90.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        cls.draft = Product.objects.create(
            name="Secret Coral", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("90.00"), status=Product.Status.DRAFT,
        )

    def names(self, response):
        return {p.name for p in response.context["products"]}

    def test_shop_lists_published_in_stock_products(self):
        response = self.client.get(reverse("catalog:shop"))
        self.assertEqual(response.status_code, 200)
        names = self.names(response)
        self.assertIn("Easy Zoa", names)
        self.assertNotIn("Secret Coral", names)
        self.assertNotIn("Sold Coral", names)

    def test_in_stock_filter_can_be_turned_off(self):
        response = self.client.get(reverse("catalog:shop"), {"in_stock": "0"})
        self.assertIn("Sold Coral", self.names(response))

    def test_care_level_filter(self):
        response = self.client.get(reverse("catalog:shop"), {"care": "beginner"})
        self.assertEqual(self.names(response), {"Easy Zoa"})

    def test_multiple_care_levels_are_ored(self):
        response = self.client.get(reverse("catalog:shop"), {"care": ["beginner", "expert"]})
        self.assertEqual(self.names(response), {"Easy Zoa", "Hard Acro"})

    def test_wysiwyg_and_type_filters(self):
        response = self.client.get(reverse("catalog:shop"), {"wysiwyg": "1"})
        self.assertEqual(self.names(response), {"Hard Acro"})

        response = self.client.get(reverse("catalog:shop"), {"type": ProductType.DRY_GOODS})
        self.assertEqual(self.names(response), {"Return Pump"})

    def test_price_range_filter(self):
        response = self.client.get(
            reverse("catalog:shop"), {"min_price": "100", "max_price": "500"}
        )
        self.assertEqual(self.names(response), {"Hard Acro", "Return Pump"})

    def test_invalid_price_is_ignored_rather_than_erroring(self):
        response = self.client.get(reverse("catalog:shop"), {"min_price": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_sorting_by_price(self):
        response = self.client.get(reverse("catalog:shop"), {"sort": "price_asc"})
        prices = [p.price for p in response.context["products"]]
        self.assertEqual(prices, sorted(prices))

    def test_search_matches_name(self):
        response = self.client.get(reverse("catalog:search"), {"q": "Acro"})
        self.assertEqual(self.names(response), {"Hard Acro"})

    def test_category_page_scopes_to_its_products(self):
        response = self.client.get(self.corals.get_absolute_url())
        self.assertNotIn("Return Pump", self.names(response))

    def test_category_page_includes_child_categories(self):
        child = Category.objects.create(
            name="SPS", parent=self.corals, product_type=ProductType.CORAL
        )
        nested = Product.objects.create(
            name="Nested Coral", category=child, product_type=ProductType.CORAL,
            price=Decimal("50.00"), status=Product.Status.ACTIVE, stock_quantity=2,
        )
        response = self.client.get(self.corals.get_absolute_url())
        self.assertIn(nested.name, self.names(response))

    def test_collection_page(self):
        collection = Collection.objects.create(title="Picks")
        CollectionItem.objects.create(collection=collection, product=self.easy)
        response = self.client.get(collection.get_absolute_url())
        self.assertEqual(self.names(response), {"Easy Zoa"})

    def test_product_detail_renders_care_table(self):
        response = self.client.get(self.easy.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Care requirements")
        self.assertContains(response, "Beginner")

    def test_draft_product_is_404_for_anonymous_visitors(self):
        response = self.client.get(self.draft.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_sold_out_product_detail_hides_add_to_cart(self):
        response = self.client.get(self.sold.get_absolute_url())
        self.assertContains(response, "Sold out")
        # The related-products rail still offers other items, so check that this
        # product's own add-to-cart form is what is missing.
        self.assertNotContains(
            response, reverse("shop:add_to_cart", args=[self.sold.slug])
        )

    def test_pagination_does_not_lose_filters(self):
        response = self.client.get(reverse("catalog:shop"), {"care": "beginner", "page": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("care=beginner", response.context["querystring"])
