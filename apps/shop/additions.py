"""Adding items to an order that has not shipped yet.

Top Shelf-style live sale flow: a customer picks a delivery date on their first
order, then keeps winning corals through the evening. Each later win joins the
existing box instead of generating a second overnight shipping charge.
"""

from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Product, ProductVariant
from apps.shop.models import ZERO, Order, OrderItem
from apps.shop.services import OutOfStock


class CannotAddToOrder(Exception):
    pass


@transaction.atomic
def add_to_order(order, cart):
    """Move every cart line into ``order``, re-quoting without new shipping.

    Shipping is deliberately left at what the customer already paid: the whole
    point of the workflow is that a second box is not being sent.
    """
    if not order.accepts_additions:
        raise CannotAddToOrder(
            "That order has already shipped, so it can't take more livestock."
        )
    lines = cart.lines
    if not lines:
        raise CannotAddToOrder("Your cart is empty.")

    original_shipping = order.shipping_total
    added = []

    for line in lines:
        product = Product.objects.select_for_update().get(pk=line.product.pk)
        variant = None
        if line.variant is not None:
            variant = ProductVariant.objects.select_for_update().get(pk=line.variant.pk)
            if not variant.is_active or not variant.can_fulfill(line.quantity):
                raise OutOfStock(product, variant.max_orderable, variant=variant)
            unit_price = variant.price
        else:
            if not product.can_fulfill(line.quantity):
                raise OutOfStock(product, product.max_orderable)
            unit_price = product.price

        item = OrderItem.objects.create(
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
        added.append(item)

    order.recalculate(save=False)
    # recalculate() re-quotes shipping from scratch; the customer already paid
    # for this box, so keep the original charge.
    order.shipping_total = original_shipping
    payable = (
        order.subtotal
        - order.discount_total
        + order.shipping_total
        + order.tax_total
        - order.points_value
        - order.gift_card_total
    )
    order.grand_total = max(payable, ZERO).quantize(Decimal("0.01"))
    order.save()

    cart.clear()
    return added


def open_orders_for(request, customer=None):
    """Unshipped orders this visitor is allowed to add to."""
    numbers = request.session.get("recent_orders", [])
    query = Order.objects.filter(
        status__in=[Order.Status.PENDING, Order.Status.PAID, Order.Status.PACKING]
    )
    if customer is not None:
        query = query.filter(models_q(customer, numbers))
    else:
        query = query.filter(number__in=numbers)
    return [order for order in query.distinct() if order.accepts_additions]


def models_q(customer, numbers):
    from django.db.models import Q

    return Q(customer=customer) | Q(number__in=numbers)
