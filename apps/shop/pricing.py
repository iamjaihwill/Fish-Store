"""One place where an order total is computed.

Credits stack in a fixed order, because the order changes what the customer
pays: a discount code comes off the merchandise first, tax is charged on the
discounted goods, then points and finally gift cards are applied against what
is left -- including shipping and tax, since both behave like money.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.cms.models import SiteSettings
from apps.rewards.models import RewardsSettings, balance_for, money
from apps.shop.models import ZERO, quote_shipping


@dataclass
class Totals:
    subtotal: Decimal = ZERO
    discount_total: Decimal = ZERO
    shipping_total: Decimal = ZERO
    tax_total: Decimal = ZERO
    points_redeemed: int = 0
    points_value: Decimal = ZERO
    gift_card_total: Decimal = ZERO
    grand_total: Decimal = ZERO
    gift_card_allocations: list = field(default_factory=list)

    @property
    def credits_applied(self):
        return self.discount_total + self.points_value + self.gift_card_total

    @property
    def is_fully_covered(self):
        return self.grand_total <= ZERO


def quote(
    subtotal,
    *,
    contains_livestock=False,
    discount_code=None,
    points=0,
    gift_cards=(),
    customer=None,
    site=None,
    rewards=None,
):
    """Compute a full set of totals. Pure: nothing is written."""
    site = site or SiteSettings.load()
    rewards = rewards or RewardsSettings.load()
    subtotal = money(subtotal)

    totals = Totals(subtotal=subtotal)
    totals.shipping_total = quote_shipping(subtotal, contains_livestock, site)

    if discount_code is not None:
        totals.discount_total = min(
            discount_code.discount_for(subtotal, totals.shipping_total), subtotal
        )
        if discount_code.kind == discount_code.Kind.FREE_SHIPPING:
            totals.discount_total = ZERO
            totals.shipping_total = ZERO

    discounted_goods = subtotal - totals.discount_total
    totals.tax_total = money(
        discounted_goods * site.tax_rate_percent / Decimal("100")
    )

    running = discounted_goods + totals.shipping_total + totals.tax_total

    # Points, capped by the balance and by what is left to pay.
    if points and rewards.is_enabled and customer is not None:
        usable = min(points, balance_for(customer))
        if usable >= rewards.minimum_redemption:
            value = min(rewards.value_of(usable), running)
            # Only charge the customer the points the discount actually used.
            spent = rewards.points_needed_for(value) if value < rewards.value_of(usable) else usable
            totals.points_redeemed = min(spent, usable)
            totals.points_value = money(value)
            running = money(running - totals.points_value)

    # Gift cards last: they are money and can cover shipping and tax.
    for card in gift_cards:
        if running <= ZERO:
            break
        take = card.redeemable_amount(running)
        if take <= ZERO:
            continue
        totals.gift_card_allocations.append((card, take))
        totals.gift_card_total = money(totals.gift_card_total + take)
        running = money(running - take)

    totals.grand_total = max(money(running), ZERO)
    return totals
