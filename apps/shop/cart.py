"""Session-backed shopping cart.

The cart stores only product ids and quantities in the session; prices, stock
and availability are always re-read from the catalog so a cart that sat open
overnight cannot check out at yesterday's price or claim a coral that sold in
the meantime.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from apps.catalog.models import Product, ProductVariant
from apps.cms.models import SiteSettings
from apps.shop.models import ZERO, quote_shipping


@dataclass
class CartLine:
    product: Product
    quantity: int
    variant: ProductVariant = None

    @property
    def key(self):
        return cart_key(self.product, self.variant)

    @property
    def label(self):
        if self.variant:
            return f"{self.product.name} ({self.variant.name})"
        return self.product.name

    @property
    def unit_price(self):
        return self.variant.price if self.variant else self.product.price

    @property
    def line_total(self):
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    @property
    def over_stock(self):
        return not self.product.can_fulfill(self.quantity, variant=self.variant)

    @property
    def available_quantity(self):
        return self.variant.max_orderable if self.variant else self.product.max_orderable


def cart_key(product, variant=None):
    """Session key for a line. Variants of one product are separate lines."""
    return f"{product.pk}:{variant.pk}" if variant else str(product.pk)


def parse_cart_key(key):
    product_id, _, variant_id = key.partition(":")
    return product_id, (variant_id or None)


class Cart:
    def __init__(self, request):
        self.session = request.session
        self._items = self.session.setdefault(settings.CART_SESSION_KEY, {})
        self.customer = getattr(request, "_cart_customer", None)
        if self.customer is None and getattr(request, "user", None) is not None:
            if request.user.is_authenticated:
                from apps.accounts.models import Customer

                self.customer = Customer.objects.filter(user=request.user).first()
                request._cart_customer = self.customer

    @property
    def wholesale_discount(self):
        """Fraction off merchandise for an approved wholesale account."""
        if self.customer is None or not self.customer.is_wholesale:
            return Decimal("0")
        return SiteSettings.load().wholesale_discount_percent / Decimal("100")

    def price_for(self, line):
        """Unit price after any wholesale discount."""
        discount = self.wholesale_discount
        if not discount:
            return line.unit_price
        return (line.unit_price * (Decimal("1") - discount)).quantize(Decimal("0.01"))

    # --- mutation --------------------------------------------------------
    def add(self, product, quantity=1, *, variant=None, replace=False):
        """Add to the cart, clamped to what we can actually ship.

        Returns the quantity now in the cart for that product/variant.
        """
        if variant is None and product.has_variants:
            # A bare add on a variant product takes the default option.
            variant = product.default_variant
        key = cart_key(product, variant)
        current = 0 if replace else self._items.get(key, 0)
        desired = quantity if replace else current + quantity
        ceiling = variant.max_orderable if variant else product.max_orderable
        final = max(0, min(desired, ceiling))
        if final == 0:
            self._items.pop(key, None)
        else:
            self._items[key] = final
        self._save()
        return final

    def set_quantity(self, product, quantity, variant=None):
        return self.add(product, quantity, variant=variant, replace=True)

    def remove(self, product, variant=None):
        self._items.pop(cart_key(product, variant), None)
        self._save()

    def clear(self):
        self.session[settings.CART_SESSION_KEY] = {}
        self._items = self.session[settings.CART_SESSION_KEY]
        self._save()

    def _save(self):
        self.session[settings.CART_SESSION_KEY] = self._items
        self.session.modified = True

    # --- reading ---------------------------------------------------------
    @property
    def lines(self):
        if not self._items:
            return []
        parsed = {key: parse_cart_key(key) for key in self._items}
        product_ids = {pid for pid, _ in parsed.values()}
        variant_ids = {vid for _, vid in parsed.values() if vid}

        products = {
            str(p.pk): p
            for p in Product.objects.for_storefront()
            .prefetch_related("variants")
            .filter(pk__in=product_ids)
        }
        variants = {
            str(v.pk): v
            for v in ProductVariant.objects.filter(pk__in=variant_ids, is_active=True)
        }

        lines = []
        stale = []
        for key, quantity in self._items.items():
            product_id, variant_id = parsed[key]
            product = products.get(product_id)
            variant = variants.get(variant_id) if variant_id else None
            # Unpublished, deleted or deactivated since it was added.
            if product is None or (variant_id and variant is None):
                stale.append(key)
                continue
            lines.append(
                CartLine(product=product, quantity=quantity, variant=variant)
            )
        if stale:
            for key in stale:
                self._items.pop(key, None)
            self._save()
        return lines

    def __iter__(self):
        return iter(self.lines)

    def __len__(self):
        return sum(self._items.values())

    @property
    def is_empty(self):
        return not self._items

    @property
    def subtotal(self):
        discount = self.wholesale_discount
        if not discount:
            return sum((line.line_total for line in self.lines), start=ZERO)
        return sum(
            (
                (self.price_for(line) * line.quantity).quantize(Decimal("0.01"))
                for line in self.lines
            ),
            start=ZERO,
        )

    @property
    def retail_subtotal(self):
        return sum((line.line_total for line in self.lines), start=ZERO)

    @property
    def wholesale_savings(self):
        return self.retail_subtotal - self.subtotal

    @property
    def contains_livestock(self):
        return any(line.product.is_livestock for line in self.lines)

    @property
    def shipping_total(self):
        return quote_shipping(self.subtotal, self.contains_livestock)

    @property
    def tax_total(self):
        rate = SiteSettings.load().tax_rate_percent
        return (self.subtotal * rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def grand_total(self):
        return self.subtotal + self.shipping_total + self.tax_total

    @property
    def amount_to_free_shipping(self):
        threshold = SiteSettings.load().free_shipping_threshold
        if not threshold or self.subtotal >= threshold:
            return ZERO
        return threshold - self.subtotal

    def problems(self):
        """Lines that can no longer be fulfilled as requested."""
        return [line for line in self.lines if line.over_stock]

    def sync_to_stock(self):
        """Clamp every line to available stock; returns the adjusted lines."""
        adjusted = []
        for line in self.lines:
            ceiling = line.available_quantity
            if line.quantity > ceiling:
                self.set_quantity(line.product, ceiling, variant=line.variant)
                adjusted.append((line.product, ceiling))
        return adjusted
