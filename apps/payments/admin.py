from django.contrib import admin, messages
from django.utils.html import format_html

from apps.payments.models import Payment, Refund


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "status_tag", "amount", "method", "provider", "reference", "created_at")
    list_filter = ("status", "method", "provider", "created_at")
    search_fields = ("order__number", "reference", "order__email")
    autocomplete_fields = ["order"]
    readonly_fields = ("created_at", "paid_at", "raw_response", "client_secret")
    inlines = [RefundInline]
    actions = ["mark_paid_action", "refund_action"]

    @admin.display(description="Status", ordering="status")
    def status_tag(self, obj):
        colors = {
            Payment.Status.PAID: "#2a8",
            Payment.Status.PENDING: "#a67",
            Payment.Status.REQUIRES_ACTION: "#b8860b",
            Payment.Status.FAILED: "#c33",
            Payment.Status.REFUNDED: "#777",
            Payment.Status.CANCELLED: "#777",
        }
        return format_html(
            '<span style="background:{};color:#fff;border-radius:6px;padding:2px 8px;font-size:11px">{}</span>',
            colors.get(obj.status, "#555"),
            obj.get_status_display(),
        )

    @admin.action(description="Record as paid (money received off-site)")
    def mark_paid_action(self, request, queryset):
        count = 0
        for payment in queryset.exclude(status=Payment.Status.PAID):
            payment.mark_paid()
            count += 1
        self.message_user(request, f"Recorded {count} payments as paid.", messages.SUCCESS)

    @admin.action(description="Refund through the provider")
    def refund_action(self, request, queryset):
        from apps.payments.gateway import get_backend

        backend = get_backend()
        refunded = failed = 0
        for payment in queryset.filter(status=Payment.Status.PAID):
            result = backend.refund(payment, payment.amount)
            if result.success:
                Refund.objects.create(
                    payment=payment, amount=payment.amount, reference=result.reference
                )
                payment.status = Payment.Status.REFUNDED
                payment.save(update_fields=["status"])
                refunded += 1
            else:
                failed += 1
        if refunded:
            self.message_user(request, f"Refunded {refunded} payments.", messages.SUCCESS)
        if failed:
            self.message_user(request, f"{failed} refunds failed.", messages.ERROR)
