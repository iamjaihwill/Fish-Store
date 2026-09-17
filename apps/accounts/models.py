"""Customer accounts.

Guest checkout stays the default -- reef buyers often arrive from a live sale
link and will not make an account first. An account adds order history, saved
addresses, a wishlist, rewards and reviews on top of that, and claims any past
guest orders placed with the same email address.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    """Storefront profile attached to a Django user."""

    class Tier(models.TextChoices):
        RETAIL = "retail", "Retail"
        WHOLESALE = "wholesale", "Wholesale"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer"
    )
    phone = models.CharField(max_length=40, blank=True)
    tier = models.CharField(max_length=12, choices=Tier.choices, default=Tier.RETAIL)
    wholesale_approved_at = models.DateTimeField(null=True, blank=True)
    wholesale_company = models.CharField(max_length=160, blank=True)
    wholesale_tax_id = models.CharField(max_length=60, blank=True)
    accepts_marketing = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def email(self):
        return self.user.email

    @property
    def is_wholesale(self):
        return self.tier == self.Tier.WHOLESALE and self.wholesale_approved_at is not None

    def orders(self):
        from apps.shop.models import Order

        return Order.objects.filter(
            models.Q(customer=self) | models.Q(email__iexact=self.user.email)
        ).distinct()

    def claim_guest_orders(self):
        """Attach past guest orders placed with this email to the account."""
        from apps.shop.models import Order

        return Order.objects.filter(
            customer__isnull=True, email__iexact=self.user.email
        ).update(customer=self)

    def default_address(self):
        return self.addresses.filter(is_default=True).first() or self.addresses.first()


class Address(models.Model):
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="addresses"
    )
    label = models.CharField(
        max_length=60, blank=True, help_text='e.g. "Home" or "Shop"'
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=40)
    address_line1 = models.CharField(max_length=160)
    address_line2 = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=40)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=60, default="United States")
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "pk"]
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.label or self.city}: {self.address_line1}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(customer=self.customer).exclude(pk=self.pk).update(
                is_default=False
            )

    def as_checkout_initial(self):
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone": self.phone,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
        }


class WishlistItem(models.Model):
    """A saved product. Doubles as the back-in-stock notification list."""

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="wishlisted_by"
    )
    notify_when_available = models.BooleanField(
        default=True,
        help_text="Email this customer when the product comes back into stock.",
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("customer", "product")]

    def __str__(self):
        return f"{self.customer} ♥ {self.product}"

    def mark_notified(self):
        self.notified_at = timezone.now()
        self.save(update_fields=["notified_at"])
