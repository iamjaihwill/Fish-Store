"""Order administration — the fulfillment half of the CMS."""

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from apps.shop.models import DoaClaim, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("name", "sku", "unit_price", "quantity", "line_total_display", "is_livestock", "is_wysiwyg")
    readonly_fields = ("line_total_display",)
    autocomplete_fields = ["product"]

    @admin.display(description="Line total")
    def line_total_display(self, obj):
        return f"${obj.line_total}" if obj.pk else "—"


class DoaClaimInline(admin.TabularInline):
    model = DoaClaim
    extra = 0
    fields = ("created_at", "items_affected", "status", "credit_amount")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "created_at",
        "customer_name",
        "status_tag",
        "total_display",
        "livestock_tag",
        "ship_plan",
    )
    list_filter = ("status", "contains_livestock", "hold_for_weather", "created_at")
    search_fields = ("number", "email", "first_name", "last_name", "tracking_number")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline, DoaClaimInline]
    readonly_fields = (
        "number",
        "created_at",
        "updated_at",
        "subtotal",
        "shipping_total",
        "tax_total",
        "grand_total",
    )
    actions = ["mark_paid", "mark_packing", "mark_shipped_action", "mark_delivered", "cancel_and_restock"]
    save_on_top = True

    fieldsets = (
        (None, {"fields": (("number", "status"), ("created_at", "updated_at"))}),
        (
            "Customer",
            {"fields": (("first_name", "last_name"), ("email", "phone"))},
        ),
        (
            "Ship to",
            {
                "fields": (
                    "address_line1",
                    "address_line2",
                    ("city", "state", "postal_code"),
                    "country",
                )
            },
        ),
        (
            "Livestock logistics",
            {
                "fields": (
                    ("contains_livestock", "hold_for_weather"),
                    "requested_ship_date",
                    ("carrier", "tracking_number"),
                    ("shipped_at", "delivered_at"),
                )
            },
        ),
        (
            "Totals",
            {"fields": (("subtotal", "shipping_total"), ("tax_total", "grand_total"))},
        ),
        ("Notes", {"fields": ("customer_notes", "staff_notes")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_tag(self, obj):
        colors = {
            Order.Status.PENDING: "#a67",
            Order.Status.PAID: "#2f6fed",
            Order.Status.PACKING: "#b8860b",
            Order.Status.SHIPPED: "#12855f",
            Order.Status.DELIVERED: "#2a8",
            Order.Status.CANCELLED: "#c33",
            Order.Status.REFUNDED: "#777",
        }
        return format_html(
            '<span style="background:{};color:#fff;border-radius:6px;padding:2px 8px;'
            'font-size:11px">{}</span>',
            colors.get(obj.status, "#555"),
            obj.get_status_display(),
        )

    @admin.display(description="Total", ordering="grand_total")
    def total_display(self, obj):
        return f"${obj.grand_total}"

    @admin.display(description="Livestock", boolean=True)
    def livestock_tag(self, obj):
        return obj.contains_livestock

    @admin.display(description="Ship plan")
    def ship_plan(self, obj):
        if obj.hold_for_weather:
            return format_html('<b style="color:#b8860b">weather hold</b>')
        if obj.requested_ship_date:
            return obj.requested_ship_date.strftime("%b %d")
        return "next ship day"

    # --- fulfillment actions ---------------------------------------------
    @admin.action(description="Mark as paid")
    def mark_paid(self, request, queryset):
        updated = queryset.update(status=Order.Status.PAID)
        self.message_user(request, f"{updated} orders marked paid.", messages.SUCCESS)

    @admin.action(description="Move to packing")
    def mark_packing(self, request, queryset):
        updated = queryset.update(status=Order.Status.PACKING)
        self.message_user(request, f"{updated} orders are being packed.")

    @admin.action(description="Mark as shipped")
    def mark_shipped_action(self, request, queryset):
        count = 0
        for order in queryset:
            order.mark_shipped()
            count += 1
        self.message_user(request, f"{count} orders marked shipped.", messages.SUCCESS)

    @admin.action(description="Mark as delivered (opens the DOA window)")
    def mark_delivered(self, request, queryset):
        updated = queryset.update(
            status=Order.Status.DELIVERED, delivered_at=timezone.now()
        )
        self.message_user(request, f"{updated} orders marked delivered.")

    @admin.action(description="Cancel and return stock to the catalog")
    def cancel_and_restock(self, request, queryset):
        count = 0
        for order in queryset:
            if order.status == Order.Status.CANCELLED:
                continue
            order.restock()
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status", "updated_at"])
            count += 1
        self.message_user(
            request, f"Cancelled {count} orders and restocked their items.", messages.WARNING
        )


@admin.register(DoaClaim)
class DoaClaimAdmin(admin.ModelAdmin):
    list_display = ("order", "created_at", "items_affected", "status", "credit_amount")
    list_filter = ("status", "created_at")
    search_fields = ("order__number", "items_affected", "details")
    readonly_fields = ("created_at", "photo_preview")
    actions = ["approve", "deny"]
    fieldsets = (
        (None, {"fields": ("order", "status", "created_at")}),
        ("Claim", {"fields": ("items_affected", "details", "photo", "photo_preview")}),
        ("Resolution", {"fields": ("credit_amount", "staff_notes", "resolved_at")}),
    )

    @admin.display(description="Photo")
    def photo_preview(self, obj):
        if not obj.photo:
            return "—"
        return format_html(
            '<img src="{}" style="max-width:360px;border-radius:10px" />', obj.photo.url
        )

    @admin.action(description="Approve claim")
    def approve(self, request, queryset):
        updated = queryset.update(
            status=DoaClaim.Status.APPROVED, resolved_at=timezone.now()
        )
        self.message_user(request, f"Approved {updated} claims.", messages.SUCCESS)

    @admin.action(description="Deny claim")
    def deny(self, request, queryset):
        updated = queryset.update(
            status=DoaClaim.Status.DENIED, resolved_at=timezone.now()
        )
        self.message_user(request, f"Denied {updated} claims.")
