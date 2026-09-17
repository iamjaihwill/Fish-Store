"""Catalog domain: what the store sells.

Livestock (corals, fish, inverts) and dry goods share a single ``Product``
model. Livestock-only fields live in the "reef care" block and are simply left
blank for dry goods -- the admin hides them for non-livestock categories and the
storefront only renders the ones that are filled in.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class ProductType(models.TextChoices):
    CORAL = "coral", "Coral"
    FISH = "fish", "Fish"
    INVERT = "invertebrate", "Invertebrate"
    DRY_GOODS = "dry_goods", "Dry goods"
    BUNDLE = "bundle", "Frag pack / bundle"


LIVESTOCK_TYPES = {ProductType.CORAL, ProductType.FISH, ProductType.INVERT}


class CareLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    EXPERT = "expert", "Expert"


class LightLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class FlowLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class Placement(models.TextChoices):
    BOTTOM = "bottom", "Bottom / sand bed"
    MIDDLE = "middle", "Mid rock"
    TOP = "top", "Upper rock"
    ANY = "any", "Anywhere"


class Temperament(models.TextChoices):
    PEACEFUL = "peaceful", "Peaceful"
    SEMI_AGGRESSIVE = "semi", "Semi-aggressive"
    AGGRESSIVE = "aggressive", "Aggressive"


class ReefSafe(models.TextChoices):
    YES = "yes", "Reef safe"
    CAUTION = "caution", "Reef safe with caution"
    NO = "no", "Not reef safe"


class CategoryQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def top_level(self):
        return self.filter(parent__isnull=True)


class Category(models.Model):
    """A browsable department, optionally nested one level deep."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Leave empty for a top-level department.",
    )
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.CORAL,
        help_text="Drives which care fields show on products in this category.",
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="categories/", blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    show_in_nav = models.BooleanField(
        default=True, help_text="Show this category in the main storefront menu."
    )
    is_active = models.BooleanField(default=True)

    objects = CategoryQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.name} / {self.name}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Category, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])

    @property
    def is_livestock(self):
        return self.product_type in LIVESTOCK_TYPES

    def descendant_ids(self):
        return [self.pk, *self.children.values_list("pk", flat=True)]


class Tag(models.Model):
    """Free-form merchandising label, e.g. "Torch", "Aquacultured", "Live Sale"."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Tag, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"{reverse('catalog:shop')}?tag={self.slug}"


class ProductQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Product.Status.ACTIVE, published_at__lte=timezone.now())

    def in_stock(self):
        return self.filter(Q(track_inventory=False) | Q(stock_quantity__gt=0))

    def sold_out(self):
        return self.filter(track_inventory=True, stock_quantity__lte=0)

    def featured(self):
        return self.published().filter(is_featured=True)

    def livestock(self):
        return self.filter(product_type__in=list(LIVESTOCK_TYPES))

    def on_sale(self):
        return self.filter(compare_at_price__gt=F("price"))

    def for_storefront(self):
        return self.published().select_related("category").prefetch_related("images")


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    # --- identity -------------------------------------------------------
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    sku = models.CharField(max_length=40, unique=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    product_type = models.CharField(
        max_length=20, choices=ProductType.choices, default=ProductType.CORAL
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")

    # --- copy -----------------------------------------------------------
    tagline = models.CharField(
        max_length=200, blank=True, help_text="One line shown under the title."
    )
    description = models.TextField(blank=True)
    scientific_name = models.CharField(max_length=160, blank=True)

    # --- money ----------------------------------------------------------
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    compare_at_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Original price. Set above the price to show a sale badge.",
    )

    # --- inventory ------------------------------------------------------
    is_wysiwyg = models.BooleanField(
        "WYSIWYG",
        default=False,
        help_text="What-you-see-is-what-you-get: this exact colony, quantity of one.",
    )
    track_inventory = models.BooleanField(default=True)
    stock_quantity = models.IntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=2)

    # --- reef care (livestock only) --------------------------------------
    care_level = models.CharField(
        max_length=20, choices=CareLevel.choices, blank=True
    )
    lighting = models.CharField(max_length=10, choices=LightLevel.choices, blank=True)
    flow = models.CharField(max_length=10, choices=FlowLevel.choices, blank=True)
    placement = models.CharField(max_length=10, choices=Placement.choices, blank=True)
    temperament = models.CharField(
        max_length=12, choices=Temperament.choices, blank=True
    )
    reef_safe = models.CharField(max_length=10, choices=ReefSafe.choices, blank=True)
    diet = models.CharField(max_length=160, blank=True)
    max_size = models.CharField(
        max_length=60, blank=True, help_text='e.g. "4 inches" or "Colony to 12in"'
    )
    min_tank_size_gallons = models.PositiveIntegerField(null=True, blank=True)
    is_aquacultured = models.BooleanField(
        default=False, help_text="Grown in-house or by a partner farm rather than wild."
    )
    is_captive_bred = models.BooleanField(default=False)
    requires_overnight_shipping = models.BooleanField(
        default=False,
        help_text="Livestock: forces overnight shipping and the live arrival guarantee.",
    )
    acclimation_notes = models.TextField(blank=True)

    # --- merchandising ---------------------------------------------------
    # --- bundles (frag packs, mystery boxes) -----------------------------
    is_mystery = models.BooleanField(
        default=False,
        help_text="Bundle whose exact contents are a surprise (mystery box).",
    )
    bundle_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="How many pieces a frag pack contains, when it is a bundle.",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    is_featured = models.BooleanField(default=False)
    badge = models.CharField(
        max_length=30, blank=True, help_text='Optional ribbon, e.g. "Limited" or "New"'
    )
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "name"]
        indexes = [
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["product_type"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Product, self.name)
        if not self.sku:
            self.sku = _generate_sku(self)
        if self.is_wysiwyg:
            # A WYSIWYG listing is one physical animal; it can never be a
            # multi-quantity line, but it may already be sold (quantity 0).
            self.track_inventory = True
            self.stock_quantity = min(self.stock_quantity, 1)
        if self.is_livestock:
            self.requires_overnight_shipping = True
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product", args=[self.slug])

    # --- derived state ---------------------------------------------------
    @property
    def is_livestock(self):
        return self.product_type in LIVESTOCK_TYPES

    @property
    def is_published(self):
        return self.status == self.Status.ACTIVE and self.published_at <= timezone.now()

    @property
    def is_bundle(self):
        return self.product_type == ProductType.BUNDLE

    @property
    def has_variants(self):
        return self.variants.exists()

    @property
    def sellable_variants(self):
        return [v for v in self.variants.all() if v.is_active]

    @property
    def default_variant(self):
        """The variant a bare "add to cart" should use, if any."""
        variants = self.sellable_variants
        if not variants:
            return None
        return next(
            (v for v in variants if v.is_default and v.in_stock),
            next((v for v in variants if v.in_stock), variants[0]),
        )

    @property
    def price_from(self):
        """Lowest sellable price, for "from $X" display on variant products."""
        variants = self.sellable_variants
        if not variants:
            return self.price
        return min(v.price for v in variants)

    @property
    def available_quantity(self):
        if self.has_variants:
            return sum(v.available_quantity for v in self.sellable_variants)
        if not self.track_inventory:
            return None  # unlimited
        return max(self.stock_quantity, 0)

    @property
    def is_sold_out(self):
        if self.has_variants:
            return not any(v.in_stock for v in self.sellable_variants)
        return self.track_inventory and self.stock_quantity <= 0

    @property
    def is_low_stock(self):
        return (
            self.track_inventory
            and 0 < self.stock_quantity <= self.low_stock_threshold
        )

    @property
    def is_on_sale(self):
        return bool(self.compare_at_price and self.compare_at_price > self.price)

    @property
    def savings(self):
        if not self.is_on_sale:
            return Decimal("0.00")
        return self.compare_at_price - self.price

    @property
    def discount_percent(self):
        if not self.is_on_sale or not self.compare_at_price:
            return 0
        return int(round((self.savings / self.compare_at_price) * 100))

    @property
    def primary_image(self):
        images = list(self.images.all())
        if not images:
            return None
        return next((img for img in images if img.is_primary), images[0])

    @property
    def care_facts(self):
        """(label, value) pairs for the care table, skipping blanks."""
        facts = [
            ("Care level", self.get_care_level_display() if self.care_level else ""),
            ("Lighting", self.get_lighting_display() if self.lighting else ""),
            ("Flow", self.get_flow_display() if self.flow else ""),
            ("Placement", self.get_placement_display() if self.placement else ""),
            ("Temperament", self.get_temperament_display() if self.temperament else ""),
            ("Reef safe", self.get_reef_safe_display() if self.reef_safe else ""),
            ("Diet", self.diet),
            ("Max size", self.max_size),
            (
                "Min tank size",
                f"{self.min_tank_size_gallons} gallons"
                if self.min_tank_size_gallons
                else "",
            ),
        ]
        return [(label, value) for label, value in facts if value]

    def can_fulfill(self, quantity, variant=None):
        """Can this product ship ``quantity`` units right now?"""
        if not self.is_published:
            return False
        if variant is not None:
            return variant.is_active and variant.can_fulfill(quantity)
        if self.has_variants:
            return any(v.can_fulfill(quantity) for v in self.sellable_variants)
        if not self.track_inventory:
            return True
        return self.stock_quantity >= quantity

    @property
    def max_orderable(self):
        if self.is_wysiwyg:
            return min(1, self.stock_quantity)
        if self.has_variants:
            variants = self.sellable_variants
            return max((v.max_orderable for v in variants), default=0)
        if not self.track_inventory:
            return 99
        return max(self.stock_quantity, 0)


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="products/")
    alt_text = models.CharField(max_length=160, blank=True)
    caption = models.CharField(
        max_length=160, blank=True, help_text='e.g. "Photographed under 20k Radion"'
    )
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-is_primary", "sort_order", "pk"]

    def __str__(self):
        return self.alt_text or f"Image for {self.product.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            # Only one primary image per product.
            ProductImage.objects.filter(product=self.product).exclude(
                pk=self.pk
            ).update(is_primary=False)


class Collection(models.Model):
    """A curated, CMS-managed grouping that cuts across categories."""

    title = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    subtitle = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="collections/", blank=True)
    products = models.ManyToManyField(
        Product, blank=True, related_name="collections", through="CollectionItem"
    )
    show_on_homepage = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Collection, self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:collection", args=[self.slug])

    def visible_products(self):
        return (
            self.products.for_storefront()
            .order_by("collectionitem__sort_order", "-published_at")
        )


class CollectionItem(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]
        unique_together = [("collection", "product")]

    def __str__(self):
        return f"{self.collection.title}: {self.product.name}"


def _unique_slug(model, value):
    base = slugify(value)[:180] or "item"
    slug = base
    counter = 2
    while model.objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _generate_sku(product):
    prefix = {
        ProductType.CORAL: "COR",
        ProductType.FISH: "FSH",
        ProductType.INVERT: "INV",
        ProductType.DRY_GOODS: "DRY",
    }.get(product.product_type, "GEN")
    stem = slugify(product.name).upper().replace("-", "")[:8] or "ITEM"
    candidate = f"{prefix}-{stem}"
    counter = 2
    while Product.objects.filter(sku=candidate).exclude(pk=product.pk).exists():
        candidate = f"{prefix}-{stem}-{counter}"
        counter += 1
    return candidate


class ProductVariant(models.Model):
    """A sellable option of a product: frag vs. colony, or a pack size.

    Products without variants sell directly and keep their own price and stock.
    Once a product has variants, the variant owns price and inventory and the
    product's own price becomes the "from" price shown on listings.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    name = models.CharField(
        max_length=80, help_text='e.g. "Single frag", "Mini colony", "10 pack"'
    )
    sku = models.CharField(max_length=48, unique=True, blank=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    compare_at_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    stock_quantity = models.IntegerField(default=0)
    track_inventory = models.BooleanField(default=True)
    pack_quantity = models.PositiveIntegerField(
        default=1, help_text="How many animals or items this option contains."
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]
        unique_together = [("product", "name")]

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.sku:
            base = f"{self.product.sku or slugify(self.product.name).upper()[:8]}"
            suffix = slugify(self.name).upper().replace("-", "")[:6] or "OPT"
            candidate = f"{base}-{suffix}"
            counter = 2
            while (
                ProductVariant.objects.filter(sku=candidate)
                .exclude(pk=self.pk)
                .exists()
            ):
                candidate = f"{base}-{suffix}-{counter}"
                counter += 1
            self.sku = candidate
        super().save(*args, **kwargs)
        if self.is_default:
            ProductVariant.objects.filter(product=self.product).exclude(
                pk=self.pk
            ).update(is_default=False)

    @property
    def in_stock(self):
        return not self.track_inventory or self.stock_quantity > 0

    @property
    def available_quantity(self):
        if not self.track_inventory:
            return 99
        return max(self.stock_quantity, 0)

    @property
    def max_orderable(self):
        if self.product.is_wysiwyg:
            return min(1, self.available_quantity)
        return self.available_quantity

    @property
    def is_on_sale(self):
        return bool(self.compare_at_price and self.compare_at_price > self.price)

    def can_fulfill(self, quantity):
        if not self.track_inventory:
            return True
        return self.stock_quantity >= quantity

    @property
    def label_with_price(self):
        return f"{self.name} — ${self.price}"


class ProductVideo(models.Model):
    """Video for a listing. Coral buyers judge movement, not just stills."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="videos"
    )
    title = models.CharField(max_length=140, blank=True)
    url = models.URLField(
        help_text="YouTube, Vimeo or a direct MP4 link.",
    )
    thumbnail = models.ImageField(upload_to="videos/", blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return self.title or f"Video for {self.product.name}"

    @property
    def embed_url(self):
        """Normalise common share links into embeddable ones."""
        url = self.url
        if "youtube.com/watch?v=" in url:
            return url.replace("watch?v=", "embed/").split("&")[0]
        if "youtu.be/" in url:
            return url.replace("youtu.be/", "www.youtube.com/embed/").split("?")[0]
        if "vimeo.com/" in url and "player.vimeo.com" not in url:
            video_id = url.rstrip("/").split("/")[-1].split("?")[0]
            return f"https://player.vimeo.com/video/{video_id}"
        return url

    @property
    def is_embed(self):
        return "youtube" in self.url or "youtu.be" in self.url or "vimeo" in self.url


class BundleItem(models.Model):
    """A component of a frag pack.

    Mystery boxes leave this empty -- the point is that the buyer does not know.
    """

    bundle = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="bundle_items",
        limit_choices_to={"product_type": ProductType.BUNDLE},
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="in_bundles"
    )
    quantity = models.PositiveIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "pk"]
        unique_together = [("bundle", "product")]

    def __str__(self):
        return f"{self.bundle.name}: {self.quantity} × {self.product.name}"
