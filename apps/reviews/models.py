"""Product reviews.

Reviews are moderated before they appear: a coral store's review section is a
target for competitors and for people venting about a tank crash that was not
the shop's fault. Reviews from someone who actually bought the item are marked
as verified, which is the signal buyers care about.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.utils import timezone


class ReviewQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status=Review.Status.APPROVED)

    def for_product(self, product):
        return self.approved().filter(product=product)


class Review(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Published"
        REJECTED = "rejected", "Rejected"

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="reviews"
    )
    customer = models.ForeignKey(
        "accounts.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviews",
    )
    author_name = models.CharField(max_length=80)
    author_email = models.EmailField(blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=140, blank=True)
    body = models.TextField()
    photo = models.ImageField(
        upload_to="reviews/",
        blank=True,
        help_text="Optional grow-out shot from the customer's tank.",
    )
    is_verified_purchase = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    staff_reply = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["product", "status"])]

    def __str__(self):
        return f"{self.rating}★ {self.product} by {self.author_name}"

    def save(self, *args, **kwargs):
        if self.status == self.Status.APPROVED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def stars(self):
        return range(self.rating)

    @property
    def empty_stars(self):
        return range(5 - self.rating)

    def approve(self):
        self.status = self.Status.APPROVED
        self.published_at = self.published_at or timezone.now()
        self.save(update_fields=["status", "published_at"])


def rating_summary(product):
    """Average rating and count for a product, over approved reviews only."""
    stats = Review.objects.for_product(product).aggregate(
        average=Avg("rating"), total=Count("pk")
    )
    average = stats["average"]
    return {
        "average": round(average, 1) if average else None,
        "total": stats["total"],
        "rounded": int(round(average)) if average else 0,
    }


def has_purchased(product, *, customer=None, email=""):
    """Did this person actually buy the product? Drives the verified badge."""
    from apps.shop.models import Order, OrderItem

    items = OrderItem.objects.filter(product=product).exclude(
        order__status__in=[Order.Status.CANCELLED, Order.Status.REFUNDED]
    )
    if customer is not None:
        if items.filter(order__customer=customer).exists():
            return True
        email = email or customer.email
    if email:
        return items.filter(order__email__iexact=email).exists()
    return False
