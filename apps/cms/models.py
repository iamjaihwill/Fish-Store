"""Content models.

Everything a shop owner would otherwise need a developer for lives here: the
announcement bar, homepage composition, navigation, policy pages, FAQ and the
live sale calendar. The Django admin is the CMS UI for these models.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, mark_safe
from django.utils.text import slugify


class SingletonModel(models.Model):
    """A model with exactly one row, which staff edit rather than create."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - guard rail
        raise ValidationError("The site settings record cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SiteSettings(SingletonModel):
    """Global storefront configuration, editable without a deploy."""

    store_name = models.CharField(max_length=80, default="Reef & Rift")
    tagline = models.CharField(
        max_length=160, default="Aquacultured corals, shipped overnight."
    )
    logo = models.ImageField(upload_to="branding/", blank=True)

    # Contact
    contact_email = models.EmailField(default="hello@reefandrift.example")
    contact_phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    hours = models.CharField(
        max_length=160, blank=True, help_text='e.g. "Tue-Sat 11am-6pm"'
    )

    # Announcement bar
    announcement_enabled = models.BooleanField(default=True)
    announcement_text = models.CharField(
        max_length=200, blank=True, default="Free overnight shipping on orders $299+"
    )
    announcement_url = models.CharField(max_length=300, blank=True)

    # Commerce policy
    free_shipping_threshold = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=299,
        help_text="Order subtotal at which livestock shipping becomes free. 0 disables.",
    )
    livestock_shipping_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=59
    )
    drygoods_shipping_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=12
    )
    tax_rate_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text="Applied to the subtotal."
    )
    shipping_days = models.CharField(
        max_length=120,
        default="Monday, Tuesday and Wednesday",
        help_text="Days livestock leaves the facility.",
    )
    shipping_cutoff_time = models.TimeField(
        default="14:00",
        help_text="Orders placed before this local time ship the same business day.",
    )
    shipping_weekdays = models.CharField(
        max_length=20,
        default="0,1,2",
        help_text="Weekday numbers livestock ships on (Monday=0). e.g. 0,1,2",
    )
    wholesale_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=30,
        help_text="Percentage off merchandise for approved wholesale accounts.",
    )
    allow_order_additions = models.BooleanField(
        default=True,
        help_text="Let customers add live sale wins to an unshipped order without paying shipping twice.",
    )
    guarantee_headline = models.CharField(
        max_length=120, default="Live Arrival Guarantee"
    )
    guarantee_blurb = models.CharField(
        max_length=240,
        default="Every animal ships overnight in an insulated box and is covered for 8 hours after delivery.",
    )

    # Social
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)

    footer_note = models.CharField(
        max_length=240, blank=True, default="Reef responsibly. Buy aquacultured."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"

    def __str__(self):
        return self.store_name

    @property
    def shipping_weekday_numbers(self):
        numbers = []
        for piece in self.shipping_weekdays.split(","):
            piece = piece.strip()
            if piece.isdigit() and 0 <= int(piece) <= 6:
                numbers.append(int(piece))
        return sorted(set(numbers)) or [0, 1, 2]

    def next_ship_date(self, now=None):
        """The next day livestock can leave, honouring the same-day cutoff."""
        from django.utils import timezone as tz

        now = now or tz.localtime()
        ship_days = self.shipping_weekday_numbers
        candidate = now.date()
        # Past the cutoff, today is no longer on the table.
        if now.time() >= self.shipping_cutoff_time:
            candidate += tz.timedelta(days=1)
        for _ in range(14):
            if candidate.weekday() in ship_days:
                return candidate
            candidate += tz.timedelta(days=1)
        return candidate

    @property
    def social_links(self):
        return [
            (label, url)
            for label, url in (
                ("Instagram", self.instagram_url),
                ("YouTube", self.youtube_url),
                ("Facebook", self.facebook_url),
                ("TikTok", self.tiktok_url),
            )
            if url
        ]


class HeroSlide(models.Model):
    """Full-bleed homepage hero panel."""

    eyebrow = models.CharField(max_length=60, blank=True)
    headline = models.CharField(max_length=120)
    subhead = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="hero/", blank=True)
    cta_label = models.CharField(max_length=40, blank=True, default="Shop corals")
    cta_url = models.CharField(max_length=300, blank=True, default="/shop/")
    secondary_cta_label = models.CharField(max_length=40, blank=True)
    secondary_cta_url = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return self.headline

    @property
    def is_live(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True


class HomepageSection(models.Model):
    """An ordered band on the homepage, composed in the admin."""

    class Kind(models.TextChoices):
        FEATURED = "featured", "Featured products"
        NEW_ARRIVALS = "new_arrivals", "Newest arrivals"
        WYSIWYG = "wysiwyg", "WYSIWYG picks"
        ON_SALE = "on_sale", "On sale"
        COLLECTION = "collection", "Specific collection"
        CATEGORY_GRID = "category_grid", "Category grid"
        RICH_TEXT = "rich_text", "Rich text band"
        GUARANTEE = "guarantee", "Guarantee / trust bar"
        TESTIMONIALS = "testimonials", "Testimonials"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    heading = models.CharField(max_length=120, blank=True)
    subheading = models.CharField(max_length=240, blank=True)
    body = models.TextField(blank=True, help_text="Used by the rich text band.")
    collection = models.ForeignKey(
        "catalog.Collection",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="homepage_sections",
        help_text="Required when the kind is 'Specific collection'.",
    )
    cta_label = models.CharField(max_length=40, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    max_items = models.PositiveIntegerField(default=8)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "pk"]
        verbose_name = "homepage section"

    def __str__(self):
        return self.heading or self.get_kind_display()

    def clean(self):
        if self.kind == self.Kind.COLLECTION and not self.collection:
            raise ValidationError(
                {"collection": "Pick a collection for this section kind."}
            )

    @property
    def body_html(self):
        return render_rich_text(self.body)


class Page(models.Model):
    """A standalone content page: policies, about, acclimation guides."""

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    body = models.TextField(
        blank=True,
        help_text="Blank lines start a new paragraph. Basic HTML is allowed.",
    )
    hero_image = models.ImageField(upload_to="pages/", blank=True)
    show_in_header = models.BooleanField(default=False)
    show_in_footer = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    seo_title = models.CharField(max_length=160, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:180]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("cms:page", args=[self.slug])

    @property
    def body_html(self):
        return render_rich_text(self.body)


class FaqItem(models.Model):
    class Topic(models.TextChoices):
        SHIPPING = "shipping", "Shipping & arrival"
        LIVESTOCK = "livestock", "Livestock care"
        ORDERS = "orders", "Orders & returns"
        GENERAL = "general", "General"

    topic = models.CharField(
        max_length=20, choices=Topic.choices, default=Topic.GENERAL
    )
    question = models.CharField(max_length=240)
    answer = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["topic", "sort_order", "pk"]
        verbose_name = "FAQ item"

    def __str__(self):
        return self.question

    @property
    def answer_html(self):
        return render_rich_text(self.answer)


class NavigationLink(models.Model):
    """Extra header/footer links beyond the auto-generated category menu."""

    class Placement(models.TextChoices):
        HEADER = "header", "Header"
        FOOTER_SHOP = "footer_shop", "Footer - Shop"
        FOOTER_SUPPORT = "footer_support", "Footer - Support"

    label = models.CharField(max_length=60)
    url = models.CharField(max_length=300, blank=True)
    page = models.ForeignKey(
        Page,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="nav_links",
        help_text="Link to a CMS page instead of typing a URL.",
    )
    placement = models.CharField(
        max_length=20, choices=Placement.choices, default=Placement.HEADER
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["placement", "sort_order", "pk"]

    def __str__(self):
        return f"{self.label} ({self.get_placement_display()})"

    def clean(self):
        if not self.url and not self.page:
            raise ValidationError("Set a URL or pick a page.")

    @property
    def href(self):
        if self.page_id:
            return self.page.get_absolute_url()
        return self.url


class LiveSaleEvent(models.Model):
    """A scheduled live sale / drop, surfaced as a homepage countdown."""

    title = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="events/", blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    stream_url = models.URLField(blank=True, help_text="YouTube / Instagram live link.")
    collection = models.ForeignKey(
        "catalog.Collection",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_sales",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:160]
        super().save(*args, **kwargs)

    def clean(self):
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "The end time must follow the start."})

    @property
    def is_upcoming(self):
        return self.is_active and self.starts_at > timezone.now()

    @property
    def is_running(self):
        now = timezone.now()
        if not self.is_active or self.starts_at > now:
            return False
        return self.ends_at is None or self.ends_at > now


class Testimonial(models.Model):
    quote = models.TextField()
    author = models.CharField(max_length=80)
    location = models.CharField(max_length=80, blank=True)
    rating = models.PositiveSmallIntegerField(default=5)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return f"{self.author}: {self.quote[:40]}"

    @property
    def stars(self):
        return range(min(self.rating, 5))


class ContactMessage(models.Model):
    """Inbox for storefront contact form submissions."""

    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=160, blank=True)
    message = models.TextField()
    order_reference = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email


#: Copy that opens with a block-level tag is treated as authored HTML. Anything
#: else is plain text, even if it contains stray angle brackets mid-sentence --
#: checking only the opening token keeps "5 < 10" from being rendered as markup.
_HTML_DOCUMENT = re.compile(
    r"^<(p|div|section|article|h[1-6]|ul|ol|table|blockquote|figure|img|hr)\b",
    re.IGNORECASE,
)


def render_rich_text(value):
    """Render staff-authored copy.

    Copy that begins with a block-level HTML tag is passed through as markup
    (only staff can edit these fields). Everything else is escaped and split
    into paragraphs, so authors are never required to write HTML.
    """
    if not value:
        return ""
    stripped = value.strip()
    if _HTML_DOCUMENT.match(stripped):
        return mark_safe(stripped)
    paragraphs = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    html = "".join(
        "<p>{}</p>".format(escape(p).replace("\n", "<br>")) for p in paragraphs
    )
    return mark_safe(html)


class Article(models.Model):
    """Care guides and shop news — the content that earns search traffic."""

    class Category(models.TextChoices):
        CARE = "care", "Care guide"
        NEWS = "news", "Shop news"
        SPECIES = "species", "Species spotlight"
        HOWTO = "howto", "How-to"

    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    category = models.CharField(
        max_length=12, choices=Category.choices, default=Category.CARE
    )
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField(
        help_text="Blank lines start a new paragraph. Basic HTML is allowed."
    )
    hero_image = models.ImageField(upload_to="articles/", blank=True)
    author = models.CharField(max_length=120, blank=True)
    related_products = models.ManyToManyField(
        "catalog.Product", blank=True, related_name="articles"
    )
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    seo_title = models.CharField(max_length=180, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:200]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("cms:article", args=[self.slug])

    @property
    def is_live(self):
        return self.is_published and self.published_at <= timezone.now()

    @property
    def body_html(self):
        return render_rich_text(self.body)

    @property
    def reading_minutes(self):
        words = len(self.body.split())
        return max(1, round(words / 200))
