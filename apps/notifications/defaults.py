"""Built-in copy for every transactional email.

These are the fallback. Staff override any of them by editing the matching
EmailTemplate row in the admin, which means a shop can change the wording of a
shipping notice without a deploy -- but a fresh install still sends sensible
email before anyone has touched the CMS.

Bodies are Django template syntax rendered against the context each sender
passes, with autoescaping off because these are plain text.
"""

DEFAULT_TEMPLATES = {
    "welcome": {
        "label": "Welcome (new account)",
        "subject": "Welcome to {{ site.store_name }}",
        "body": """Hi {{ first_name|default:"there" }},

Your account is set up. From here you can track orders, save corals to a
wishlist, and earn {{ rewards.points_per_dollar|floatformat:0 }} point per dollar on everything you buy.
{% if claimed %}
We also linked {{ claimed }} previous order{{ claimed|pluralize }} placed with this email address,
so your history is all in one place.
{% endif %}
Livestock ships overnight {{ site.shipping_days }}.

— {{ site.store_name }}
{{ site.contact_email }}
""",
    },
    "order_confirmation": {
        "label": "Order confirmation",
        "subject": "{{ site.store_name }} order {{ order.number }}",
        "body": """Thanks {{ order.first_name }}, we have your order.

{% for item in order.items.all %}  {{ item.quantity }} x {{ item.display_name }} — ${{ item.line_total }}
{% endfor %}
Subtotal: ${{ order.subtotal }}
{% if order.discount_total %}Discount: -${{ order.discount_total }}
{% endif %}Shipping: ${{ order.shipping_total }}
{% if order.tax_total %}Tax: ${{ order.tax_total }}
{% endif %}{% if order.points_value %}Reward points: -${{ order.points_value }}
{% endif %}{% if order.gift_card_total %}Gift card: -${{ order.gift_card_total }}
{% endif %}Total: ${{ order.grand_total }}

Shipping to:
{{ order.customer_name }}
{% for line in order.shipping_address_lines %}{{ line }}
{% endfor %}
{% if order.contains_livestock %}Livestock ships overnight {{ site.shipping_days }}.{% if order.requested_ship_date %} You requested {{ order.requested_ship_date|date:"l, F j" }}.{% endif %}
{% if order.hold_for_weather %}We will hold your box if temperatures are unsafe.
{% endif %}
{{ site.guarantee_headline }}: {{ site.guarantee_blurb }}
{% endif %}
Track it any time: {{ order_url }}

Questions? Reply to this email or write {{ site.contact_email }}.
""",
    },
    "payment_received": {
        "label": "Payment received",
        "subject": "Payment received for {{ order.number }}",
        "body": """Thanks {{ order.first_name }} — we've received ${{ payment.amount }} for order {{ order.number }}.

Your order is now in the queue to be packed.
{% if order.contains_livestock %}Livestock leaves the facility {{ site.shipping_days }}, and you'll get
tracking the morning your box ships.{% endif %}

{{ order_url }}

— {{ site.store_name }}
""",
    },
    "order_shipped": {
        "label": "Order shipped",
        "subject": "Your {{ site.store_name }} box is on the way ({{ order.number }})",
        "body": """{{ order.first_name }}, your box shipped.

{% if order.carrier %}Carrier: {{ order.carrier }}
{% endif %}{% if order.tracking_number %}Tracking: {{ order.tracking_number }}
{% endif %}
{% if order.contains_livestock %}IMPORTANT: someone needs to be present to receive this box. Livestock left
on a doorstep is not covered by the {{ site.guarantee_headline }}.

When it lands:
  1. Photograph anything that looks wrong BEFORE you open the bag.
  2. Float sealed bags 15 minutes, then drip acclimate for 45.
  3. Keep the lights low for the first day.

You have 8 hours from delivery to file a live arrival claim if something
arrives in distress.
{% endif %}
{{ order_url }}

— {{ site.store_name }}
""",
    },
    "order_delivered": {
        "label": "Order delivered (DOA window open)",
        "subject": "Delivered — your 8 hour arrival window is open ({{ order.number }})",
        "body": """{{ order.first_name }}, the carrier marked order {{ order.number }} as delivered.

If anything arrived in distress, file a claim within 8 hours{% if order.doa_window_closes_at %} — by
{{ order.doa_window_closes_at|date:"g:i a" }} today{% endif %}:

  {{ claim_url }}

Photograph the animal in the sealed bag it arrived in before you open it.
That photo is what lets us approve a credit without any argument.

Take your time acclimating. A coral that stays closed for two or three days
is normal, not a problem.

— {{ site.store_name }}
""",
    },
    "doa_received": {
        "label": "DOA claim received",
        "subject": "We got your arrival claim for {{ order.number }}",
        "body": """{{ order.first_name }}, your claim is in front of our livestock team.

Affected: {{ claim.items_affected }}

We review claims the same day they arrive. You do not need to do anything else
right now — don't throw anything away until we've replied.

— {{ site.store_name }}
""",
    },
    "doa_resolved": {
        "label": "DOA claim resolved",
        "subject": "Your arrival claim for {{ order.number }}",
        "body": """{{ order.first_name }}, we've reviewed your claim.

Outcome: {{ claim.get_status_display }}
{% if claim.credit_amount %}Credit issued: ${{ claim.credit_amount }}
{% endif %}{% if claim.staff_notes %}
{{ claim.staff_notes }}
{% endif %}
— {{ site.store_name }}
""",
    },
    "review_request": {
        "label": "Review request",
        "subject": "How did everything settle in?",
        "body": """{{ order.first_name }}, it's been a couple of weeks since order {{ order.number }} landed.

If you have a minute, other reefers would value hearing how it went:
{% for item in order.items.all %}
  {{ item.name }}
  {{ base_url }}{% url 'reviews:submit' item.product.slug %}
{% endfor %}

Honest reviews help more than glowing ones. If something isn't thriving, reply
to this email instead and we'll talk it through.

— {{ site.store_name }}
""",
    },
    "abandoned_cart": {
        "label": "Abandoned cart reminder",
        "subject": "{% if wysiwyg %}That one-of-a-kind piece is still unclaimed{% else %}You left something in your cart{% endif %}",
        "body": """{% if first_name %}{{ first_name }}, {% endif %}your cart is still here:

{% for item in items %}  {{ item.quantity }} x {{ item.name }} — ${{ item.price }}
{% endfor %}
Subtotal: ${{ subtotal }}
{% if wysiwyg %}
At least one of these is a WYSIWYG piece — there is exactly one of it, and it
stays available until someone else finishes checkout.
{% endif %}
Pick up where you left off:
  {{ recovery_url }}

Not interested any more? Ignore this and we won't chase it again.

— {{ site.store_name }}
""",
    },
    "back_in_stock": {
        "label": "Back in stock",
        "subject": "Back in stock: {{ product.name }}",
        "body": """{{ product.name }} is back in stock at {{ site.store_name }}.

You saved this one, so you get the heads-up first:

  {{ product.name }}{% if product.scientific_name %} ({{ product.scientific_name }}){% endif %}
  ${{ product.price_from }}
  {{ product_url }}

{% if product.is_wysiwyg %}This is a one-of-a-kind WYSIWYG piece — once it sells it is gone for good.
{% endif %}Livestock ships overnight {{ site.shipping_days }}.

— {{ site.store_name }}
""",
    },
    "points_expiring": {
        "label": "Reward points expiring",
        "subject": "{{ points }} reward points expire soon",
        "body": """{{ first_name|default:"Hi" }}, you have {{ points }} points expiring on {{ expires_on|date:"F j" }}.

That's ${{ value }} off your next order.

  {{ shop_url }}

Points can't be spent during live sales, so use them on a standard order.

— {{ site.store_name }}
""",
    },
    "gift_card_issued": {
        "label": "Gift card issued",
        "subject": "You've been sent a {{ site.store_name }} gift card",
        "body": """{% if card.message %}{{ card.message }}

{% endif %}Your gift card code is:

  {{ card.code }}

Balance: ${{ card.balance }}
{% if card.expires_at %}Expires: {{ card.expires_at|date:"F j, Y" }}
{% endif %}
Enter it at checkout. It covers livestock, dry goods, shipping and tax.

— {{ site.store_name }}
""",
    },
}
