"""Sending transactional email, and capturing carts for recovery."""

from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.template import Context, Template

from apps.notifications.models import AbandonedCart, EmailLog, EmailTemplate


def render_template(body, context):
    """Render staff-authored copy.

    Autoescaping is off because these are plain-text emails -- escaping would
    turn an apostrophe in a coral name into &#x27; in someone's inbox.
    """
    return Template(body).render(Context(context, autoescape=False))


def send_transactional(
    key,
    recipient,
    context=None,
    *,
    dedupe_key="",
    order=None,
    customer=None,
    site=None,
):
    """Send one transactional email. Returns the EmailLog row, or None.

    Nothing is sent when the template is switched off, the recipient is blank,
    or an identical send was already logged -- so a retried webhook or a
    re-run command cannot email a customer twice.
    """
    if not recipient:
        return None

    subject_template, body_template, enabled = EmailTemplate.resolve(key)
    if not enabled or body_template is None:
        return None

    if dedupe_key and EmailLog.objects.filter(
        dedupe_key=dedupe_key, status=EmailLog.Status.SENT
    ).exists():
        return None

    from apps.cms.models import SiteSettings
    from apps.rewards.models import RewardsSettings

    context = dict(context or {})
    context.setdefault("site", site or SiteSettings.load())
    context.setdefault("rewards", RewardsSettings.load())
    context.setdefault("base_url", getattr(settings, "SITE_BASE_URL", ""))

    subject = render_template(subject_template, context).strip()
    body = render_template(body_template, context)

    log = EmailLog(
        key=key,
        recipient=recipient,
        subject=subject,
        body=body,
        dedupe_key=dedupe_key,
        order=order,
        customer=customer,
    )
    try:
        sent = send_mail(
            subject=subject,
            message=body,
            from_email=None,
            recipient_list=[recipient],
            fail_silently=False,
        )
        log.status = EmailLog.Status.SENT if sent else EmailLog.Status.FAILED
    except Exception as exc:  # pragma: no cover - transport failures
        # A dead SMTP server must never take down a checkout.
        log.status = EmailLog.Status.FAILED
        log.error = str(exc)[:300]
    log.save()
    return log


def absolute_url(path):
    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


# --- abandoned carts -----------------------------------------------------
def snapshot_cart(cart):
    """Serialise a cart into the shape stored on AbandonedCart."""
    items = []
    contains_wysiwyg = False
    for line in cart.lines:
        items.append(
            {
                "product_id": line.product.pk,
                "variant_id": line.variant.pk if line.variant else None,
                "name": line.label,
                "slug": line.product.slug,
                "quantity": line.quantity,
                "price": str(line.unit_price),
            }
        )
        contains_wysiwyg = contains_wysiwyg or line.product.is_wysiwyg
    return items, contains_wysiwyg


def capture_cart(request, cart, email="", customer=None):
    """Remember a cart against a known email so it can be recovered.

    Called when we learn who is holding the cart -- they signed in, or they
    typed an email at checkout. An empty cart clears any stored copy instead
    of leaving a stale snapshot to be emailed about.
    """
    email = (email or "").strip().lower()
    if customer is None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            from apps.accounts.models import Customer

            customer = Customer.objects.filter(user=request.user).first()
    if not email and customer is not None:
        email = customer.email.lower()
    if not email:
        return None

    existing = AbandonedCart.objects.open().filter(email__iexact=email).first()

    if cart.is_empty:
        if existing:
            existing.delete()
        return None

    items, contains_wysiwyg = snapshot_cart(cart)
    if not items:
        return None

    if existing is None:
        existing = AbandonedCart(email=email)
    existing.customer = customer
    existing.items = items
    existing.subtotal = cart.subtotal
    existing.contains_wysiwyg = contains_wysiwyg
    existing.save()
    return existing


def mark_carts_recovered(order):
    """Close out any open cart for this order's email once they buy."""
    carts = AbandonedCart.objects.open().filter(email__iexact=order.email)
    count = 0
    for cart in carts:
        cart.mark_recovered(order)
        count += 1
    return count


def restore_cart(request, abandoned):
    """Put a stored cart back into the session. Returns (restored, skipped)."""
    from apps.catalog.models import Product, ProductVariant
    from apps.shop.cart import Cart

    cart = Cart(request)
    restored = skipped = 0
    for item in abandoned.items:
        product = Product.objects.filter(pk=item.get("product_id")).first()
        if product is None or not product.is_published:
            skipped += 1
            continue
        variant = None
        if item.get("variant_id"):
            variant = ProductVariant.objects.filter(
                pk=item["variant_id"], is_active=True
            ).first()
            if variant is None:
                skipped += 1
                continue
        placed = cart.add(product, item.get("quantity", 1), variant=variant)
        if placed:
            restored += 1
        else:
            skipped += 1
    return restored, skipped
