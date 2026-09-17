"""Account forms: registration, profile, addresses, wholesale applications."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.accounts.models import Address, Customer

User = get_user_model()


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    phone = forms.CharField(max_length=40, required=False)
    accepts_marketing = forms.BooleanField(
        required=False, initial=True, label="Send me drop announcements"
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses that email address.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # The storefront identifies people by email; username is an implementation
        # detail, so keep them in sync rather than asking for both.
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            Customer.objects.create(
                user=user,
                phone=self.cleaned_data.get("phone", ""),
                accepts_marketing=self.cleaned_data.get("accepts_marketing", False),
            )
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Email")

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)

    class Meta:
        model = Customer
        fields = ["phone", "accepts_marketing"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name

    def save(self, commit=True):
        customer = super().save(commit=commit)
        user = customer.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save(update_fields=["first_name", "last_name"])
        return customer


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        exclude = ["customer"]
        widgets = {"state": forms.TextInput(attrs={"maxlength": 2})}


class WholesaleApplicationForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["wholesale_company", "wholesale_tax_id"]
        labels = {
            "wholesale_company": "Business name",
            "wholesale_tax_id": "Resale / tax ID",
        }

    def save(self, commit=True):
        customer = super().save(commit=False)
        customer.tier = Customer.Tier.WHOLESALE
        # Approval is a staff action; applying only records the request.
        customer.wholesale_approved_at = None
        if commit:
            customer.save()
        return customer
