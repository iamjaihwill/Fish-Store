from django.contrib import admin, messages
from django.utils import timezone

from apps.accounts.models import Address, Customer, WishlistItem


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("__str__", "email", "tier", "wholesale_state", "accepts_marketing", "created_at")
    list_filter = ("tier", "accepts_marketing", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "wholesale_company")
    autocomplete_fields = ["user"]
    inlines = [AddressInline]
    actions = ["approve_wholesale", "revoke_wholesale"]
    readonly_fields = ("created_at",)

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="Wholesale")
    def wholesale_state(self, obj):
        if obj.tier != Customer.Tier.WHOLESALE:
            return "—"
        return "Approved" if obj.wholesale_approved_at else "Pending review"

    @admin.action(description="Approve wholesale access")
    def approve_wholesale(self, request, queryset):
        updated = queryset.update(
            tier=Customer.Tier.WHOLESALE, wholesale_approved_at=timezone.now()
        )
        self.message_user(request, f"Approved {updated} wholesale accounts.", messages.SUCCESS)

    @admin.action(description="Revoke wholesale access")
    def revoke_wholesale(self, request, queryset):
        updated = queryset.update(tier=Customer.Tier.RETAIL, wholesale_approved_at=None)
        self.message_user(request, f"Reverted {updated} accounts to retail.")


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("customer", "product", "notify_when_available", "notified_at", "created_at")
    list_filter = ("notify_when_available", "created_at")
    search_fields = ("customer__user__email", "product__name")
    autocomplete_fields = ["customer", "product"]
