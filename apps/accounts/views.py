"""Account area: dashboard, orders, addresses, wishlist, wholesale."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import (
    AddressForm,
    ProfileForm,
    RegistrationForm,
    WholesaleApplicationForm,
)
from apps.accounts.models import Address, Customer, WishlistItem
from apps.catalog.models import Product


def get_customer(request):
    """The Customer for the logged-in user, creating it if it is missing."""
    if not request.user.is_authenticated:
        return None
    customer, _ = Customer.objects.get_or_create(user=request.user)
    return customer


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            claimed = user.customer.claim_guest_orders()

            from apps.notifications.senders import send_welcome

            send_welcome(user.customer, claimed)
            if claimed:
                messages.success(
                    request,
                    f"Welcome. We linked {claimed} previous order"
                    f"{'s' if claimed != 1 else ''} to your new account.",
                )
            else:
                messages.success(request, "Welcome to Reef & Rift.")
            return redirect("accounts:dashboard")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def dashboard(request):
    customer = get_customer(request)
    orders = customer.orders()[:5]
    return render(
        request,
        "accounts/dashboard.html",
        {
            "customer": customer,
            "orders": orders,
            "address": customer.default_address(),
            "wishlist_count": customer.wishlist_items.count(),
        },
    )


@login_required
def order_history(request):
    customer = get_customer(request)
    return render(
        request,
        "accounts/orders.html",
        {"orders": customer.orders().prefetch_related("items")},
    )


@login_required
def profile(request):
    customer = get_customer(request)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=customer)
    return render(request, "accounts/profile.html", {"form": form, "customer": customer})


@login_required
def address_list(request):
    customer = get_customer(request)
    return render(
        request, "accounts/addresses.html", {"addresses": customer.addresses.all()}
    )


@login_required
def address_edit(request, pk=None):
    customer = get_customer(request)
    instance = get_object_or_404(Address, pk=pk, customer=customer) if pk else None
    if request.method == "POST":
        form = AddressForm(request.POST, instance=instance)
        if form.is_valid():
            address = form.save(commit=False)
            address.customer = customer
            if not customer.addresses.exists():
                address.is_default = True
            address.save()
            messages.success(request, "Address saved.")
            return redirect("accounts:addresses")
    else:
        form = AddressForm(instance=instance)
    return render(
        request, "accounts/address_form.html", {"form": form, "instance": instance}
    )


@login_required
@require_POST
def address_delete(request, pk):
    customer = get_customer(request)
    get_object_or_404(Address, pk=pk, customer=customer).delete()
    messages.info(request, "Address removed.")
    return redirect("accounts:addresses")


@login_required
def wishlist(request):
    customer = get_customer(request)
    items = customer.wishlist_items.select_related("product").prefetch_related(
        "product__images"
    )
    return render(request, "accounts/wishlist.html", {"items": items})


@require_POST
def wishlist_toggle(request, slug):
    """Save or unsave a product. Anonymous visitors are sent to log in first."""
    product = get_object_or_404(Product, slug=slug)
    if not request.user.is_authenticated:
        messages.info(request, "Sign in to save corals to your wishlist.")
        return redirect("accounts:login")

    customer = get_customer(request)
    item = customer.wishlist_items.filter(product=product).first()
    if item:
        item.delete()
        messages.info(request, f"Removed {product.name} from your wishlist.")
    else:
        WishlistItem.objects.create(customer=customer, product=product)
        messages.success(
            request,
            f"Saved {product.name}."
            + (
                " We'll email you when it's back in stock."
                if product.is_sold_out
                else ""
            ),
        )
    return redirect(request.POST.get("next") or product.get_absolute_url())


@login_required
@require_POST
def wishlist_add_all_to_cart(request):
    """TSA-style: turn saved items into a cart in one action."""
    from apps.shop.cart import Cart

    customer = get_customer(request)
    cart = Cart(request)
    added = skipped = 0
    for item in customer.wishlist_items.select_related("product"):
        if item.product.is_published and not item.product.is_sold_out:
            cart.add(item.product, 1)
            added += 1
        else:
            skipped += 1
    if added:
        messages.success(request, f"Added {added} saved item{'s' if added != 1 else ''} to your cart.")
    if skipped:
        messages.warning(request, f"{skipped} saved item{'s were' if skipped != 1 else ' was'} unavailable.")
    return redirect("shop:cart")


@login_required
def rewards(request):
    from apps.rewards.models import PointsTransaction, RewardsSettings, balance_for

    customer = get_customer(request)
    settings_obj = RewardsSettings.load()
    balance = balance_for(customer)
    return render(
        request,
        "accounts/rewards.html",
        {
            "customer": customer,
            "balance": balance,
            "balance_value": settings_obj.value_of(balance),
            "rewards": settings_obj,
            "history": PointsTransaction.objects.filter(customer=customer)[:30],
            "gift_cards": customer.gift_cards.filter(is_active=True),
        },
    )


@login_required
def wholesale(request):
    customer = get_customer(request)
    if request.method == "POST":
        form = WholesaleApplicationForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Application received. We review wholesale accounts within two business days.",
            )
            return redirect("accounts:wholesale")
    else:
        form = WholesaleApplicationForm(instance=customer)
    return render(
        request, "accounts/wholesale.html", {"form": form, "customer": customer}
    )
