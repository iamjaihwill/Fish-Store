from apps.shop.cart import Cart


def cart(request):
    """Expose a lazy cart summary to the header on every page."""
    if not hasattr(request, "session"):
        return {}
    return {"cart_summary": Cart(request)}
