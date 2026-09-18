"""One function per lifecycle event, so callers never build context by hand."""

from apps.notifications.services import absolute_url, send_transactional


def send_welcome(customer, claimed=0):
    return send_transactional(
        "welcome",
        customer.email,
        {"first_name": customer.user.first_name, "claimed": claimed},
        dedupe_key=f"welcome:{customer.pk}",
        customer=customer,
    )


def send_order_confirmation(order):
    return send_transactional(
        "order_confirmation",
        order.email,
        {"order": order, "order_url": absolute_url(order.get_absolute_url())},
        dedupe_key=f"order_confirmation:{order.pk}",
        order=order,
        customer=order.customer,
    )


def send_payment_received(payment):
    order = payment.order
    return send_transactional(
        "payment_received",
        order.email,
        {
            "order": order,
            "payment": payment,
            "order_url": absolute_url(order.get_absolute_url()),
        },
        dedupe_key=f"payment_received:{payment.pk}",
        order=order,
        customer=order.customer,
    )


def send_order_shipped(order):
    return send_transactional(
        "order_shipped",
        order.email,
        {"order": order, "order_url": absolute_url(order.get_absolute_url())},
        # Keyed on the tracking number, so a corrected tracking number sends a
        # fresh notice but re-saving the same one does not.
        dedupe_key=f"order_shipped:{order.pk}:{order.tracking_number}",
        order=order,
        customer=order.customer,
    )


def send_order_delivered(order):
    from django.urls import reverse

    return send_transactional(
        "order_delivered",
        order.email,
        {
            "order": order,
            "claim_url": absolute_url(
                reverse("shop:doa_claim", args=[order.number])
            ),
        },
        dedupe_key=f"order_delivered:{order.pk}",
        order=order,
        customer=order.customer,
    )


def send_doa_received(claim):
    order = claim.order
    return send_transactional(
        "doa_received",
        order.email,
        {"order": order, "claim": claim},
        dedupe_key=f"doa_received:{claim.pk}",
        order=order,
        customer=order.customer,
    )


def send_doa_resolved(claim):
    order = claim.order
    return send_transactional(
        "doa_resolved",
        order.email,
        {"order": order, "claim": claim},
        dedupe_key=f"doa_resolved:{claim.pk}:{claim.status}",
        order=order,
        customer=order.customer,
    )


def send_gift_card(card):
    recipient = card.recipient_email or (card.issued_to.email if card.issued_to else "")
    return send_transactional(
        "gift_card_issued",
        recipient,
        {"card": card},
        dedupe_key=f"gift_card_issued:{card.pk}",
        customer=card.issued_to,
    )


def send_abandoned_cart(abandoned):
    return send_transactional(
        "abandoned_cart",
        abandoned.email,
        {
            "items": abandoned.items,
            "subtotal": abandoned.subtotal,
            "wysiwyg": abandoned.contains_wysiwyg,
            "first_name": (
                abandoned.customer.user.first_name if abandoned.customer else ""
            ),
            "recovery_url": absolute_url(abandoned.get_recovery_url()),
        },
        dedupe_key=f"abandoned_cart:{abandoned.pk}:{abandoned.reminders_sent}",
        customer=abandoned.customer,
    )


def send_back_in_stock(item):
    return send_transactional(
        "back_in_stock",
        item.customer.email,
        {
            "product": item.product,
            "item": item,
            "product_url": absolute_url(item.product.get_absolute_url()),
        },
        dedupe_key=f"back_in_stock:{item.pk}",
        customer=item.customer,
    )


def send_review_request(order):
    return send_transactional(
        "review_request",
        order.email,
        {"order": order},
        dedupe_key=f"review_request:{order.pk}",
        order=order,
        customer=order.customer,
    )


def send_points_expiring(customer, points, expires_on, value):
    from django.urls import reverse

    return send_transactional(
        "points_expiring",
        customer.email,
        {
            "first_name": customer.user.first_name,
            "points": points,
            "expires_on": expires_on,
            "value": value,
            "shop_url": absolute_url(reverse("catalog:shop")),
        },
        dedupe_key=f"points_expiring:{customer.pk}:{expires_on:%Y-%m-%d}",
        customer=customer,
    )
