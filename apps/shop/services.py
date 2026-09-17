"""Checkout services: turning a cart into an order."""

from decimal import Decimal

from django.core.mail import send_mail
from django.db import models, transaction
from django.template.loader import render_to_string

from apps.catalog.models import Product, ProductVariant
from apps.cms.models import SiteSettings
from apps.rewards.models import (
    DiscountRedemption,
    RewardsSettings,
    award_points,
    redeem_points,
)
from apps.shop.models import Order, OrderItem, quote_shipping
from apps.shop.pricing import quote


class OutOfStock(Exception):
    """Raised when stock disappeared between the cart page and checkout."""

    def __init__(self, product, available, variant=None):
        self.product = product
        self.available = available
        self.variant = variant
        label = f"{product.name} ({variant.name})" if variant else product.name
        super().__init__(f"{label} only has {available} available.")


@transaction.atomic
def place_order(cart, details, customer=None, credits=None):
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
        # Lock the row so concurrent checkouts serialize on this product. For a
        # variant product the variant row is the contended one.
        product = Product.objects.select_for_update().get(pk=line.product.pk)
        variant = None
        if line.variant is not None:
            variant = ProductVariant.objects.select_for_update().get(
                pk=line.variant.pk
            )
            if not variant.is_active or not variant.can_fulfill(line.quantity):
                raise OutOfStock(product, variant.max_orderable, variant=variant)
            unit_price = variant.price
        else:
            if not product.can_fulfill(line.quantity):
                raise OutOfStock(product, product.max_orderable)
            unit_price = product.price

        # Approved wholesale accounts buy at trade pricing.
        if customer is not None and customer.is_wholesale:
            from apps.cms.models import SiteSettings as _Site

            rate = _Site.load().wholesale_discount_percent / Decimal("100")
            unit_price = (unit_price * (Decimal("1") - rate)).quantize(Decimal("0.01"))

        OrderItem.objects.create(
            order=order,
            product=product,
            variant=variant,
            name=product.name,
            variant_name=variant.name if variant else "",
            sku=variant.sku if variant else product.sku,
            unit_price=unit_price,
            quantity=line.quantity,
            is_livestock=product.is_livestock,
            is_wysiwyg=product.is_wysiwyg,
        )
        if variant is not None:
            if variant.track_inventory:
                variant.stock_quantity -= line.quantity
                variant.save(update_fields=["stock_quantity"])
        elif product.track_inventory:
            product.stock_quantity -= line.quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
        subtotal += unit_price * line.quantity
        contains_livestock = contains_livestock or product.is_livestock

    # Price the order through the single pricing function, then consume the
    # credits it actually used -- never more than that.
    discount_code = credits.discount_code if credits else None
    totals = quote(
        subtotal,
        contains_livestock=contains_livestock,
        discount_code=discount_code,
        points=credits.points if credits else 0,
        gift_cards=credits.gift_cards if credits else (),
        customer=customer,
        site=settings_obj,
    )

    order.subtotal = totals.subtotal
    order.contains_livestock = contains_livestock
    order.discount_total = totals.discount_total
    order.shipping_total = totals.shipping_total
    order.tax_total = totals.tax_total
    order.points_redeemed = totals.points_redeemed
    order.points_value = totals.points_value
    order.gift_card_total = totals.gift_card_total
    order.grand_total = totals.grand_total
    order.discount_code = discount_code if totals.discount_total or (
        discount_code and discount_code.kind == discount_code.Kind.FREE_SHIPPING
    ) else None
    order.save()

    if order.discount_code is not None:
        DiscountRedemption.objects.create(
            code=order.discount_code,
            customer=customer,
            order=order,
            email=order.email,
            amount=totals.discount_total,
        )
        type(order.discount_code).objects.filter(pk=order.discount_code.pk).update(
            times_used=models.F("times_used") + 1
        )

    if totals.points_redeemed:
        redeem_points(customer, totals.points_redeemed, order=order)

    for card, amount in totals.gift_card_allocations:
        card.redeem(amount, order=order)

    # Points are earned on what the customer actually spent on merchandise.
    award_points(customer, order, settings_obj=RewardsSettings.load())

    cart.clear()
    if credits is not None:
        credits.clear()
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
