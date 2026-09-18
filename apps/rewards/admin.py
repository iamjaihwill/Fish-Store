from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from apps.rewards.models import (
    DiscountCode,
    DiscountRedemption,
    GiftCard,
    GiftCardTransaction,
    PointsTransaction,
    RewardsSettings,
    balance_for,
)


@admin.register(RewardsSettings)
class RewardsSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Programme", {"fields": ("is_enabled", "points_per_dollar", "cents_per_point")}),
        (
            "Rules",
            {"fields": ("expiry_days", "minimum_redemption", "redeemable_during_sales")},
        ),
    )

    def has_add_permission(self, request):
        return not RewardsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect(
            reverse("admin:rewards_rewardssettings_change", args=[RewardsSettings.load().pk])
        )


@admin.register(PointsTransaction)
class PointsTransactionAdmin(admin.ModelAdmin):
    list_display = ("customer", "kind", "points", "balance_after", "order", "expires_at", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("customer__user__email", "note", "order__number")
    autocomplete_fields = ["customer", "order"]
    readonly_fields = ("created_at",)

    @admin.display(description="Current balance")
    def balance_after(self, obj):
        return balance_for(obj.customer)


class GiftCardTransactionInline(admin.TabularInline):
    model = GiftCardTransaction
    extra = 0
    readonly_fields = ("amount", "order", "note", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GiftCard)
class GiftCardAdmin(admin.ModelAdmin):
    list_display = ("code", "balance_tag", "initial_balance", "issued_to", "is_active", "expires_at", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("code", "recipient_email", "issued_to__user__email")
    autocomplete_fields = ["issued_to", "purchased_with_order"]
    readonly_fields = ("code", "created_at")
    inlines = [GiftCardTransactionInline]
    actions = ["email_card", "deactivate"]

    @admin.display(description="Balance", ordering="balance")
    def balance_tag(self, obj):
        color = "#2a8" if obj.balance > 0 else "#777"
        return format_html('<b style="color:{}">${}</b>', color, obj.balance)

    @admin.action(description="Email the code to the recipient")
    def email_card(self, request, queryset):
        from apps.notifications.senders import send_gift_card

        sent = skipped = 0
        for card in queryset:
            if send_gift_card(card) is not None:
                sent += 1
            else:
                skipped += 1
        if sent:
            self.message_user(request, f"Emailed {sent} gift cards.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"{skipped} cards had no recipient email or were already sent.",
                messages.WARNING,
            )

    @admin.action(description="Deactivate selected gift cards")
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated} gift cards.", messages.WARNING)


class DiscountRedemptionInline(admin.TabularInline):
    model = DiscountRedemption
    extra = 0
    readonly_fields = ("customer", "order", "email", "amount", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "kind", "value", "usage", "live_now", "starts_at", "ends_at")
    list_filter = ("kind", "is_active", "excludes_livestock")
    search_fields = ("code", "description")
    inlines = [DiscountRedemptionInline]
    fieldsets = (
        (None, {"fields": ("code", "description", ("kind", "value"), "is_active")}),
        (
            "Conditions",
            {
                "fields": (
                    "minimum_subtotal",
                    ("max_uses", "max_uses_per_customer"),
                    "excludes_livestock",
                    ("starts_at", "ends_at"),
                )
            },
        ),
    )
    readonly_fields = ()

    @admin.display(description="Used")
    def usage(self, obj):
        return f"{obj.times_used}/{obj.max_uses}" if obj.max_uses else str(obj.times_used)

    @admin.display(description="Live", boolean=True)
    def live_now(self, obj):
        return obj.is_live
