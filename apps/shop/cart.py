"""Session-backed shopping cart.

The cart stores only product ids and quantities in the session; prices, stock
and availability are always re-read from the catalog so a cart that sat open
overnight cannot check out at yesterday's price or claim a coral that sold in
the meantime.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from apps.catalog.models import Product
from apps.cms.models import SiteSettings
from apps.shop.models import ZERO, quote_shipping


@dataclass
class CartLine:
    product: Product
    quantity: int

    @property
    def unit_price(self):
        return self.product.price

    @property
    def line_total(self):
        return (self.product.price * self.quantity).quantize(Decimal("0.01"))

    @property
    def over_stock(self):
        return not self.product.can_fulfill(self.quantity)

    @property
    def available_quantity(self):
        return self.product.max_orderable


class Cart:
    def __init__(self, request):
        self.session = request.session
        self._items = self.session.setdefault(settings.CART_SESSION_KEY, {})

    # --- mutation --------------------------------------------------------
    def add(self, product, quantity=1, *, replace=False):
        """Add to the cart, clamped to what we can actually ship.

        Returns the quantity now in the cart for that product.
        """
        key = str(product.pk)
        current = 0 if replace else self._items.get(key, 0)
        desired = current + quantity if not replace else quantity
        ceiling = product.max_orderable
        final = max(0, min(desired, ceiling))
        if final == 0:
            self._items.pop(key, None)
        else:
            self._items[key] = final
        self._save()
        return final

    def set_quantity(self, product, quantity):
        return self.add(product, quantity, replace=True)

    def remove(self, product):
        self._items.pop(str(product.pk), None)
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
        products = {
            str(p.pk): p
            for p in Product.objects.for_storefront().filter(pk__in=self._items.keys())
        }
        lines = []
        stale = []
        for key, quantity in self._items.items():
            product = products.get(key)
            if product is None:
                # Unpublished or deleted since it was added.
                stale.append(key)
                continue
            lines.append(CartLine(product=product, quantity=quantity))
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
        return sum((line.line_total for line in self.lines), start=ZERO)

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
            ceiling = line.product.max_orderable
            if line.quantity > ceiling:
                self.set_quantity(line.product, ceiling)
                adjusted.append((line.product, ceiling))
        return adjusted
