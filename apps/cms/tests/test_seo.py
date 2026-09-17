import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductType
from apps.cms.models import Article, Page
from apps.reviews.models import Review


class SeoBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.product = Product.objects.create(
            name="Midnight Torch", category=cls.category, product_type=ProductType.CORAL,
            price=Decimal("340.00"), status=Product.Status.ACTIVE, stock_quantity=2,
            scientific_name="Euphyllia glabrescens", tagline="Deep teal tentacles.",
        )


class SitemapTests(SeoBase):
    def test_sitemap_renders_and_lists_the_product(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response["Content-Type"])
        self.assertContains(response, self.product.get_absolute_url())

    def test_unpublished_products_are_not_in_the_sitemap(self):
        hidden = Product.objects.create(
            name="Draft Coral", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("50.00"), status=Product.Status.DRAFT,
        )
        response = self.client.get("/sitemap.xml")
        self.assertNotContains(response, hidden.get_absolute_url())

    def test_static_pages_are_listed(self):
        response = self.client.get("/sitemap.xml")
        self.assertContains(response, reverse("catalog:shop"))

    def test_published_pages_and_articles_appear(self):
        page = Page.objects.create(title="Shipping", body="Overnight.")
        article = Article.objects.create(title="Torch care", body="Feed weekly.")
        response = self.client.get("/sitemap.xml")
        self.assertContains(response, page.get_absolute_url())
        self.assertContains(response, article.get_absolute_url())

    def test_future_dated_articles_are_excluded(self):
        future = Article.objects.create(
            title="Embargoed", body="Later.",
            published_at=timezone.now() + timedelta(days=3),
        )
        response = self.client.get("/sitemap.xml")
        self.assertNotContains(response, future.get_absolute_url())


class RobotsTests(SeoBase):
    def test_robots_is_served_as_plain_text(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_private_areas_are_disallowed(self):
        body = self.client.get("/robots.txt").content.decode()
        for path in ["/admin/", "/checkout/", "/account/", "/cart/"]:
            self.assertIn(f"Disallow: {path}", body)

    def test_robots_points_at_the_sitemap(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Sitemap: http://testserver/sitemap.xml", body)


class StructuredDataTests(SeoBase):
    def get_json_ld(self, product=None):
        response = self.client.get((product or self.product).get_absolute_url())
        raw = response.context["structured_data"]
        return json.loads(raw)

    def test_product_json_ld_has_the_core_fields(self):
        data = self.get_json_ld()
        self.assertEqual(data["@type"], "Product")
        self.assertEqual(data["name"], "Midnight Torch")
        self.assertEqual(data["sku"], self.product.sku)
        self.assertEqual(data["alternateName"], "Euphyllia glabrescens")

    def test_offer_reports_price_and_in_stock(self):
        offer = self.get_json_ld()["offers"]
        self.assertEqual(offer["price"], "340.00")
        self.assertEqual(offer["priceCurrency"], "USD")
        self.assertEqual(offer["availability"], "https://schema.org/InStock")

    def test_sold_out_product_reports_out_of_stock(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        offer = self.get_json_ld()["offers"]
        self.assertEqual(offer["availability"], "https://schema.org/OutOfStock")

    def test_aggregate_rating_appears_once_reviews_are_published(self):
        self.assertNotIn("aggregateRating", self.get_json_ld())
        Review.objects.create(
            product=self.product, author_name="Dana", rating=5, body="Great.",
            status=Review.Status.APPROVED,
        )
        rating = self.get_json_ld()["aggregateRating"]
        self.assertEqual(rating["ratingValue"], "5.0")
        self.assertEqual(rating["reviewCount"], 1)

    def test_json_ld_is_embedded_in_the_page(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'type="application/ld+json"')

    def test_open_graph_tags_describe_the_product(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, '<meta property="og:type" content="product">')
        self.assertContains(response, 'content="Midnight Torch"')


class SearchSuggestTests(SeoBase):
    def suggest(self, query):
        response = self.client.get(reverse("cms:search_suggest"), {"q": query})
        return json.loads(response.content)

    def test_short_queries_return_nothing(self):
        self.assertEqual(self.suggest("m")["results"], [])

    def test_matching_products_are_returned(self):
        results = self.suggest("torch")["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Midnight Torch")
        self.assertEqual(results[0]["url"], self.product.get_absolute_url())

    def test_scientific_name_is_searchable(self):
        self.assertEqual(len(self.suggest("Euphyllia")["results"]), 1)

    def test_unpublished_products_are_not_suggested(self):
        Product.objects.create(
            name="Torch Draft", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("10.00"), status=Product.Status.DRAFT,
        )
        self.assertEqual(len(self.suggest("torch")["results"]), 1)

    def test_sold_out_products_are_flagged(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        self.assertTrue(self.suggest("torch")["results"][0]["sold_out"])


class ArticleTests(SeoBase):
    def test_article_renders(self):
        article = Article.objects.create(
            title="Torch coral care", summary="Feed weekly.",
            body="<p>Keep flow moderate.</p>", author="Sam",
        )
        response = self.client.get(article.get_absolute_url())
        self.assertContains(response, "Keep flow moderate.")
        self.assertContains(response, "Sam")

    def test_unpublished_article_is_404(self):
        article = Article.objects.create(title="Hidden", body="x", is_published=False)
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 404)

    def test_future_article_is_404(self):
        article = Article.objects.create(
            title="Embargoed", body="x",
            published_at=timezone.now() + timedelta(days=2),
        )
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 404)

    def test_index_filters_by_category(self):
        Article.objects.create(title="Care one", body="x", category=Article.Category.CARE)
        Article.objects.create(title="News one", body="x", category=Article.Category.NEWS)
        response = self.client.get(reverse("cms:articles"), {"category": "news"})
        self.assertContains(response, "News one")
        self.assertNotContains(response, "Care one")

    def test_reading_time_is_estimated(self):
        article = Article.objects.create(title="Long", body=" ".join(["word"] * 400))
        self.assertEqual(article.reading_minutes, 2)


class AnalyticsTests(SeoBase):
    def test_no_snippet_when_unconfigured(self):
        response = self.client.get(reverse("cms:home"))
        self.assertNotContains(response, "plausible.io")
        self.assertNotContains(response, "googletagmanager")

    @override_settings(ANALYTICS_ID="site-123", ANALYTICS_PROVIDER="plausible",
                       ANALYTICS_DOMAIN="reefandrift.example")
    def test_plausible_snippet_is_emitted_when_configured(self):
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "plausible.io/js/script.js")
        self.assertContains(response, "reefandrift.example")

    @override_settings(ANALYTICS_ID="G-ABC123", ANALYTICS_PROVIDER="ga4")
    def test_ga4_snippet_is_emitted_when_configured(self):
        response = self.client.get(reverse("cms:home"))
        self.assertContains(response, "googletagmanager.com/gtag/js?id=G-ABC123")
