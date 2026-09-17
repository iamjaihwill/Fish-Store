from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Category, Collection, CollectionItem, Product, ProductType
from apps.cms.models import (
    ContactMessage,
    FaqItem,
    HeroSlide,
    HomepageSection,
    LiveSaleEvent,
    NavigationLink,
    NewsletterSubscriber,
    Page,
    SiteSettings,
    Testimonial,
    render_rich_text,
)


class SiteSettingsTests(TestCase):
    def test_load_is_idempotent_and_single_row(self):
        first = SiteSettings.load()
        second = SiteSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_saving_a_second_instance_overwrites_the_singleton(self):
        SiteSettings.load()
        SiteSettings(store_name="Second Store").save()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.load().store_name, "Second Store")

    def test_delete_is_blocked(self):
        with self.assertRaises(ValidationError):
            SiteSettings.load().delete()

    def test_social_links_skip_blank_urls(self):
        settings_obj = SiteSettings.load()
        settings_obj.instagram_url = "https://instagram.com/example"
        settings_obj.save()
        self.assertEqual(settings_obj.social_links, [("Instagram", "https://instagram.com/example")])


class RichTextTests(TestCase):
    def test_plain_text_becomes_paragraphs_and_is_escaped(self):
        html = render_rich_text("First para\n\nSecond <b>para</b>")
        self.assertIn("<p>First para</p>", html)
        self.assertIn("&lt;b&gt;", html)

    def test_html_authored_copy_passes_through(self):
        html = render_rich_text("<h2>Heading</h2><p>Body</p>")
        self.assertEqual(html, "<h2>Heading</h2><p>Body</p>")

    def test_stray_angle_brackets_stay_plain_text(self):
        html = render_rich_text("Keep alkalinity < 9 dKH")
        self.assertIn("&lt; 9 dKH", html)
        self.assertTrue(html.startswith("<p>"))

    def test_inline_markup_in_plain_copy_is_escaped(self):
        html = render_rich_text("Careful: <script>alert(1)</script>")
        self.assertNotIn("<script>", html)

    def test_blank_input(self):
        self.assertEqual(render_rich_text(""), "")


class HomepageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corals = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.featured = Product.objects.create(
            name="Featured Torch", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE,
            stock_quantity=2, is_featured=True,
        )
        cls.wysiwyg = Product.objects.create(
            name="Vault Piece", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("300.00"), status=Product.Status.ACTIVE,
            stock_quantity=1, is_wysiwyg=True,
        )
        cls.sale = Product.objects.create(
            name="Discounted Zoa", category=cls.corals, product_type=ProductType.CORAL,
            price=Decimal("40.00"), compare_at_price=Decimal("60.00"),
            status=Product.Status.ACTIVE, stock_quantity=3,
        )

    def test_homepage_renders_each_section_kind(self):
        HeroSlide.objects.create(headline="Corals grown here")
        for order, kind in enumerate(
            [
                HomepageSection.Kind.GUARANTEE,
                HomepageSection.Kind.FEATURED,
                HomepageSection.Kind.WYSIWYG,
                HomepageSection.Kind.ON_SALE,
                HomepageSection.Kind.CATEGORY_GRID,
                HomepageSection.Kind.NEW_ARRIVALS,
                HomepageSection.Kind.TESTIMONIALS,
                HomepageSection.Kind.RICH_TEXT,
            ]
        ):
            HomepageSection.objects.create(
                kind=kind, heading=f"Band {order}", sort_order=order,
                body="Some copy" if kind == HomepageSection.Kind.RICH_TEXT else "",
            )
        Testimonial.objects.create(quote="Great corals", author="Dana")

        response = self.client.get(reverse("cms:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corals grown here")
        self.assertContains(response, "Featured Torch")
        self.assertContains(response, "Vault Piece")
        self.assertContains(response, "Discounted Zoa")
        self.assertContains(response, "Great corals")
        self.assertContains(response, "Some copy")

    def test_inactive_sections_are_skipped(self):
        HomepageSection.objects.create(
            kind=HomepageSection.Kind.FEATURED, heading="Hidden band", is_active=False
        )
        response = self.client.get(reverse("cms:home"))
        self.assertNotContains(response, "Hidden band")

    def test_collection_section_lists_its_products(self):
        collection = Collection.objects.create(title="Curated")
        CollectionItem.objects.create(collection=collection, product=self.featured)
        HomepageSection.objects.create(
            kind=HomepageSection.Kind.COLLECTION, heading="Curated", collection=collection
        )
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "Featured Torch")

    def test_collection_section_without_a_collection_fails_validation(self):
        section = HomepageSection(kind=HomepageSection.Kind.COLLECTION)
        with self.assertRaises(ValidationError):
            section.full_clean()

    def test_max_items_limits_the_band(self):
        for i in range(5):
            Product.objects.create(
                name=f"Extra {i}", category=self.corals, product_type=ProductType.CORAL,
                price=Decimal("10.00"), status=Product.Status.ACTIVE,
                stock_quantity=1, is_featured=True,
            )
        HomepageSection.objects.create(kind=HomepageSection.Kind.FEATURED, max_items=2)
        response = self.client.get(reverse("cms:home"))
        self.assertEqual(len(response.context["sections"][0]["products"]), 2)

    def test_expired_hero_slide_is_not_shown(self):
        HeroSlide.objects.create(
            headline="Old campaign",
            ends_at=timezone.now() - timezone.timedelta(days=1),
        )
        response = self.client.get(reverse("cms:home"))
        self.assertNotContains(response, "Old campaign")

    def test_upcoming_live_sale_appears_on_the_homepage(self):
        LiveSaleEvent.objects.create(
            title="Friday Frag Fest",
            starts_at=timezone.now() + timezone.timedelta(days=2),
        )
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "Friday Frag Fest")


class PageAndNavigationTests(TestCase):
    def test_published_page_renders_its_body(self):
        page = Page.objects.create(
            title="Shipping", body="<p>We ship overnight.</p>", summary="How it works"
        )
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, "We ship overnight.")

    def test_unpublished_page_is_404(self):
        page = Page.objects.create(title="Draft policy", is_published=False)
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 404)

    def test_footer_lists_published_pages(self):
        Page.objects.create(title="Returns", show_in_footer=True)
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "Returns")

    def test_navigation_link_requires_a_target(self):
        with self.assertRaises(ValidationError):
            NavigationLink(label="Broken").clean()

    def test_navigation_link_prefers_its_page(self):
        page = Page.objects.create(title="Guarantee")
        link = NavigationLink.objects.create(label="Guarantee", page=page, url="/ignored/")
        self.assertEqual(link.href, page.get_absolute_url())

    def test_header_nav_shows_active_categories_only(self):
        Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        Category.objects.create(
            name="Hidden Dept", product_type=ProductType.CORAL, show_in_nav=False
        )
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "Corals")
        self.assertNotContains(response, "Hidden Dept")


class FaqAndContactTests(TestCase):
    def test_faq_groups_by_topic(self):
        FaqItem.objects.create(
            topic=FaqItem.Topic.SHIPPING, question="When do you ship?", answer="Mondays."
        )
        FaqItem.objects.create(
            topic=FaqItem.Topic.LIVESTOCK, question="What is WYSIWYG?", answer="Exactly that."
        )
        response = self.client.get(reverse("cms:faq"))
        self.assertContains(response, "Shipping &amp; arrival")
        self.assertContains(response, "Livestock care")

    def test_inactive_faq_is_hidden(self):
        FaqItem.objects.create(question="Secret", answer="Hidden", is_active=False)
        self.assertNotContains(self.client.get(reverse("cms:faq")), "Secret")

    def test_contact_form_stores_a_message(self):
        response = self.client.post(
            reverse("cms:contact"),
            {
                "name": "Dana",
                "email": "dana@example.com",
                "subject": "Torch question",
                "message": "Is this aquacultured?",
                "order_reference": "",
            },
        )
        self.assertRedirects(response, reverse("cms:contact"))
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_invalid_contact_form_does_not_store(self):
        self.client.post(reverse("cms:contact"), {"name": "Dana", "email": "not-an-email"})
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_newsletter_signup_is_deduplicated(self):
        for _ in range(2):
            self.client.post(reverse("cms:newsletter"), {"email": "dana@example.com"})
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)


class LiveSaleTests(TestCase):
    def test_event_end_must_follow_its_start(self):
        event = LiveSaleEvent(
            title="Bad window",
            starts_at=timezone.now(),
            ends_at=timezone.now() - timezone.timedelta(hours=1),
        )
        with self.assertRaises(ValidationError):
            event.clean()

    def test_running_and_upcoming_states(self):
        now = timezone.now()
        running = LiveSaleEvent.objects.create(
            title="Now", starts_at=now - timezone.timedelta(minutes=5),
            ends_at=now + timezone.timedelta(hours=1),
        )
        upcoming = LiveSaleEvent.objects.create(
            title="Later", starts_at=now + timezone.timedelta(days=1)
        )
        self.assertTrue(running.is_running)
        self.assertFalse(running.is_upcoming)
        self.assertTrue(upcoming.is_upcoming)
        self.assertFalse(upcoming.is_running)

    def test_live_sales_page_splits_upcoming_and_past(self):
        now = timezone.now()
        LiveSaleEvent.objects.create(title="Next drop", starts_at=now + timezone.timedelta(days=3))
        LiveSaleEvent.objects.create(title="Old drop", starts_at=now - timezone.timedelta(days=30))
        response = self.client.get(reverse("cms:live_sales"))
        self.assertContains(response, "Next drop")
        self.assertContains(response, "Old drop")
