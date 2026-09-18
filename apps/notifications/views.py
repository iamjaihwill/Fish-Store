"""Cart recovery from an emailed link."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from apps.notifications.models import AbandonedCart
from apps.notifications.services import restore_cart


def recover_cart(request, token):
    """Restore a stored cart into this session and send them to the cart.

    The token is the only credential, so it is single-purpose: it rebuilds a
    cart and nothing else. It never signs anyone in, and it never exposes the
    address or payment details on the account.
    """
    abandoned = get_object_or_404(AbandonedCart, token=token)

    if abandoned.is_recovered:
        messages.info(request, "That cart was already checked out. Here's the shop.")
        return redirect("catalog:shop")

    restored, skipped = restore_cart(request, abandoned)

    if restored and skipped:
        messages.warning(
            request,
            f"We put {restored} item{'s' if restored != 1 else ''} back in your cart. "
            f"{skipped} sold out while you were away.",
        )
    elif restored:
        messages.success(request, "Your cart is back — pick up where you left off.")
    else:
        messages.info(
            request,
            "Everything in that cart has sold. Corals move fast — here's what's in now.",
        )
        return redirect("catalog:shop")

    return redirect("shop:cart")
