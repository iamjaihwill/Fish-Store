"""Catalog administration — the merchandising half of the CMS."""

from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html
from django.utils.timezone import now

from apps.catalog.models import (
    BundleItem,
    Category,
    Collection,
    CollectionItem,
    Product,
    ProductImage,
    ProductType,
    ProductVariant,
    ProductVideo,
    Tag,
)


def thumbnail(image_field, size=56):
    if not image_field:
        return format_html(
            '<div style="width:{}px;height:{}px;border-radius:8px;'
            'background:#123;display:flex;align-items:center;justify-content:center;'
            'color:#5a8;font-size:10px">none</div>',
            size,
            size,
        )
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;'
        'border-radius:8px" />',
        image_field.url,
        size,
        size,
    )


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("preview", "image", "alt_text", "caption", "is_primary", "sort_order")
    readonly_fields = ("preview",)

    @admin.display(description="Preview")
    def preview(self, obj):
        return thumbnail(obj.image) if obj.pk else "—"


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = (
        "name", "sku", "price", "compare_at_price", "stock_quantity",
        "pack_quantity", "is_default", "is_active", "sort_order",
    )
    readonly_fields = ("sku",)


class ProductVideoInline(admin.TabularInline):
    model = ProductVideo
    extra = 0
    fields = ("title", "url", "thumbnail", "sort_order")


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    fk_name = "bundle"
    extra = 1
    autocomplete_fields = ["product"]
    verbose_name = "pack contents"
    verbose_name_plural = "pack contents"


class CollectionItemInline(admin.TabularInline):
    model = CollectionItem
    extra = 1
    autocomplete_fields = ["product"]


class StockFilter(admin.SimpleListFilter):
    title = "stock"
    parameter_name = "stock"

    def lookups(self, request, model_admin):
        return [
            ("in", "In stock"),
            ("low", "Low stock"),
            ("out", "Sold out"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "in":
            return queryset.in_stock()
        if self.value() == "out":
            return queryset.sold_out()
        if self.value() == "low":
            return queryset.filter(
                track_inventory=True, stock_quantity__gt=0, stock_quantity__lte=2
            )
        return queryset


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "image_tag",
        "__str__",
        "product_type",
        "product_count",
        "show_in_nav",
        "is_active",
        "sort_order",
    )
    list_display_links = ("image_tag", "__str__")
    list_editable = ("show_in_nav", "is_active", "sort_order")
    list_filter = ("product_type", "is_active", "show_in_nav")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_count=Count("products"))

    @admin.display(description="")
    def image_tag(self, obj):
        return thumbnail(obj.image, 40)

    @admin.display(description="Products", ordering="_count")
    def product_count(self, obj):
        return obj._count


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "image_tag",
        "name",
        "category",
        "price_tag",
        "stock_tag",
        "flags",
        "status",
        "is_featured",
    )
    list_display_links = ("image_tag", "name")
    list_editable = ("status", "is_featured")
    list_filter = (
        "status",
        "product_type",
        StockFilter,
        "is_wysiwyg",
        "is_featured",
        "care_level",
        "lighting",
        "flow",
        "is_aquacultured",
        "category",
    )
    search_fields = ("name", "sku", "scientific_name", "tagline", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["category", "tags"]
    inlines = [ProductImageInline, ProductVariantInline, ProductVideoInline, BundleItemInline]
    save_on_top = True
    list_per_page = 40
    date_hierarchy = "published_at"
    actions = [
        "publish",
        "unpublish",
        "feature",
        "unfeature",
        "mark_sold_out",
        "restock_one",
    ]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "sku",
                    ("category", "product_type"),
                    "tags",
                    "tagline",
                    "scientific_name",
                    "description",
                )
            },
        ),
        (
            "Pricing",
            {"fields": (("price", "compare_at_price"),)},
        ),
        (
            "Inventory",
            {
                "fields": (
                    "is_wysiwyg",
                    ("track_inventory", "stock_quantity", "low_stock_threshold"),
                ),
                "description": "A WYSIWYG listing is a single physical animal: "
                "quantity is capped at one automatically.",
            },
        ),
        (
            "Reef care",
            {
                "fields": (
                    ("care_level", "lighting", "flow", "placement"),
                    ("temperament", "reef_safe"),
                    ("diet", "max_size", "min_tank_size_gallons"),
                    ("is_aquacultured", "is_captive_bred"),
                    "requires_overnight_shipping",
                    "acclimation_notes",
                ),
                "classes": ("collapse",),
                "description": "Livestock only — leave blank for dry goods.",
            },
        ),
        (
            "Frag pack / bundle",
            {
                "fields": (("is_mystery", "bundle_size"),),
                "classes": ("collapse",),
                "description": "Only used when the product type is a bundle. "
                "List the contents in the 'pack contents' rows below, or tick "
                "mystery to keep them a surprise.",
            },
        ),
        (
            "Merchandising",
            {"fields": (("status", "is_featured"), "badge", "published_at")},
        ),
    )

    @admin.display(description="")
    def image_tag(self, obj):
        return thumbnail(obj.primary_image.image if obj.primary_image else None, 48)

    @admin.display(description="Price", ordering="price")
    def price_tag(self, obj):
        if obj.is_on_sale:
            return format_html(
                '<span style="color:#e06;font-weight:600">${}</span> '
                '<s style="opacity:.6">${}</s>',
                obj.price,
                obj.compare_at_price,
            )
        return format_html("${}", obj.price)

    @admin.display(description="Stock", ordering="stock_quantity")
    def stock_tag(self, obj):
        if obj.has_variants:
            total = obj.available_quantity
            color = "#c33" if total == 0 else "#2a8"
            return format_html(
                '<b style="color:{}">{}</b> <span style="opacity:.7">in {} options</span>',
                color, total, len(obj.sellable_variants),
            )
        if not obj.track_inventory:
            return format_html('<span style="opacity:.7">untracked</span>')
        if obj.is_sold_out:
            return format_html('<b style="color:#c33">sold out</b>')
        color = "#e8a" if obj.is_low_stock else "#2a8"
        return format_html('<b style="color:{}">{}</b>', color, obj.stock_quantity)

    @admin.display(description="Flags")
    def flags(self, obj):
        badges = []
        if obj.is_wysiwyg:
            badges.append(("WYSIWYG", "#2f6fed"))
        if obj.is_aquacultured:
            badges.append(("Aquacultured", "#12855f"))
        if obj.is_on_sale:
            badges.append((f"-{obj.discount_percent}%", "#c2185b"))
        if not badges:
            return "—"
        return format_html(
            " ".join(
                '<span style="background:{};color:#fff;border-radius:6px;'
                'padding:1px 6px;font-size:10px">{}</span>'.format(color, label)
                for label, color in badges
            )
        )

    # --- bulk actions ----------------------------------------------------
    @admin.action(description="Publish selected products")
    def publish(self, request, queryset):
        updated = queryset.update(status=Product.Status.ACTIVE, published_at=now())
        self.message_user(request, f"Published {updated} products.", messages.SUCCESS)

    @admin.action(description="Move selected products to draft")
    def unpublish(self, request, queryset):
        updated = queryset.update(status=Product.Status.DRAFT)
        self.message_user(request, f"{updated} products moved to draft.")

    @admin.action(description="Feature on the homepage")
    def feature(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"Featured {updated} products.")

    @admin.action(description="Remove from featured")
    def unfeature(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f"Unfeatured {updated} products.")

    @admin.action(description="Mark sold out (stock 0)")
    def mark_sold_out(self, request, queryset):
        updated = queryset.update(stock_quantity=0, track_inventory=True)
        self.message_user(request, f"Marked {updated} products sold out.")

    @admin.action(description="Restock to 1 (WYSIWYG relist)")
    def restock_one(self, request, queryset):
        updated = queryset.update(stock_quantity=1, track_inventory=True)
        self.message_user(request, f"Restocked {updated} products to one unit.")

    def get_changeform_initial_data(self, request):
        return {"published_at": now(), "product_type": ProductType.CORAL}


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("image_tag", "title", "item_count", "show_on_homepage", "is_active", "sort_order")
    list_display_links = ("image_tag", "title")
    list_editable = ("show_on_homepage", "is_active", "sort_order")
    list_filter = ("is_active", "show_on_homepage")
    search_fields = ("title", "subtitle", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [CollectionItemInline]

    @admin.display(description="")
    def image_tag(self, obj):
        return thumbnail(obj.image, 40)

    @admin.display(description="Products")
    def item_count(self, obj):
        return obj.products.count()


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Standalone view for bulk stock edits across every option."""

    list_display = ("product", "name", "sku", "price", "stock_quantity", "is_default", "is_active")
    list_editable = ("price", "stock_quantity", "is_default", "is_active")
    list_filter = ("is_active", "is_default", "product__product_type")
    search_fields = ("product__name", "name", "sku")
    autocomplete_fields = ["product"]
