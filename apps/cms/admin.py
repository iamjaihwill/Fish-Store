"""Content administration — the site-building half of the CMS."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.catalog.admin import thumbnail
from apps.cms.models import (
    Article,
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
)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Singleton: staff edit the one record instead of creating rows."""

    fieldsets = (
        ("Identity", {"fields": ("store_name", "tagline", "logo")}),
        (
            "Announcement bar",
            {"fields": ("announcement_enabled", "announcement_text", "announcement_url")},
        ),
        (
            "Shipping & money",
            {
                "fields": (
                    ("free_shipping_threshold", "tax_rate_percent"),
                    ("livestock_shipping_rate", "drygoods_shipping_rate"),
                    "shipping_days",
                    ("shipping_weekdays", "shipping_cutoff_time"),
                    ("wholesale_discount_percent", "allow_order_additions"),
                    ("guarantee_headline", "guarantee_blurb"),
                )
            },
        ),
        (
            "Contact",
            {"fields": ("contact_email", "contact_phone", "hours", "address")},
        ),
        (
            "Social",
            {"fields": ("instagram_url", "youtube_url", "facebook_url", "tiktok_url")},
        ),
        ("Footer", {"fields": ("footer_note",)}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        settings_obj = SiteSettings.load()
        from django.shortcuts import redirect

        return redirect(
            reverse("admin:cms_sitesettings_change", args=[settings_obj.pk])
        )


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ("image_tag", "headline", "is_active", "live_now", "sort_order")
    list_display_links = ("image_tag", "headline")
    list_editable = ("is_active", "sort_order")
    fieldsets = (
        (None, {"fields": ("eyebrow", "headline", "subhead", "image")}),
        (
            "Buttons",
            {
                "fields": (
                    ("cta_label", "cta_url"),
                    ("secondary_cta_label", "secondary_cta_url"),
                )
            },
        ),
        ("Scheduling", {"fields": ("is_active", ("starts_at", "ends_at"), "sort_order")}),
    )

    @admin.display(description="")
    def image_tag(self, obj):
        return thumbnail(obj.image, 60)

    @admin.display(boolean=True, description="Live")
    def live_now(self, obj):
        return obj.is_live


@admin.register(HomepageSection)
class HomepageSectionAdmin(admin.ModelAdmin):
    list_display = ("heading_or_kind", "kind", "collection", "max_items", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    list_filter = ("kind", "is_active")
    autocomplete_fields = ["collection"]
    fieldsets = (
        (None, {"fields": ("kind", "heading", "subheading")}),
        (
            "Content",
            {
                "fields": ("collection", "max_items", "body"),
                "description": "Pick a collection for the 'Specific collection' kind; "
                "body copy is only used by the rich text band.",
            },
        ),
        ("Call to action", {"fields": (("cta_label", "cta_url"),)}),
        ("Placement", {"fields": ("is_active", "sort_order")}),
    )

    @admin.display(description="Section")
    def heading_or_kind(self, obj):
        return obj.heading or obj.get_kind_display()


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "show_in_header", "show_in_footer", "updated_at")
    list_editable = ("is_published", "show_in_header", "show_in_footer")
    list_filter = ("is_published", "show_in_header", "show_in_footer")
    search_fields = ("title", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {"fields": ("title", "slug", "summary", "hero_image", "body")}),
        (
            "Placement",
            {"fields": ("is_published", ("show_in_header", "show_in_footer"), "sort_order")},
        ),
        ("SEO", {"fields": ("seo_title", "seo_description"), "classes": ("collapse",)}),
    )

    @admin.display(description="View")
    def view_link(self, obj):
        return format_html('<a href="{}" target="_blank">Open</a>', obj.get_absolute_url())


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    list_display = ("question", "topic", "is_active", "sort_order")
    list_editable = ("topic", "is_active", "sort_order")
    list_filter = ("topic", "is_active")
    search_fields = ("question", "answer")


@admin.register(NavigationLink)
class NavigationLinkAdmin(admin.ModelAdmin):
    list_display = ("label", "placement", "target", "is_active", "sort_order")
    list_editable = ("placement", "is_active", "sort_order")
    list_filter = ("placement", "is_active")
    autocomplete_fields = ["page"]

    @admin.display(description="Target")
    def target(self, obj):
        return obj.href or "—"


@admin.register(LiveSaleEvent)
class LiveSaleEventAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "ends_at", "state", "is_active")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    date_hierarchy = "starts_at"
    autocomplete_fields = ["collection"]
    prepopulated_fields = {"slug": ("title",)}

    @admin.display(description="State")
    def state(self, obj):
        if obj.is_running:
            return "Live now"
        return "Upcoming" if obj.is_upcoming else "Ended"


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author", "location", "rating", "is_active", "sort_order")
    list_editable = ("rating", "is_active", "sort_order")
    list_filter = ("rating", "is_active")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "email", "subject", "order_reference", "is_handled")
    list_editable = ("is_handled",)
    list_filter = ("is_handled", "created_at")
    search_fields = ("name", "email", "subject", "message", "order_reference")
    readonly_fields = ("name", "email", "subject", "message", "order_reference", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at", "is_active")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("email",)
    actions = ["export_emails"]

    @admin.action(description="Show selected addresses for export")
    def export_emails(self, request, queryset):
        self.message_user(
            request, ", ".join(queryset.values_list("email", flat=True))
        )


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "author", "is_published", "published_at")
    list_editable = ("category", "is_published")
    list_filter = ("category", "is_published", "published_at")
    search_fields = ("title", "summary", "body", "author")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ["related_products"]
    date_hierarchy = "published_at"
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "author", "summary", "hero_image")}),
        ("Body", {"fields": ("body", "related_products")}),
        ("Publishing", {"fields": ("is_published", "published_at")}),
        ("SEO", {"fields": ("seo_title", "seo_description"), "classes": ("collapse",)}),
    )
