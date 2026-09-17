"""Content-driven pages: homepage, CMS pages, FAQ, contact."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.cms.models import (
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
