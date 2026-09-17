"""Credits held in the session while a customer is checking out."""

from apps.rewards.models import DiscountCode, GiftCard, RewardsSettings, balance_for

DISCOUNT_KEY = "checkout_discount"
POINTS_KEY = "checkout_points"
GIFT_CARDS_KEY = "checkout_gift_cards"


class AppliedCredits:
    """Reads and writes the discount/points/gift-card choices in the session."""

    def __init__(self, request):
        self.session = request.session
        self.request = request

    # --- discount code ---------------------------------------------------
    @property
    def discount_code(self):
        code = self.session.get(DISCOUNT_KEY)
        if not code:
            return None
        return DiscountCode.objects.filter(code=code, is_active=True).first()

    def apply_discount(self, code_text, subtotal, customer=None):
        """Returns (ok, message)."""
        code = DiscountCode.objects.filter(code=code_text.strip().upper()).first()
        if code is None:
            return False, "We don't recognise that code."
        ok, message = code.check_usable(subtotal, customer=customer)
        if not ok:
            return False, message
        self.session[DISCOUNT_KEY] = code.code
        self.session.modified = True
        return True, f"Applied {code.code}."

    def clear_discount(self):
        self.session.pop(DISCOUNT_KEY, None)
        self.session.modified = True

    # --- points ----------------------------------------------------------
    @property
    def points(self):
        return int(self.session.get(POINTS_KEY, 0) or 0)

    def apply_points(self, points, customer, live_sale_running=False):
        rewards = RewardsSettings.load()
        if not rewards.is_enabled:
            return False, "The rewards programme is not running."
        if customer is None:
            return False, "Sign in to spend reward points."
        if live_sale_running and not rewards.redeemable_during_sales:
            return False, "Points cannot be redeemed during a live sale — but you still earn them."
        points = int(points)
        if points < rewards.minimum_redemption:
            return False, f"Redeem at least {rewards.minimum_redemption} points."
        if points > balance_for(customer):
            return False, "That is more points than you have."
        self.session[POINTS_KEY] = points
        self.session.modified = True
        return True, f"Applied {points} points."

    def clear_points(self):
        self.session.pop(POINTS_KEY, None)
        self.session.modified = True

    # --- gift cards ------------------------------------------------------
    @property
    def gift_card_codes(self):
        return list(self.session.get(GIFT_CARDS_KEY, []))

    @property
    def gift_cards(self):
        codes = self.gift_card_codes
        if not codes:
            return []
        found = {c.code: c for c in GiftCard.objects.filter(code__in=codes)}
        return [found[c] for c in codes if c in found and found[c].is_redeemable]

    def apply_gift_card(self, code_text):
        code_text = code_text.strip().upper()
        card = GiftCard.objects.filter(code=code_text).first()
        if card is None:
            return False, "We don't recognise that gift card."
        if not card.is_redeemable:
            return False, "That gift card has no balance left."
        codes = self.gift_card_codes
        if card.code in codes:
            return False, "That gift card is already applied."
        codes.append(card.code)
        self.session[GIFT_CARDS_KEY] = codes
        self.session.modified = True
        return True, f"Applied gift card (${card.balance} available)."

    def remove_gift_card(self, code_text):
        codes = [c for c in self.gift_card_codes if c != code_text.strip().upper()]
        self.session[GIFT_CARDS_KEY] = codes
        self.session.modified = True

    def clear(self):
        for key in (DISCOUNT_KEY, POINTS_KEY, GIFT_CARDS_KEY):
            self.session.pop(key, None)
        self.session.modified = True
