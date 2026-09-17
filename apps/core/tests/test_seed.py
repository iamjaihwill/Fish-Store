from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import Category, Collection, Product
from apps.cms.models import FaqItem, HomepageSection, Page, SiteSettings


class SeedStoreCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_store", "--no-images", stdout=StringIO())

    def test_catalog_is_populated(self):
        self.assertGreater(Product.objects.count(), 20)
        self.assertGreater(Category.objects.count(), 10)
        self.assertTrue(Product.objects.filter(is_wysiwyg=True).exists())
        self.assertTrue(Product.objects.published().exists())

    def test_content_is_populated(self):
        self.assertTrue(Page.objects.filter(title="Live Arrival Guarantee").exists())
        self.assertTrue(HomepageSection.objects.exists())
        self.assertTrue(FaqItem.objects.exists())
        self.assertTrue(Collection.objects.exists())
        self.assertEqual(SiteSettings.load().store_name, "Reef & Rift")

    def test_seeding_twice_does_not_duplicate(self):
        before = Product.objects.count()
        call_command("seed_store", "--no-images", stdout=StringIO())
        self.assertEqual(Product.objects.count(), before)

    def test_seeded_store_renders_end_to_end(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/shop/").status_code, 200)
        product = Product.objects.published().first()
        self.assertEqual(self.client.get(product.get_absolute_url()).status_code, 200)

    def test_wysiwyg_products_are_single_quantity(self):
        for product in Product.objects.filter(is_wysiwyg=True):
            self.assertLessEqual(product.stock_quantity, 1)
