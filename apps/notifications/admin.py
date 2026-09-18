from django.contrib import admin, messages
from django.utils.html import format_html

from apps.notifications.defaults import DEFAULT_TEMPLATES
from apps.notifications.models import AbandonedCart, EmailLog, EmailTemplate

#: What each template can reference, shown to staff while they edit.
TEMPLATE_VARIABLES = {
    "welcome": "first_name, claimed, site, rewards",
    "order_confirmation": "order, order_url, site",
    "payment_received": "order, payment, order_url, site",
    "order_shipped": "order, order_url, site",
    "order_delivered": "order, claim_url, site",
    "doa_received": "order, claim, site",
    "doa_resolved": "order, claim, site",
    "review_request": "order, base_url, site",
    "abandoned_cart": "items, subtotal, wysiwyg, first_name, recovery_url, site",
    "back_in_stock": "product, item, product_url, site",
    "points_expiring": "first_name, points, expires_on, value, shop_url, site",
    "gift_card_issued": "card, site",
}


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("__str__", "subject", "is_active", "customised", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("key", "subject", "body")
    actions = ["reset_selected", "seed_all"]

    @admin.display(description="Customised", boolean=True)
    def customised(self, obj):
        default = DEFAULT_TEMPLATES.get(obj.key, {})
        return obj.subject != default.get("subject") or obj.body != default.get("body")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.key in TEMPLATE_VARIABLES:
            help_text = format_html(
                "Available variables: <code>{}</code>",
                TEMPLATE_VARIABLES[obj.key],
            )
            form.base_fields["body"].help_text = help_text
        return form

    @admin.action(description="Reset selected templates to the built-in wording")
    def reset_selected(self, request, queryset):
        count = sum(1 for template in queryset if template.reset_to_default())
        self.message_user(request, f"Reset {count} templates.", messages.WARNING)

    @admin.action(description="Create rows for any missing built-in templates")
    def seed_all(self, request, queryset):
        created = EmailTemplate.seed_defaults()
        self.message_user(
            request,
            f"Added {created} templates." if created else "Every template already exists.",
            messages.SUCCESS,
        )


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "key", "recipient", "subject", "status_tag")
    list_filter = ("key", "status", "created_at")
    search_fields = ("recipient", "subject", "body", "order__number", "dedupe_key")
    readonly_fields = (
        "key", "recipient", "subject", "body", "status", "dedupe_key",
        "order", "customer", "error", "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Status", ordering="status")
    def status_tag(self, obj):
        colors = {
            EmailLog.Status.SENT: "#2a8",
            EmailLog.Status.FAILED: "#c33",
            EmailLog.Status.SKIPPED: "#777",
        }
        return format_html(
            '<span style="background:{};color:#fff;border-radius:6px;padding:2px 8px;'
            'font-size:11px">{}</span>',
            colors.get(obj.status, "#555"),
            obj.get_status_display(),
        )


@admin.register(AbandonedCart)
class AbandonedCartAdmin(admin.ModelAdmin):
    list_display = (
        "email", "subtotal", "item_count", "wysiwyg", "reminders_sent",
        "state", "updated_at",
    )
    list_filter = ("contains_wysiwyg", "reminders_sent", "recovered_at", "updated_at")
    search_fields = ("email", "customer__user__email")
    readonly_fields = (
        "token", "items", "subtotal", "contains_wysiwyg", "created_at",
        "updated_at", "recovery_link",
    )
    actions = ["send_reminder_now"]
    date_hierarchy = "updated_at"

    @admin.display(description="WYSIWYG", boolean=True)
    def wysiwyg(self, obj):
        return obj.contains_wysiwyg

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.item_count

    @admin.display(description="State")
    def state(self, obj):
        if obj.is_recovered:
            return format_html('<b style="color:#2a8">Recovered</b>')
        return "Open"

    @admin.display(description="Recovery link")
    def recovery_link(self, obj):
        url = obj.get_recovery_url()
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)

    @admin.action(description="Send a reminder now")
    def send_reminder_now(self, request, queryset):
        from apps.notifications.senders import send_abandoned_cart

        sent = 0
        for cart in queryset.filter(recovered_at__isnull=True):
            if send_abandoned_cart(cart) is not None:
                cart.record_reminder()
                sent += 1
        self.message_user(request, f"Sent {sent} reminders.", messages.SUCCESS)
