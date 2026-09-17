"""Sitemaps. Search traffic is how a coral shop gets found."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.catalog.models import Category, Collection, Product
from apps.cms.models import Article, Page


class ProductSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9

    def items(self):
        return Product.objects.published()

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return Category.objects.active()


class CollectionSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Collection.objects.filter(is_active=True)


class PageSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return Page.objects.filter(is_published=True)

    def lastmod(self, obj):
        return obj.updated_at


class ArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return [a for a in Article.objects.filter(is_published=True) if a.is_live]

    def lastmod(self, obj):
        return obj.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return ["cms:home", "catalog:shop", "cms:faq", "cms:live_sales", "cms:articles"]

    def location(self, item):
        return reverse(item)


SITEMAPS = {
    "static": StaticViewSitemap,
    "products": ProductSitemap,
    "categories": CategorySitemap,
    "collections": CollectionSitemap,
    "pages": PageSitemap,
    "articles": ArticleSitemap,
}
