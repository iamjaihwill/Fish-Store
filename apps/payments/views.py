"""Payment return and webhook endpoints."""

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.payments.gateway import get_backend
from apps.payments.models import Payment
from apps.shop.models import Order


def pay(request, number):
    """Card confirmation step for an order awaiting payment."""
    order = get_object_or_404(Order, number=number)
    if number not in request.session.get("recent_orders", []):
        return redirect("shop:order_lookup")

    payment = order.payments.exclude(status=Payment.Status.FAILED).first()
    return render(
        request,
        "payments/pay.html",
        {
            "order": order,
            "payment": payment,
            "backend": get_backend(),
            "publishable_key": _publishable_key(),
        },
    )


def _publishable_key():
    from django.conf import settings

    return getattr(settings, "STRIPE_PUBLISHABLE_KEY", "")


@csrf_exempt
@require_POST
def webhook(request):
    """Provider callback. CSRF-exempt because the caller is the provider.

    Authentication is the signed payload, verified by the backend, not a
    session cookie.
    """
    backend = get_backend()
    handled, message = backend.handle_webhook(request)
    if not handled:
        return HttpResponseBadRequest(message)
    return HttpResponse(message)
