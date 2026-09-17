"""Content-driven pages: homepage, CMS pages, FAQ, contact."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.cms.models import (
    Article,
    ContactMessage,
    FaqItem,
    HeroSlide,
    HomepageSection,
    LiveSaleEvent,
    NewsletterSubscriber,
    Page,
    Testimonial,
)
from apps.shop.forms import ContactForm, NewsletterForm


def _section_products(section):
    """Resolve the product list a homepage section should render."""
    Kind = HomepageSection.Kind
    limit = section.max_items or 8
    base = Product.objects.for_storefront()
    if section.kind == Kind.FEATURED:
        return base.filter(is_featured=True)[:limit]
    if section.kind == Kind.NEW_ARRIVALS:
        return base.order_by("-published_at")[:limit]
    if section.kind == Kind.WYSIWYG:
        return base.filter(is_wysiwyg=True).in_stock()[:limit]
    if section.kind == Kind.ON_SALE:
        return base.on_sale()[:limit]
    if section.kind == Kind.COLLECTION and section.collection:
        return section.collection.visible_products()[:limit]
    return []


def home(request):
    sections = []
    for section in HomepageSection.objects.filter(is_active=True).select_related(
        "collection"
    ):
        sections.append(
            {
                "section": section,
                "products": _section_products(section),
                "categories": (
                    Category.objects.active().top_level()
                    if section.kind == HomepageSection.Kind.CATEGORY_GRID
                    else []
                ),
                "testimonials": (
                    Testimonial.objects.filter(is_active=True)
                    if section.kind == HomepageSection.Kind.TESTIMONIALS
                    else []
                ),
            }
        )

    now = timezone.now()
    live_sale = (
        LiveSaleEvent.objects.filter(is_active=True)
        .filter(starts_at__gte=now - timezone.timedelta(hours=6))
        .first()
    )

    return render(
        request,
        "cms/home.html",
        {
            "slides": [s for s in HeroSlide.objects.all() if s.is_live],
            "sections": sections,
            "live_sale": live_sale,
        },
    )


def page_detail(request, slug):
    page = get_object_or_404(Page, slug=slug, is_published=True)
    return render(request, "cms/page.html", {"page": page})


def faq(request):
    items = FaqItem.objects.filter(is_active=True)
    grouped = {}
    for item in items:
        grouped.setdefault(item.get_topic_display(), []).append(item)
    return render(request, "cms/faq.html", {"grouped": grouped})


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            ContactMessage.objects.create(**form.cleaned_data)
            messages.success(
                request, "Thanks — we read every message and reply within one business day."
            )
            return redirect("cms:contact")
    else:
        form = ContactForm()
    return render(request, "cms/contact.html", {"form": form})


def newsletter_signup(request):
    if request.method == "POST":
        form = NewsletterForm(request.POST)
        if form.is_valid():
            NewsletterSubscriber.objects.get_or_create(
                email=form.cleaned_data["email"].lower()
            )
            messages.success(request, "You're on the list. Watch for drop announcements.")
        else:
            messages.error(request, "That email address didn't look right.")
    return redirect(request.META.get("HTTP_REFERER") or "cms:home")


def live_sales(request):
    now = timezone.now()
    return render(
        request,
        "cms/live_sales.html",
        {
            "upcoming": LiveSaleEvent.objects.filter(
                is_active=True, starts_at__gte=now
            ),
            "past": LiveSaleEvent.objects.filter(
                is_active=True, starts_at__lt=now
            ).order_by("-starts_at")[:6],
        },
    )


def articles(request):
    """Care guides index."""
    from django.core.paginator import Paginator

    queryset = [a for a in Article.objects.filter(is_published=True) if a.is_live]
    selected = request.GET.get("category")
    if selected:
        queryset = [a for a in queryset if a.category == selected]
    page = Paginator(queryset, 9).get_page(request.GET.get("page"))
    return render(
        request,
        "cms/articles.html",
        {
            "page_obj": page,
            "articles": page.object_list,
            "categories": Article.Category.choices,
            "selected": selected,
        },
    )


def article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug, is_published=True)
    if article.published_at > timezone.now():
        from django.http import Http404

        raise Http404("No article matches the given query.")
    return render(
        request,
        "cms/article.html",
        {
            "article": article,
            "related": article.related_products.all()[:4],
            "more": [
                a
                for a in Article.objects.filter(is_published=True).exclude(pk=article.pk)[:3]
                if a.is_live
            ],
        },
    )


def robots_txt(request):
    """robots.txt pointing at the sitemap."""
    from django.http import HttpResponse

    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /account/",
        "Disallow: /orders/",
        "Allow: /",
        "",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def search_suggest(request):
    """Instant-search suggestions for the header field."""
    from django.db.models import Q
    from django.http import JsonResponse

    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    products = (
        Product.objects.for_storefront()
        .filter(
            Q(name__icontains=query)
            | Q(scientific_name__icontains=query)
            | Q(sku__iexact=query)
        )[:8]
    )
    results = []
    for product in products:
        image = product.primary_image
        results.append(
            {
                "name": product.name,
                "url": product.get_absolute_url(),
                "price": str(product.price_from),
                "image": image.image.url if image else "",
                "sold_out": product.is_sold_out,
                "wysiwyg": product.is_wysiwyg,
            }
        )
    return JsonResponse({"results": results, "query": query})
