"""Loyalty points, gift cards and discount codes.

The three are one subsystem because they all reduce what a customer pays and
all have to agree on the order they apply in: discount code first (it is a
percentage or amount off the goods), then points, then gift cards, which behave
like money and can cover shipping and tax.

Points follow the model these stores actually use: earned per dollar spent,
expiring a fixed number of days after they are earned, and not redeemable
during a live or flash sale.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

ZERO = Decimal("0.00")
MONEY = {"max_digits": 10, "decimal_places": 2}


def money(value):
    return Decimal(value).quantize(Decimal("0.01"))


class RewardsSettings(models.Model):
    """Singleton controlling how the points programme behaves."""

    points_per_dollar = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("1.00"),
        help_text="Points earned per dollar of merchandise.",
    )
    cents_per_point = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("0.05"),
        help_text="Redemption value of one point, in dollars (0.05 = 20 points per $1).",
    )
    expiry_days = models.PositiveIntegerField(
        default=180, help_text="Days until earned points expire. 0 disables expiry."
    )
    minimum_redemption = models.PositiveIntegerField(
        default=100, help_text="Fewest points that can be spent at once."
    )
    redeemable_during_sales = models.BooleanField(
        default=False,
        help_text="Allow point redemption while a live or flash sale is running.",
    )
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "rewards settings"
        verbose_name_plural = "rewards settings"

    def __str__(self):
        return "Rewards settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def points_for(self, amount):
        return int((Decimal(amount) * self.points_per_dollar).to_integral_value())

    def value_of(self, points):
        return money(Decimal(points) * self.cents_per_point)

    def points_needed_for(self, amount):
        if self.cents_per_point <= 0:
            return 0
        import math

        return int(math.ceil(Decimal(amount) / self.cents_per_point))


class PointsTransaction(models.Model):
    """Ledger row. A balance is the sum of its unexpired rows."""

    class Kind(models.TextChoices):
        EARNED = "earned", "Earned"
        REDEEMED = "redeemed", "Redeemed"
        EXPIRED = "expired", "Expired"
        ADJUSTMENT = "adjustment", "Manual adjustment"
        REFUNDED = "refunded", "Returned from a cancelled order"

    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.CASCADE, related_name="points"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    points = models.IntegerField(help_text="Positive to credit, negative to debit.")
    order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="points_transactions",
    )
    note = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer}: {self.points:+d} ({self.get_kind_display()})"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())


def balance_for(customer):
    """Unexpired point balance."""
    if customer is None:
        return 0
    now = timezone.now()
    rows = PointsTransaction.objects.filter(customer=customer).filter(
        models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
    )
    return rows.aggregate(total=models.Sum("points"))["total"] or 0


def award_points(customer, order, *, settings_obj=None):
    """Credit points for a paid order. Idempotent per order."""
    if customer is None:
        return None
    settings_obj = settings_obj or RewardsSettings.load()
    if not settings_obj.is_enabled:
        return None
    if PointsTransaction.objects.filter(
        customer=customer, order=order, kind=PointsTransaction.Kind.EARNED
    ).exists():
        return None

    earned = settings_obj.points_for(order.subtotal)
    if earned <= 0:
        return None
    expires_at = (
        timezone.now() + timedelta(days=settings_obj.expiry_days)
        if settings_obj.expiry_days
        else None
    )
    return PointsTransaction.objects.create(
        customer=customer,
        kind=PointsTransaction.Kind.EARNED,
        points=earned,
        order=order,
        expires_at=expires_at,
        note=f"Order {order.number}",
    )


def redeem_points(customer, points, order=None, note=""):
    """Debit points. Raises ValidationError if the balance cannot cover it."""
    if points <= 0:
        raise ValidationError("Redeem a positive number of points.")
    if balance_for(customer) < points:
        raise ValidationError("Not enough points.")
    return PointsTransaction.objects.create(
        customer=customer,
        kind=PointsTransaction.Kind.REDEEMED,
        points=-points,
        order=order,
        note=note or (f"Order {order.number}" if order else "Redemption"),
    )


def expire_points(customer=None):
    """Write explicit expiry rows so the ledger reads honestly.

    ``balance_for`` already ignores expired rows; this makes the expiry visible
    in a customer's history rather than having points quietly vanish.
    """
    now = timezone.now()
    query = PointsTransaction.objects.filter(
        kind=PointsTransaction.Kind.EARNED, expires_at__lte=now
    )
    if customer is not None:
        query = query.filter(customer=customer)

    written = 0
    for row in query.select_related("customer"):
        already = PointsTransaction.objects.filter(
            customer=row.customer,
            kind=PointsTransaction.Kind.EXPIRED,
            note=f"Expiry of transaction {row.pk}",
        ).exists()
        if already:
            continue
        PointsTransaction.objects.create(
            customer=row.customer,
            kind=PointsTransaction.Kind.EXPIRED,
            points=0,  # balance_for already excludes the expired row
            note=f"Expiry of transaction {row.pk}",
        )
        written += 1
    return written


class GiftCard(models.Model):
    """Prepaid balance. Behaves like money: covers goods, shipping and tax."""

    code = models.CharField(max_length=24, unique=True, blank=True)
    initial_balance = models.DecimalField(**MONEY)
    balance = models.DecimalField(**MONEY)
    recipient_email = models.EmailField(blank=True)
    message = models.CharField(max_length=240, blank=True)
    issued_to = models.ForeignKey(
        "accounts.Customer", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="gift_cards",
    )
    purchased_with_order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="issued_gift_cards",
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} (${self.balance})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        if self.pk is None and not self.balance:
            self.balance = self.initial_balance
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_code():
        while True:
            code = "RR-" + get_random_string(
                12, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            )
            if not GiftCard.objects.filter(code=code).exists():
                return code

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def is_redeemable(self):
        return self.is_active and not self.is_expired and self.balance > ZERO

    def redeemable_amount(self, total):
        """How much of ``total`` this card can cover."""
        if not self.is_redeemable:
            return ZERO
        return min(self.balance, money(total))

    @transaction.atomic
    def redeem(self, amount, order=None):
        """Draw ``amount`` from the card, returning what was actually taken."""
        card = GiftCard.objects.select_for_update().get(pk=self.pk)
        taken = card.redeemable_amount(amount)
        if taken <= ZERO:
            return ZERO
        card.balance = money(card.balance - taken)
        card.save(update_fields=["balance"])
        GiftCardTransaction.objects.create(
            gift_card=card, amount=-taken, order=order
        )
        self.balance = card.balance
        return taken

    def refund(self, amount, order=None):
        self.balance = money(self.balance + money(amount))
        self.save(update_fields=["balance"])
        GiftCardTransaction.objects.create(
            gift_card=self, amount=money(amount), order=order, note="Refund"
        )


class GiftCardTransaction(models.Model):
    gift_card = models.ForeignKey(
        GiftCard, on_delete=models.CASCADE, related_name="transactions"
    )
    amount = models.DecimalField(**MONEY, help_text="Negative when spent.")
    order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="gift_card_transactions",
    )
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.gift_card.code}: {self.amount}"


class DiscountCode(models.Model):
    """A promo code: percentage or fixed amount off the merchandise subtotal."""

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        FIXED = "fixed", "Amount off"
        FREE_SHIPPING = "free_shipping", "Free shipping"

    code = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField(
        **MONEY, default=ZERO,
        validators=[MinValueValidator(ZERO)],
        help_text="Percent for percentage codes, dollars for fixed codes.",
    )
    description = models.CharField(max_length=200, blank=True)
    minimum_subtotal = models.DecimalField(**MONEY, default=ZERO)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total redemptions allowed. Blank for unlimited."
    )
    max_uses_per_customer = models.PositiveIntegerField(default=1)
    times_used = models.PositiveIntegerField(default=0)
    excludes_livestock = models.BooleanField(
        default=False, help_text="Apply only to dry goods lines."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def clean(self):
        if self.kind == self.Kind.PERCENT and self.value > 100:
            raise ValidationError({"value": "A percentage cannot exceed 100."})
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "The end must follow the start."})

    @property
    def is_live(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False
        return True

    def check_usable(self, subtotal, customer=None):
        """Return (ok, message)."""
        if not self.is_live:
            return False, "That code is no longer available."
        if subtotal < self.minimum_subtotal:
            return False, f"This code needs a subtotal of ${self.minimum_subtotal}."
        if customer is not None and self.max_uses_per_customer:
            used = DiscountRedemption.objects.filter(
                code=self, customer=customer
            ).count()
            if used >= self.max_uses_per_customer:
                return False, "You have already used that code."
        return True, ""

    def discount_for(self, subtotal, shipping=ZERO):
        """Dollar value of this code against a subtotal."""
        subtotal = money(subtotal)
        if self.kind == self.Kind.PERCENT:
            return money(subtotal * self.value / Decimal("100"))
        if self.kind == self.Kind.FIXED:
            return money(min(self.value, subtotal))
        if self.kind == self.Kind.FREE_SHIPPING:
            return money(shipping)
        return ZERO


class DiscountRedemption(models.Model):
    code = models.ForeignKey(
        DiscountCode, on_delete=models.CASCADE, related_name="redemptions"
    )
    customer = models.ForeignKey(
        "accounts.Customer", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="discount_redemptions",
    )
    order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="discount_redemptions",
    )
    email = models.EmailField(blank=True)
    amount = models.DecimalField(**MONEY, default=ZERO)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code.code} on {self.order or 'unknown order'}"
