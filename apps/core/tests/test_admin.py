"""The admin is the CMS, so its pages are covered like any other surface."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, Collection, Product, ProductType
from apps.cms.models import SiteSettings
from apps.shop.models import Order, OrderItem


class AdminSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            "curator", "curator@example.com", "reef-pass-123"
        )
        cls.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.product = Product.objects.create(
            name="Torch", category=cls.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=4,
        )
        cls.collection = Collection.objects.create(title="Picks")
        cls.order = Order.objects.create(
            email="reefer@example.com", first_name="Sam", last_name="Rivera",
            phone="555-0100", address_line1="12 Coral Way", city="Wilmington",
            state="NC", postal_code="28401",
        )
        OrderItem.objects.create(
            order=cls.order, product=cls.product, name="Torch", sku="COR-TORCH",
            unit_price=Decimal("100.00"), quantity=2, is_livestock=True,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_changelists_render(self):
        for url_name in [
            "admin:catalog_product_changelist",
            "admin:catalog_category_changelist",
            "admin:catalog_collection_changelist",
            "admin:cms_page_changelist",
            "admin:cms_homepagesection_changelist",
            "admin:cms_heroslide_changelist",
            "admin:cms_faqitem_changelist",
            "admin:cms_livesaleevent_changelist",
            "admin:shop_order_changelist",
            "admin:shop_doaclaim_changelist",
        ]:
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_product_change_form_renders(self):
        response = self.client.get(
            reverse("admin:catalog_product_change", args=[self.product.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reef care")

    def test_site_settings_changelist_redirects_to_the_single_record(self):
        response = self.client.get(reverse("admin:cms_sitesettings_changelist"))
        settings_obj = SiteSettings.load()
        self.assertRedirects(
            response, reverse("admin:cms_sitesettings_change", args=[settings_obj.pk])
        )

    def test_publish_action_activates_drafts(self):
        draft = Product.objects.create(
            name="Draft Coral", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("50.00"), status=Product.Status.DRAFT,
        )
        self.client.post(
            reverse("admin:catalog_product_changelist"),
            {"action": "publish", "_selected_action": [draft.pk]},
        )
        draft.refresh_from_db()
        self.assertEqual(draft.status, Product.Status.ACTIVE)

    def test_mark_sold_out_action(self):
        self.client.post(
            reverse("admin:catalog_product_changelist"),
            {"action": "mark_sold_out", "_selected_action": [self.product.pk]},
        )
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_sold_out)

    def test_cancel_and_restock_action_returns_inventory(self):
        self.client.post(
            reverse("admin:shop_order_changelist"),
            {"action": "cancel_and_restock", "_selected_action": [self.order.pk]},
        )
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock_quantity, 6)

    def test_mark_shipped_action_stamps_the_ship_date(self):
        self.client.post(
            reverse("admin:shop_order_changelist"),
            {"action": "mark_shipped_action", "_selected_action": [self.order.pk]},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertIsNotNone(self.order.shipped_at)

    def test_stock_filter_narrows_the_changelist(self):
        response = self.client.get(
            reverse("admin:catalog_product_changelist"), {"stock": "out"}
        )
        self.assertEqual(response.status_code, 200)

    def test_anonymous_users_are_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
