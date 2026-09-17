from apps.accounts.models import Customer


def account(request):
    """Expose the signed-in customer and wishlist size to every template."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"customer": None, "wishlist_count": 0}
    customer = Customer.objects.filter(user=request.user).first()
    return {
        "customer": customer,
        "wishlist_count": customer.wishlist_items.count() if customer else 0,
    }
