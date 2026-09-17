from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from io import StringIO

from apps.accounts.models import Customer, WishlistItem
from apps.catalog.models import (
    BundleItem,
    Category,
    Product,
    ProductType,
    ProductVariant,
    ProductVideo,
)
from apps.shop.models import Order, OrderItem
from django.contrib.auth import get_user_model

User = get_user_model()


class VariantModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.product = Product.objects.create(
            name="Torch", category=cls.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        cls.frag = ProductVariant.objects.create(
            product=cls.product, name="Single head", price=Decimal("120.00"),
            stock_quantity=4, is_default=True,
        )
        cls.colony = ProductVariant.objects.create(
            product=cls.product, name="Three head colony", price=Decimal("310.00"),
            stock_quantity=1,
        )

    def test_variants_generate_unique_skus(self):
        self.assertTrue(self.frag.sku)
        self.assertNotEqual(self.frag.sku, self.colony.sku)

    def test_price_from_is_the_cheapest_option(self):
        self.assertEqual(self.product.price_from, Decimal("120.00"))

    def test_available_quantity_sums_the_variants(self):
        self.assertEqual(self.product.available_quantity, 5)

    def test_product_with_stocked_variants_is_not_sold_out(self):
        # The product's own stock_quantity is 0; the variants carry the stock.
        self.assertFalse(self.product.is_sold_out)

    def test_product_is_sold_out_when_every_variant_is(self):
        ProductVariant.objects.filter(product=self.product).update(stock_quantity=0)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_sold_out)

    def test_only_one_default_variant(self):
        self.colony.is_default = True
        self.colony.save()
        self.frag.refresh_from_db()
        self.assertFalse(self.frag.is_default)

    def test_default_variant_falls_back_to_one_in_stock(self):
        self.frag.stock_quantity = 0
        self.frag.save()
        self.assertEqual(self.product.default_variant, self.colony)

    def test_can_fulfill_checks_the_named_variant(self):
        self.assertTrue(self.product.can_fulfill(1, variant=self.colony))
        self.assertFalse(self.product.can_fulfill(2, variant=self.colony))

    def test_inactive_variants_are_not_sellable(self):
        self.colony.is_active = False
        self.colony.save()
        self.assertEqual(len(self.product.sellable_variants), 1)
        self.assertEqual(self.product.available_quantity, 4)


class VariantCartTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        self.frag = ProductVariant.objects.create(
            product=self.product, name="Single head", price=Decimal("120.00"),
            stock_quantity=4, is_default=True,
        )
        self.colony = ProductVariant.objects.create(
            product=self.product, name="Colony", price=Decimal("310.00"), stock_quantity=1,
        )

    def add(self, variant=None, quantity=1):
        data = {"quantity": quantity}
        if variant:
            data["variant"] = variant.pk
        return self.client.post(
            reverse("shop:add_to_cart", args=[self.product.slug]), data
        )

    def test_variants_are_separate_cart_lines(self):
        self.add(self.frag)
        self.add(self.colony)
        response = self.client.get(reverse("shop:cart"))
        self.assertContains(response, "Single head")
        self.assertContains(response, "Colony")
        self.assertEqual(len(response.context["cart"].lines), 2)

    def test_line_uses_the_variant_price(self):
        self.add(self.colony)
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.subtotal, Decimal("310.00"))

    def test_bare_add_uses_the_default_variant(self):
        self.add()
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.lines[0].variant, self.frag)

    def test_quantity_is_clamped_to_the_variant_stock(self):
        self.add(self.colony, quantity=5)
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertEqual(cart.lines[0].quantity, 1)

    def test_cannot_add_a_variant_from_another_product(self):
        other = Product.objects.create(
            name="Hammer", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("90.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        foreign = ProductVariant.objects.create(
            product=other, name="Single", price=Decimal("90.00"), stock_quantity=2
        )
        response = self.client.post(
            reverse("shop:add_to_cart", args=[self.product.slug]),
            {"quantity": 1, "variant": foreign.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_deactivated_variant_drops_out_of_the_cart(self):
        self.add(self.colony)
        ProductVariant.objects.filter(pk=self.colony.pk).update(is_active=False)
        cart = self.client.get(reverse("shop:cart")).context["cart"]
        self.assertTrue(cart.is_empty)

    def test_checkout_decrements_the_variant_not_the_product(self):
        self.add(self.frag, quantity=2)
        self.client.post(
            reverse("shop:checkout"),
            {
                "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
                "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
                "state": "NC", "postal_code": "28401", "country": "United States",
                "accepts_livestock_terms": "on",
            },
        )
        self.frag.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.frag.stock_quantity, 2)
        self.assertEqual(self.product.stock_quantity, 0)

        item = OrderItem.objects.get()
        self.assertEqual(item.variant, self.frag)
        self.assertEqual(item.variant_name, "Single head")
        self.assertEqual(item.unit_price, Decimal("120.00"))

    def test_cancelling_restocks_the_variant(self):
        self.add(self.frag, quantity=2)
        self.client.post(
            reverse("shop:checkout"),
            {
                "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
                "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
                "state": "NC", "postal_code": "28401", "country": "United States",
                "accepts_livestock_terms": "on",
            },
        )
        Order.objects.get().restock()
        self.frag.refresh_from_db()
        self.assertEqual(self.frag.stock_quantity, 4)


class BundleTests(TestCase):
    def test_frag_pack_lists_its_contents(self):
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        zoa = Product.objects.create(
            name="Nebula Zoa", category=category, product_type=ProductType.CORAL,
            price=Decimal("40.00"), status=Product.Status.ACTIVE, stock_quantity=5,
        )
        pack = Product.objects.create(
            name="Beginner Four Pack", category=category, product_type=ProductType.BUNDLE,
            price=Decimal("129.00"), status=Product.Status.ACTIVE,
            stock_quantity=10, bundle_size=4,
        )
        BundleItem.objects.create(bundle=pack, product=zoa, quantity=2)

        self.assertTrue(pack.is_bundle)
        response = self.client.get(pack.get_absolute_url())
        self.assertContains(response, "What's in the pack")
        self.assertContains(response, "Nebula Zoa")

    def test_mystery_box_hides_its_contents(self):
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        box = Product.objects.create(
            name="Mystery Box", category=category, product_type=ProductType.BUNDLE,
            price=Decimal("199.00"), status=Product.Status.ACTIVE,
            stock_quantity=5, is_mystery=True, bundle_size=5,
        )
        response = self.client.get(box.get_absolute_url())
        self.assertContains(response, "mystery box is curated on packing day")


class VideoTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=2,
        )

    def test_youtube_watch_url_becomes_an_embed(self):
        video = ProductVideo.objects.create(
            product=self.product, url="https://www.youtube.com/watch?v=abc123&t=5"
        )
        self.assertEqual(video.embed_url, "https://www.youtube.com/embed/abc123")
        self.assertTrue(video.is_embed)

    def test_youtu_be_short_link_becomes_an_embed(self):
        video = ProductVideo.objects.create(
            product=self.product, url="https://youtu.be/xyz789?si=tracking"
        )
        self.assertEqual(video.embed_url, "https://www.youtube.com/embed/xyz789")

    def test_vimeo_link_becomes_a_player_url(self):
        video = ProductVideo.objects.create(
            product=self.product, url="https://vimeo.com/123456789"
        )
        self.assertEqual(video.embed_url, "https://player.vimeo.com/video/123456789")

    def test_direct_mp4_is_left_alone_and_rendered_as_video(self):
        video = ProductVideo.objects.create(
            product=self.product, url="https://cdn.example.com/torch.mp4"
        )
        self.assertEqual(video.embed_url, video.url)
        self.assertFalse(video.is_embed)

    def test_video_renders_on_the_product_page(self):
        ProductVideo.objects.create(
            product=self.product, url="https://www.youtube.com/watch?v=abc123"
        )
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "youtube.com/embed/abc123")


class RestockAlertTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        user = User.objects.create_user("sam@example.com", "sam@example.com", "pw-192837")
        self.customer = Customer.objects.create(user=user)
        self.item = WishlistItem.objects.create(
            customer=self.customer, product=self.product
        )

    def run_command(self, **kwargs):
        call_command("send_restock_alerts", stdout=StringIO(), **kwargs)

    def test_no_email_while_the_product_is_sold_out(self):
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.notified_at)

    def test_email_sent_once_stock_returns(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Back in stock", mail.outbox[0].subject)
        self.item.refresh_from_db()
        self.assertIsNotNone(self.item.notified_at)

    def test_customers_are_not_emailed_twice(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        self.run_command()
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_opting_out_suppresses_the_alert(self):
        self.item.notify_when_available = False
        self.item.save()
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_sends_nothing_and_marks_nothing(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        self.run_command(dry_run=True)
        self.assertEqual(len(mail.outbox), 0)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.notified_at)
