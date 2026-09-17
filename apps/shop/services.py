"""Checkout services: turning a cart into an order."""

from decimal import Decimal

from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

from apps.catalog.models import Product
from apps.cms.models import SiteSettings
from apps.shop.models import Order, OrderItem, quote_shipping


class OutOfStock(Exception):
    """Raised when stock disappeared between the cart page and checkout."""

    def __init__(self, product, available):
        self.product = product
        self.available = available
        super().__init__(f"{product.name} only has {available} available.")


@transaction.atomic
def place_order(cart, details, customer=None):
    """Create an order from ``cart``.

    Inventory is locked and decremented inside the transaction, so two people
    racing for the last WYSIWYG colony cannot both win it. ``details`` is the
    cleaned data of the checkout form.
    """
    lines = cart.lines
    if not lines:
        raise ValueError("Cannot place an order with an empty cart.")

    settings_obj = SiteSettings.load()
    order = Order(
        customer=customer,
        email=details["email"],
        first_name=details["first_name"],
        last_name=details["last_name"],
        phone=details["phone"],
        address_line1=details["address_line1"],
        address_line2=details.get("address_line2", ""),
        city=details["city"],
        state=details["state"],
        postal_code=details["postal_code"],
        country=details.get("country") or "United States",
        requested_ship_date=details.get("requested_ship_date"),
        hold_for_weather=details.get("hold_for_weather", False),
        customer_notes=details.get("customer_notes", ""),
    )
    order.save()

    subtotal = Decimal("0.00")
    contains_livestock = False

    for line in lines:
        # Lock the row so concurrent checkouts serialize on this product.
        product = Product.objects.select_for_update().get(pk=line.product.pk)
        if not product.can_fulfill(line.quantity):
            raise OutOfStock(product, product.max_orderable)

        OrderItem.objects.create(
            order=order,
            product=product,
            name=product.name,
            sku=product.sku,
            unit_price=product.price,
            quantity=line.quantity,
            is_livestock=product.is_livestock,
            is_wysiwyg=product.is_wysiwyg,
        )
        if product.track_inventory:
            product.stock_quantity -= line.quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
        subtotal += product.price * line.quantity
        contains_livestock = contains_livestock or product.is_livestock

    order.subtotal = subtotal.quantize(Decimal("0.01"))
    order.contains_livestock = contains_livestock
    order.shipping_total = quote_shipping(order.subtotal, contains_livestock, settings_obj)
    order.tax_total = (
        order.subtotal * settings_obj.tax_rate_percent / Decimal("100")
    ).quantize(Decimal("0.01"))
    order.grand_total = order.subtotal + order.shipping_total + order.tax_total
    order.save()

    cart.clear()
    return order


def send_order_confirmation(order):
    """Email the customer their receipt. Console backend in development."""
    settings_obj = SiteSettings.load()
    context = {"order": order, "site": settings_obj}
    body = render_to_string("shop/email/order_confirmation.txt", context)
    send_mail(
        subject=f"{settings_obj.store_name} order {order.number}",
        message=body,
        from_email=None,
        recipient_list=[order.email],
        fail_silently=True,
    )
