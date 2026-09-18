"""Transactional email and abandoned cart recovery."""

from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.notifications.defaults import DEFAULT_TEMPLATES

TEMPLATE_CHOICES = [
    (key, spec["label"]) for key, spec in sorted(DEFAULT_TEMPLATES.items())
]


class EmailTemplate(models.Model):
    """Staff-editable copy for one transactional email.

    A missing row is not an error: the built-in default is used instead, so a
    fresh install sends proper email before anyone opens the admin.
    """

    key = models.CharField(max_length=40, choices=TEMPLATE_CHOICES, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField(
        help_text="Django template syntax. The available variables are listed "
        "under each template in the admin."
    )
    is_active = models.BooleanField(
        default=True, help_text="Turn off to stop sending this email entirely."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.get_key_display()

    @classmethod
    def resolve(cls, key):
        """(subject, body, enabled) for a key, falling back to the default."""
        row = cls.objects.filter(key=key).first()
        if row is not None:
            return row.subject, row.body, row.is_active
        default = DEFAULT_TEMPLATES.get(key)
        if default is None:
            return None, None, False
        return default["subject"], default["body"], True

    @classmethod
    def seed_defaults(cls):
        """Write every built-in template into the database for editing."""
        created = 0
        for key, spec in DEFAULT_TEMPLATES.items():
            _, was_created = cls.objects.get_or_create(
                key=key,
                defaults={"subject": spec["subject"], "body": spec["body"]},
            )
            created += int(was_created)
        return created

    def reset_to_default(self):
        default = DEFAULT_TEMPLATES.get(self.key)
        if not default:
            return False
        self.subject = default["subject"]
        self.body = default["body"]
        self.save(update_fields=["subject", "body", "updated_at"])
        return True


class EmailLog(models.Model):
    """Record of what was sent, and the guard against sending it twice."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped (duplicate)"

    key = models.CharField(max_length=40)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    dedupe_key = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Identifies this exact send, so a retry cannot email twice.",
    )
    order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="emails",
    )
    customer = models.ForeignKey(
        "accounts.Customer", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="emails",
    )
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["key", "recipient"])]

    def __str__(self):
        return f"{self.key} → {self.recipient}"


class AbandonedCartQuerySet(models.QuerySet):
    def open(self):
        return self.filter(recovered_at__isnull=True, placed_order__isnull=True)

    def due_for_reminder(self, *, after_hours, max_reminders, now=None):
        """Carts old enough for their next nudge."""
        now = now or timezone.now()
        cutoff = now - timezone.timedelta(hours=after_hours)
        return self.open().filter(
            updated_at__lte=cutoff,
            reminders_sent__lt=max_reminders,
        ).filter(
            models.Q(last_reminder_at__isnull=True)
            | models.Q(last_reminder_at__lte=cutoff)
        )


class AbandonedCart(models.Model):
    """A cart we know an email address for, held so it can be recovered.

    Only carts with a contactable owner are stored -- an anonymous visitor who
    never identified themselves leaves nothing behind.
    """

    email = models.EmailField()
    customer = models.ForeignKey(
        "accounts.Customer", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="abandoned_carts",
    )
    token = models.CharField(max_length=40, unique=True, blank=True)
    items = models.JSONField(
        default=list, help_text="Snapshot of the cart when it was last seen."
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    contains_wysiwyg = models.BooleanField(default=False)
    reminders_sent = models.PositiveIntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    recovered_at = models.DateTimeField(null=True, blank=True)
    placed_order = models.ForeignKey(
        "shop.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recovered_from_carts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AbandonedCartQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "abandoned cart"

    def __str__(self):
        return f"{self.email} (${self.subtotal})"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(40)
        super().save(*args, **kwargs)

    def get_recovery_url(self):
        return reverse("notifications:recover_cart", args=[self.token])

    @property
    def item_count(self):
        return sum(item.get("quantity", 0) for item in self.items)

    @property
    def is_recovered(self):
        return self.recovered_at is not None

    def mark_recovered(self, order=None):
        self.recovered_at = timezone.now()
        self.placed_order = order
        self.save(update_fields=["recovered_at", "placed_order", "updated_at"])

    def record_reminder(self):
        self.reminders_sent += 1
        self.last_reminder_at = timezone.now()
        # updated_at is deliberately excluded: bumping it would make the cart
        # look freshly active and push back the next reminder forever.
        AbandonedCart.objects.filter(pk=self.pk).update(
            reminders_sent=self.reminders_sent, last_reminder_at=self.last_reminder_at
        )
