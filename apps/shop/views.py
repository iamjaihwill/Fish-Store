"""Cart, checkout, order tracking and DOA claims."""

from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.shop.cart import Cart
from apps.shop.forms import CheckoutForm, DoaClaimForm, OrderLookupForm
from apps.shop.models import Order
from apps.shop.services import OutOfStock, place_order, send_order_confirmation

ORDER_SESSION_KEY = "recent_orders"


def _back(request, fallback="shop:cart"):
    return HttpResponseRedirect(request.POST.get("next") or reverse(fallback))


@require_POST
def add_to_cart(request, slug):
    product = get_object_or_404(Product.objects.published(), slug=slug)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    cart = Cart(request)
    before = len(cart)
    placed = cart.add(product, quantity)

    if placed == before:
        messages.error(
            request,
            f"{product.name} is sold out."
            if product.is_sold_out
            else f"We only have {product.max_orderable} of {product.name} left.",
        )
    elif product.is_wysiwyg:
        messages.success(
            request, f"{product.name} is held in your cart — it's a one-of-a-kind piece."
        )
    else:
        messages.success(request, f"Added {product.name} to your cart.")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"count": len(cart), "subtotal": str(cart.subtotal)})
    return _back(request)


@require_POST
def update_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    cart = Cart(request)
    try:
        quantity = int(request.POST.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0
    if quantity <= 0:
        cart.remove(product)
        messages.info(request, f"Removed {product.name}.")
    else:
        final = cart.set_quantity(product, quantity)
        if final < quantity:
            messages.warning(
                request, f"Only {final} of {product.name} available — cart updated."
            )
    return _back(request)


@require_POST
def remove_from_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    Cart(request).remove(product)
    messages.info(request, f"Removed {product.name}.")
    return _back(request)


def cart_detail(request):
    cart = Cart(request)
    return render(request, "shop/cart.html", {"cart": cart, "problems": cart.problems()})


def checkout(request):
    cart = Cart(request)
    if cart.is_empty:
        messages.info(request, "Your cart is empty.")
        return redirect("catalog:shop")

    adjusted = cart.sync_to_stock()
    for product, quantity in adjusted:
        messages.warning(
            request,
            f"{product.name} is down to {quantity} — we adjusted your cart."
            if quantity
            else f"{product.name} sold out and was removed from your cart.",
        )
    if cart.is_empty:
        return redirect("catalog:shop")

    requires_terms = cart.contains_livestock
    customer = None
    if request.user.is_authenticated:
        from apps.accounts.views import get_customer

        customer = get_customer(request)

    if request.method == "POST":
        form = CheckoutForm(request.POST, requires_livestock_terms=requires_terms)
        if form.is_valid():
            try:
                order = place_order(cart, form.cleaned_data, customer=customer)
            except OutOfStock as exc:
                messages.error(
                    request,
                    f"{exc.product.name} sold out while you were checking out. "
                    "Your cart has been updated.",
                )
                cart.sync_to_stock()
                return redirect("shop:checkout")
            send_order_confirmation(order)
            recent = request.session.get(ORDER_SESSION_KEY, [])
            request.session[ORDER_SESSION_KEY] = [order.number, *recent][:10]
            return redirect("shop:order_confirmation", number=order.number)
    else:
        initial = {}
        if customer:
            initial["email"] = request.user.email
            address = customer.default_address()
            if address:
                initial.update(address.as_checkout_initial())
            else:
                initial["first_name"] = request.user.first_name
                initial["last_name"] = request.user.last_name
                initial["phone"] = customer.phone
        form = CheckoutForm(initial=initial, requires_livestock_terms=requires_terms)

    return render(
        request,
        "shop/checkout.html",
        {
            "cart": cart,
            "form": form,
            "requires_terms": requires_terms,
            "customer": customer,
        },
    )


def order_confirmation(request, number):
    order = get_object_or_404(Order, number=number)
    if number not in request.session.get(ORDER_SESSION_KEY, []):
        return redirect("shop:order_lookup")
    return render(request, "shop/order_confirmation.html", {"order": order})


def order_lookup(request):
    order = None
    if request.method == "POST":
        form = OrderLookupForm(request.POST)
        if form.is_valid():
            order = form.find_order()
            if order:
                recent = request.session.get(ORDER_SESSION_KEY, [])
                request.session[ORDER_SESSION_KEY] = [order.number, *recent][:10]
                return redirect("shop:order_detail", number=order.number)
            messages.error(request, "We couldn't find an order with those details.")
    else:
        form = OrderLookupForm()
    return render(request, "shop/order_lookup.html", {"form": form})


def order_detail(request, number):
    order = get_object_or_404(Order, number=number)
    if number not in request.session.get(ORDER_SESSION_KEY, []) and not request.user.is_staff:
        messages.info(request, "Look up your order to view it.")
        return redirect("shop:order_lookup")
    return render(request, "shop/order_detail.html", {"order": order})


def doa_claim(request, number):
    order = get_object_or_404(Order, number=number)
    if number not in request.session.get(ORDER_SESSION_KEY, []):
        return redirect("shop:order_lookup")

    if request.method == "POST":
        form = DoaClaimForm(request.POST, request.FILES)
        if form.is_valid():
            claim = form.save(commit=False)
            claim.order = order
            claim.save()
            messages.success(
                request,
                "Claim received. Our livestock team reviews claims the same day.",
            )
            return redirect("shop:order_detail", number=order.number)
    else:
        form = DoaClaimForm()

    return render(
        request,
        "shop/doa_claim.html",
        {"order": order, "form": form, "now": timezone.now()},
    )
