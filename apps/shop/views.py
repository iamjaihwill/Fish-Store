"""Cart, checkout, order tracking and DOA claims."""

from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Product, ProductVariant
from apps.shop.cart import Cart
from apps.shop.forms import CheckoutForm, DoaClaimForm, OrderLookupForm
from apps.shop.models import Order
from apps.rewards.checkout import AppliedCredits
from apps.shop.additions import CannotAddToOrder, add_to_order, open_orders_for
from apps.shop.pricing import quote
from apps.shop.services import OutOfStock, place_order, send_order_confirmation

ORDER_SESSION_KEY = "recent_orders"


def _back(request, fallback="shop:cart"):
    return HttpResponseRedirect(request.POST.get("next") or reverse(fallback))


def _requested_variant(request, product):
    """The variant chosen on the form, validated as belonging to this product."""
    variant_id = request.POST.get("variant")
    if not variant_id:
        return None
    return get_object_or_404(
        ProductVariant, pk=variant_id, product=product, is_active=True
    )


@require_POST
def add_to_cart(request, slug):
    product = get_object_or_404(Product.objects.published(), slug=slug)
    variant = _requested_variant(request, product)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    cart = Cart(request)
    before = len(cart)
    placed = cart.add(product, quantity, variant=variant)

    label = f"{product.name} ({variant.name})" if variant else product.name
    ceiling = variant.max_orderable if variant else product.max_orderable
    if placed == before:
        messages.error(
            request,
            f"{label} is sold out."
            if ceiling == 0
            else f"We only have {ceiling} of {label} left.",
        )
    elif product.is_wysiwyg:
        messages.success(
            request, f"{label} is held in your cart — it's a one-of-a-kind piece."
        )
    else:
        messages.success(request, f"Added {label} to your cart.")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"count": len(cart), "subtotal": str(cart.subtotal)})
    return _back(request)


@require_POST
def update_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    variant = _requested_variant(request, product)
    label = f"{product.name} ({variant.name})" if variant else product.name
    cart = Cart(request)
    try:
        quantity = int(request.POST.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0
    if quantity <= 0:
        cart.remove(product, variant=variant)
        messages.info(request, f"Removed {label}.")
    else:
        final = cart.set_quantity(product, quantity, variant=variant)
        if final < quantity:
            messages.warning(
                request, f"Only {final} of {label} available — cart updated."
            )
    return _back(request)


@require_POST
def remove_from_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    variant = _requested_variant(request, product)
    Cart(request).remove(product, variant=variant)
    messages.info(request, f"Removed {product.name}.")
    return _back(request)


def cart_detail(request):
    cart = Cart(request)
    return render(
        request,
        "shop/cart.html",
        {
            "cart": cart,
            "problems": cart.problems(),
            "open_orders": open_orders_for(request, _current_customer(request)),
        },
    )


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

    credits = AppliedCredits(request)
    live_sale_running = _live_sale_running()
    totals = quote(
        cart.subtotal,
        contains_livestock=cart.contains_livestock,
        discount_code=credits.discount_code,
        points=credits.points,
        gift_cards=credits.gift_cards,
        customer=customer,
    )

    if request.method == "POST":
        form = CheckoutForm(request.POST, requires_livestock_terms=requires_terms)
        if form.is_valid():
            try:
                order = place_order(
                    cart, form.cleaned_data, customer=customer, credits=credits
                )
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

            from apps.payments.gateway import charge_order
            from apps.payments.models import Payment

            payment = charge_order(order)
            if payment.status == Payment.Status.FAILED:
                messages.error(
                    request,
                    f"We couldn't start the payment: {payment.error_message} "
                    "Your order is saved — you can retry from the order page.",
                )
            elif payment.status == Payment.Status.REQUIRES_ACTION:
                return redirect("payments:pay", number=order.number)
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

    from apps.cms.models import SiteSettings
    from apps.rewards.models import RewardsSettings, balance_for

    site_settings = SiteSettings.load()
    return render(
        request,
        "shop/checkout.html",
        {
            "cart": cart,
            "form": form,
            "requires_terms": requires_terms,
            "customer": customer,
            "totals": totals,
            "credits": credits,
            "next_ship_date": site_settings.next_ship_date(),
            "points_balance": balance_for(customer),
            "rewards": RewardsSettings.load(),
            "live_sale_running": live_sale_running,
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


def _live_sale_running():
    """Is a live or flash sale on right now? Points cannot be spent during one."""
    from apps.cms.models import LiveSaleEvent

    return any(event.is_running for event in LiveSaleEvent.objects.filter(is_active=True))


@require_POST
def apply_discount(request):
    cart = Cart(request)
    credits = AppliedCredits(request)
    customer = None
    if request.user.is_authenticated:
        from apps.accounts.views import get_customer

        customer = get_customer(request)

    code = request.POST.get("code", "")
    if not code.strip():
        credits.clear_discount()
        messages.info(request, "Discount code removed.")
    else:
        ok, message = credits.apply_discount(code, cart.subtotal, customer=customer)
        (messages.success if ok else messages.error)(request, message)
    return redirect("shop:checkout")


@require_POST
def apply_points(request):
    credits = AppliedCredits(request)
    customer = None
    if request.user.is_authenticated:
        from apps.accounts.views import get_customer

        customer = get_customer(request)

    raw = request.POST.get("points", "").strip()
    if not raw:
        credits.clear_points()
        messages.info(request, "Reward points removed.")
        return redirect("shop:checkout")

    try:
        points = int(raw)
    except ValueError:
        messages.error(request, "Enter a whole number of points.")
        return redirect("shop:checkout")

    ok, message = credits.apply_points(
        points, customer, live_sale_running=_live_sale_running()
    )
    (messages.success if ok else messages.error)(request, message)
    return redirect("shop:checkout")


@require_POST
def apply_gift_card(request):
    credits = AppliedCredits(request)
    code = request.POST.get("code", "")
    remove = request.POST.get("remove")
    if remove:
        credits.remove_gift_card(remove)
        messages.info(request, "Gift card removed.")
    else:
        ok, message = credits.apply_gift_card(code)
        (messages.success if ok else messages.error)(request, message)
    return redirect("shop:checkout")


def _current_customer(request):
    if not request.user.is_authenticated:
        return None
    from apps.accounts.views import get_customer

    return get_customer(request)


def add_to_existing_order(request):
    """Live sale flow: put this cart into a box that has not shipped yet."""
    cart = Cart(request)
    customer = _current_customer(request)
    orders = open_orders_for(request, customer)

    if request.method == "POST":
        number = request.POST.get("order")
        order = next((o for o in orders if o.number == number), None)
        if order is None:
            messages.error(request, "We couldn't find that open order.")
            return redirect("shop:add_to_existing")
        try:
            added = add_to_order(order, cart)
        except OutOfStock as exc:
            messages.error(request, f"{exc.product.name} sold out before we could add it.")
            return redirect("shop:cart")
        except CannotAddToOrder as exc:
            messages.error(request, str(exc))
            return redirect("shop:cart")

        messages.success(
            request,
            f"Added {len(added)} item{'s' if len(added) != 1 else ''} to order "
            f"{order.number} — no second shipping charge.",
        )
        return redirect("shop:order_detail", number=order.number)

    return render(
        request,
        "shop/add_to_order.html",
        {"cart": cart, "orders": orders},
    )
