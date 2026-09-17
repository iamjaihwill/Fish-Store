from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from apps.reviews.models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "stars_tag", "author_name", "verified", "status", "created_at")
    list_filter = ("status", "rating", "is_verified_purchase", "created_at")
    search_fields = ("product__name", "author_name", "author_email", "title", "body")
    autocomplete_fields = ["product", "customer"]
    readonly_fields = ("created_at", "photo_preview")
    actions = ["approve", "reject"]
    fieldsets = (
        (None, {"fields": (("product", "status"), ("rating", "is_verified_purchase"))}),
        ("Reviewer", {"fields": (("author_name", "author_email"), "customer")}),
        ("Content", {"fields": ("title", "body", "photo", "photo_preview")}),
        ("Shop response", {"fields": ("staff_reply",)}),
        ("Dates", {"fields": (("created_at", "published_at"),)}),
    )

    @admin.display(description="Rating", ordering="rating")
    def stars_tag(self, obj):
        return format_html(
            '<span style="color:#f5c76e">{}</span><span style="opacity:.3">{}</span>',
            "★" * obj.rating,
            "★" * (5 - obj.rating),
        )

    @admin.display(description="Verified", boolean=True)
    def verified(self, obj):
        return obj.is_verified_purchase

    @admin.display(description="Photo")
    def photo_preview(self, obj):
        if not obj.photo:
            return "—"
        return format_html('<img src="{}" style="max-width:320px;border-radius:10px">', obj.photo.url)

    @admin.action(description="Publish selected reviews")
    def approve(self, request, queryset):
        updated = queryset.update(
            status=Review.Status.APPROVED, published_at=timezone.now()
        )
        self.message_user(request, f"Published {updated} reviews.", messages.SUCCESS)

    @admin.action(description="Reject selected reviews")
    def reject(self, request, queryset):
        updated = queryset.update(status=Review.Status.REJECTED)
        self.message_user(request, f"Rejected {updated} reviews.")
