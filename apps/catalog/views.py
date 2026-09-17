"""Storefront browsing: shop grid, filters, category, collection, product."""

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from apps.catalog.models import (
    CareLevel,
    Category,
    Collection,
    FlowLevel,
    LightLevel,
    Product,
    ProductType,
    Tag,
)

SORT_OPTIONS = {
    "newest": ("-published_at", "Newest"),
    "price_asc": ("price", "Price: low to high"),
    "price_desc": ("-price", "Price: high to low"),
    "name": ("name", "Name A-Z"),
}
PAGE_SIZE = 12


def _filtered_products(request, base_queryset=None):
    """Apply the query-string filters shared by every browsing page."""
    products = (
        base_queryset
        if base_queryset is not None
        else Product.objects.for_storefront()
    )
    params = request.GET

    search = params.get("q", "").strip()
    if search:
        products = products.filter(
            Q(name__icontains=search)
            | Q(scientific_name__icontains=search)
            | Q(tagline__icontains=search)
            | Q(description__icontains=search)
            | Q(sku__iexact=search)
        )

    product_type = params.get("type")
    if product_type in ProductType.values:
        products = products.filter(product_type=product_type)

    care = params.getlist("care")
    if care:
        products = products.filter(care_level__in=care)

    lighting = params.getlist("lighting")
    if lighting:
        products = products.filter(lighting__in=lighting)

    flow = params.getlist("flow")
    if flow:
        products = products.filter(flow__in=flow)

    tag = params.get("tag")
    if tag:
        products = products.filter(tags__slug=tag)

    if params.get("wysiwyg") == "1":
        products = products.filter(is_wysiwyg=True)
    if params.get("sale") == "1":
        products = products.on_sale()
    if params.get("aquacultured") == "1":
        products = products.filter(is_aquacultured=True)
    if params.get("in_stock", "1") == "1":
        products = products.in_stock()

    for key, lookup in (("min_price", "price__gte"), ("max_price", "price__lte")):
        raw = params.get(key)
        if raw:
            try:
                products = products.filter(**{lookup: float(raw)})
            except ValueError:
                pass

    sort = params.get("sort", "newest")
    ordering = SORT_OPTIONS.get(sort, SORT_OPTIONS["newest"])[0]
    return products.distinct().order_by(ordering, "-pk")


def _browse_context(request, products, **extra):
    paginator = Paginator(products, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    querystring = request.GET.copy()
    querystring.pop("page", None)

    context = {
        "page_obj": page,
        "products": page.object_list,
        "total_count": paginator.count,
        "querystring": querystring.urlencode(),
        "filters": {
            "q": request.GET.get("q", ""),
            "type": request.GET.get("type", ""),
            "care": request.GET.getlist("care"),
            "lighting": request.GET.getlist("lighting"),
            "flow": request.GET.getlist("flow"),
            "wysiwyg": request.GET.get("wysiwyg") == "1",
            "sale": request.GET.get("sale") == "1",
            "aquacultured": request.GET.get("aquacultured") == "1",
            "in_stock": request.GET.get("in_stock", "1") == "1",
            "min_price": request.GET.get("min_price", ""),
            "max_price": request.GET.get("max_price", ""),
            "sort": request.GET.get("sort", "newest"),
            "tag": request.GET.get("tag", ""),
        },
        "choices": {
            "types": ProductType.choices,
            "care": CareLevel.choices,
            "lighting": LightLevel.choices,
            "flow": FlowLevel.choices,
            "sorts": [(key, label) for key, (_, label) in SORT_OPTIONS.items()],
        },
        "tags": Tag.objects.all()[:20],
    }
    context.update(extra)
    return context


def shop(request):
    products = _filtered_products(request)
    context = _browse_context(
        request,
        products,
        heading="Shop everything",
        subheading="Aquacultured corals, captive-bred fish and the gear to keep them.",
    )
    return render(request, "catalog/shop.html", context)


def category_detail(request, slug):
    category = get_object_or_404(Category.objects.active(), slug=slug)
    base = Product.objects.for_storefront().filter(
        category_id__in=category.descendant_ids()
    )
    context = _browse_context(
        request,
        _filtered_products(request, base),
        category=category,
        heading=category.name,
        subheading=category.description,
    )
    return render(request, "catalog/shop.html", context)


def collection_detail(request, slug):
    collection = get_object_or_404(Collection, slug=slug, is_active=True)
    base = Product.objects.for_storefront().filter(collections=collection)
    context = _browse_context(
        request,
        _filtered_products(request, base),
        collection=collection,
        heading=collection.title,
        subheading=collection.subtitle,
    )
    return render(request, "catalog/shop.html", context)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images", "tags"),
        slug=slug,
    )
    if not product.is_published and not request.user.is_staff:
        from django.http import Http404

        raise Http404("No product matches the given query.")

    related = (
        Product.objects.for_storefront()
        .filter(category=product.category)
        .exclude(pk=product.pk)[:4]
    )
    return render(
        request,
        "catalog/product_detail.html",
        {"product": product, "related": related, "images": list(product.images.all())},
    )


def search(request):
    products = _filtered_products(request)
    query = request.GET.get("q", "").strip()
    context = _browse_context(
        request,
        products,
        heading=f'Search results for "{query}"' if query else "Search",
        subheading=None,
        is_search=True,
    )
    return render(request, "catalog/shop.html", context)
