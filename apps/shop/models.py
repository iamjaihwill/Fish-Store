"""Ordering: carts become orders, orders get packed and shipped.

Livestock ordering differs from ordinary retail in ways that are modelled here
rather than bolted on: overnight-only shipping, a requested ship date because
the customer has to be home to receive the box, weather holds, and a dead on
arrival claim window that opens when the box is delivered.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

MONEY = {"max_digits": 10, "decimal_places": 2}
ZERO = Decimal("0.00")


class OrderQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(
            status__in=[Order.Status.DELIVERED, Order.Status.CANCELLED, Order.Status.REFUNDED]
        )

    def needs_packing(self):
        return self.filter(status__in=[Order.Status.PAID, Order.Status.PACKING])


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting payment"
        PAID = "paid", "Paid"
        PACKING = "packing", "Packing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    number = models.CharField(max_length=20, unique=True, editable=False)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )

    # Customer
    customer = models.ForeignKey(
        "accounts.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="linked_orders",
        help_text="Set when the order was placed by a signed-in account.",
    )
    email = models.EmailField()
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(
        max_length=40,
        help_text="Required by the carrier for overnight livestock delivery.",
    )

    # Shipping address
    address_line1 = models.CharField(max_length=160)
    address_line2 = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=40)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=60, default="United States")

    # Livestock logistics
    contains_livestock = models.BooleanField(default=False)
    requested_ship_date = models.DateField(
        null=True,
        blank=True,
        help_text="Customer's preferred departure day, subject to the shipping calendar.",
    )
    hold_for_weather = models.BooleanField(
        default=False,
        help_text="Customer asked us to hold the box until temperatures are safe.",
    )
    customer_notes = models.TextField(blank=True)
    staff_notes = models.TextField(blank=True)

    # Money (snapshotted at checkout)
    subtotal = models.DecimalField(**MONEY, default=ZERO)
    discount_total = models.DecimalField(**MONEY, default=ZERO)
    shipping_total = models.DecimalField(**MONEY, default=ZERO)
    tax_total = models.DecimalField(**MONEY, default=ZERO)
    points_redeemed = models.PositiveIntegerField(default=0)
    points_value = models.DecimalField(**MONEY, default=ZERO)
    gift_card_total = models.DecimalField(**MONEY, default=ZERO)
    grand_total = models.DecimalField(
        **MONEY, default=ZERO, help_text="Amount actually payable after credits."
    )
    discount_code = models.ForeignKey(
        "rewards.DiscountCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    # Fulfillment
    carrier = models.CharField(max_length=40, blank=True)
    tracking_number = models.CharField(max_length=80, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._generate_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_number():
        stamp = timezone.now().strftime("%y%m")
        while True:
            candidate = f"RR-{stamp}-{get_random_string(4, '0123456789')}"
            if not Order.objects.filter(number=candidate).exists():
                return candidate

    def get_absolute_url(self):
        return reverse("shop:order_detail", args=[self.number])

    @property
    def customer_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def shipping_address_lines(self):
        lines = [self.address_line1]
        if self.address_line2:
            lines.append(self.address_line2)
        lines.append(f"{self.city}, {self.state} {self.postal_code}")
        lines.append(self.country)
        return lines

    @property
    def is_cancellable(self):
        return self.status in {self.Status.PENDING, self.Status.PAID}

    @property
    def doa_window_closes_at(self):
        """Live arrival claims must be filed within 8 hours of delivery."""
        if not self.delivered_at:
            return None
        return self.delivered_at + timezone.timedelta(hours=8)

    @property
    def doa_window_open(self):
        closes = self.doa_window_closes_at
        return bool(closes and timezone.now() <= closes)

    @property
    def credits_applied(self):
        return self.discount_total + self.points_value + self.gift_card_total

    def recalculate(self, *, save=True):
        """Recompute money fields from the current line items.

        Credits already recorded on the order (a discount code, redeemed points,
        gift cards) are preserved and re-applied, so adding a line to an order
        later cannot silently drop them.
        """
        from apps.cms.models import SiteSettings

        settings_obj = SiteSettings.load()
        self.subtotal = sum(
            (item.line_total for item in self.items.all()), start=ZERO
        )
        self.contains_livestock = self.items.filter(is_livestock=True).exists()
        self.shipping_total = quote_shipping(
            self.subtotal, self.contains_livestock, settings_obj
        )
        self.tax_total = (
            (self.subtotal - self.discount_total)
            * settings_obj.tax_rate_percent
            / Decimal("100")
        ).quantize(Decimal("0.01"))
        payable = (
            self.subtotal
            - self.discount_total
            + self.shipping_total
            + self.tax_total
            - self.points_value
            - self.gift_card_total
        )
        self.grand_total = max(payable, ZERO).quantize(Decimal("0.01"))
        if save:
            self.save(
                update_fields=[
                    "subtotal",
                    "shipping_total",
                    "tax_total",
                    "grand_total",
                    "contains_livestock",
                    "updated_at",
                ]
            )
        return self.grand_total

    def mark_paid(self):
        """Move a pending order to paid. Never downgrades a later status."""
        if self.status != self.Status.PENDING:
            return self
        self.status = self.Status.PAID
        self.save(update_fields=["status", "updated_at"])
        return self

    @property
    def is_paid(self):
        return self.status not in {self.Status.PENDING, self.Status.CANCELLED}

    @property
    def amount_outstanding(self):
        from apps.payments.models import Payment

        if self.is_paid:
            return ZERO
        settled = sum(
            (p.amount for p in self.payments.filter(status=Payment.Status.PAID)),
            start=ZERO,
        )
        return max(self.grand_total - settled, ZERO)

    def mark_shipped(self, carrier="", tracking_number=""):
        self.status = self.Status.SHIPPED
        self.carrier = carrier or self.carrier
        self.tracking_number = tracking_number or self.tracking_number
        self.shipped_at = self.shipped_at or timezone.now()
        self.save(
            update_fields=[
                "status",
                "carrier",
                "tracking_number",
                "shipped_at",
                "updated_at",
            ]
        )

    def restock(self):
        """Return reserved inventory to the catalog (cancellations/refunds)."""
        from apps.catalog.models import Product

        from apps.catalog.models import ProductVariant

        for item in self.items.select_related("product", "variant"):
            if item.variant_id:
                if item.variant.track_inventory:
                    ProductVariant.objects.filter(pk=item.variant_id).update(
                        stock_quantity=models.F("stock_quantity") + item.quantity
                    )
            elif item.product_id and item.product.track_inventory:
                Product.objects.filter(pk=item.product_id).update(
                    stock_quantity=models.F("stock_quantity") + item.quantity
                )


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    # Snapshots so history survives catalog edits and deletions.
    name = models.CharField(max_length=180)
    variant_name = models.CharField(max_length=80, blank=True)
    sku = models.CharField(max_length=40, blank=True)
    unit_price = models.DecimalField(**MONEY)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    is_livestock = models.BooleanField(default=False)
    is_wysiwyg = models.BooleanField(default=False)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        if self.variant_name:
            return f"{self.quantity} x {self.name} ({self.variant_name})"
        return f"{self.quantity} x {self.name}"

    @property
    def display_name(self):
        return f"{self.name} ({self.variant_name})" if self.variant_name else self.name

    @property
    def line_total(self):
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))


class DoaClaim(models.Model):
    """A dead-on-arrival claim filed against a delivered order."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="doa_claims")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SUBMITTED
    )
    items_affected = models.CharField(
        max_length=240, help_text="Which animals arrived in distress."
    )
    details = models.TextField(
        help_text="Water parameters, acclimation steps, time of delivery."
    )
    photo = models.ImageField(upload_to="doa/", blank=True)
    credit_amount = models.DecimalField(**MONEY, default=ZERO)
    staff_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "DOA claim"

    def __str__(self):
        return f"DOA claim for {self.order.number}"


def quote_shipping(subtotal, contains_livestock, settings_obj=None):
    """Shipping quote for a subtotal.

    Livestock always moves overnight at the livestock rate; dry-goods-only
    orders take the flat parcel rate. Either becomes free once the order clears
    the free-shipping threshold.
    """
    from apps.cms.models import SiteSettings

    settings_obj = settings_obj or SiteSettings.load()
    if subtotal <= ZERO:
        return ZERO
    threshold = settings_obj.free_shipping_threshold
    if threshold and subtotal >= threshold:
        return ZERO
    rate = (
        settings_obj.livestock_shipping_rate
        if contains_livestock
        else settings_obj.drygoods_shipping_rate
    )
    return Decimal(rate).quantize(Decimal("0.01"))
