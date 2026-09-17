"""Storefront forms: checkout, order lookup and DOA claims."""

from django import forms
from django.utils import timezone

from apps.shop.models import DoaClaim, Order

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
]


class CheckoutForm(forms.Form):
    email = forms.EmailField(label="Email")
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    phone = forms.CharField(
        max_length=40,
        help_text="The carrier needs a daytime number for overnight livestock.",
    )
    address_line1 = forms.CharField(max_length=160, label="Address")
    address_line2 = forms.CharField(
        max_length=160, required=False, label="Apartment, suite, etc."
    )
    city = forms.CharField(max_length=80)
    state = forms.ChoiceField(choices=[(s, s) for s in STATES])
    postal_code = forms.CharField(max_length=20, label="ZIP code")
    country = forms.CharField(max_length=60, initial="United States")
    requested_ship_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Pick a day you can receive the box. We ship livestock overnight only.",
    )
    hold_for_weather = forms.BooleanField(
        required=False,
        label="Hold my order if temperatures are unsafe",
        initial=True,
    )
    customer_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Order notes",
    )
    accepts_livestock_terms = forms.BooleanField(
        required=False,
        label="I have read the Live Arrival Guarantee and will be home to receive the box.",
    )

    def __init__(self, *args, requires_livestock_terms=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.requires_livestock_terms = requires_livestock_terms
        if requires_livestock_terms:
            self.fields["accepts_livestock_terms"].required = True

    def clean_requested_ship_date(self):
        value = self.cleaned_data.get("requested_ship_date")
        if value and value < timezone.localdate():
            raise forms.ValidationError("Pick a date that has not already passed.")
        return value


class OrderLookupForm(forms.Form):
    number = forms.CharField(label="Order number", max_length=20)
    email = forms.EmailField(label="Email on the order")

    def find_order(self):
        return Order.objects.filter(
            number__iexact=self.cleaned_data["number"].strip(),
            email__iexact=self.cleaned_data["email"].strip(),
        ).first()


class DoaClaimForm(forms.ModelForm):
    class Meta:
        model = DoaClaim
        fields = ["items_affected", "details", "photo"]
        widgets = {"details": forms.Textarea(attrs={"rows": 5})}


class ContactForm(forms.Form):
    name = forms.CharField(max_length=120)
    email = forms.EmailField()
    order_reference = forms.CharField(
        max_length=40, required=False, label="Order number (optional)"
    )
    subject = forms.CharField(max_length=160, required=False)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 6}))


class NewsletterForm(forms.Form):
    email = forms.EmailField(label="", widget=forms.EmailInput(
        attrs={"placeholder": "you@example.com"}
    ))
