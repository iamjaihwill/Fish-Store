from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Address, Customer, WishlistItem
from apps.catalog.models import Category, Product, ProductType
from apps.shop.models import Order

User = get_user_model()

REGISTRATION = {
    "first_name": "Sam",
    "last_name": "Rivera",
    "email": "sam@example.com",
    "phone": "555-0100",
    "password1": "reef-keeper-9182",
    "password2": "reef-keeper-9182",
    "accepts_marketing": "on",
}


class RegistrationTests(TestCase):
    def test_registration_creates_user_and_customer(self):
        response = self.client.post(reverse("accounts:register"), REGISTRATION)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(email="sam@example.com")
        self.assertEqual(user.username, "sam@example.com")
        self.assertTrue(Customer.objects.filter(user=user).exists())
        self.assertEqual(user.customer.phone, "555-0100")

    def test_email_is_lowercased_and_unique(self):
        self.client.post(reverse("accounts:register"), REGISTRATION)
        self.client.logout()
        response = self.client.post(
            reverse("accounts:register"), dict(REGISTRATION, email="SAM@example.com")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact="sam@example.com").count(), 1)

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("accounts:register"), dict(REGISTRATION, password2="different-9182")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_claims_previous_guest_orders(self):
        guest_order = Order.objects.create(
            email="sam@example.com", first_name="Sam", last_name="Rivera",
            phone="555-0100", address_line1="12 Coral Way", city="Wilmington",
            state="NC", postal_code="28401",
        )
        other = Order.objects.create(
            email="someone@example.com", first_name="Other", last_name="Person",
            phone="555-0101", address_line1="9 Reef Rd", city="Austin",
            state="TX", postal_code="78701",
        )
        self.client.post(reverse("accounts:register"), REGISTRATION)

        guest_order.refresh_from_db()
        other.refresh_from_db()
        customer = Customer.objects.get(user__email="sam@example.com")
        self.assertEqual(guest_order.customer, customer)
        self.assertIsNone(other.customer)

    def test_login_with_email(self):
        self.client.post(reverse("accounts:register"), REGISTRATION)
        self.client.logout()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "SAM@example.com", "password": "reef-keeper-9182"},
        )
        self.assertEqual(response.status_code, 302)

    def test_account_pages_require_login(self):
        for name in ["dashboard", "orders", "profile", "addresses", "wishlist", "wholesale"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"accounts:{name}"))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])


class SignedInTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "sam@example.com", "sam@example.com", "reef-keeper-9182",
            first_name="Sam", last_name="Rivera",
        )
        self.customer = Customer.objects.create(user=self.user, phone="555-0100")
        self.client.force_login(self.user)
        self.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        self.product = Product.objects.create(
            name="Torch", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=3,
        )


class AddressTests(SignedInTestCase):
    ADDRESS = {
        "label": "Home", "first_name": "Sam", "last_name": "Rivera",
        "phone": "555-0100", "address_line1": "12 Coral Way", "address_line2": "",
        "city": "Wilmington", "state": "NC", "postal_code": "28401",
        "country": "United States",
    }

    def test_first_address_becomes_the_default(self):
        self.client.post(reverse("accounts:address_new"), self.ADDRESS)
        address = Address.objects.get()
        self.assertTrue(address.is_default)

    def test_only_one_address_stays_default(self):
        self.client.post(reverse("accounts:address_new"), self.ADDRESS)
        self.client.post(
            reverse("accounts:address_new"),
            dict(self.ADDRESS, label="Shop", city="Raleigh", is_default="on"),
        )
        defaults = Address.objects.filter(customer=self.customer, is_default=True)
        self.assertEqual(defaults.count(), 1)
        self.assertEqual(defaults.get().label, "Shop")

    def test_address_can_be_deleted(self):
        self.client.post(reverse("accounts:address_new"), self.ADDRESS)
        address = Address.objects.get()
        self.client.post(reverse("accounts:address_delete", args=[address.pk]))
        self.assertEqual(Address.objects.count(), 0)

    def test_customers_cannot_touch_another_customer_address(self):
        other_user = User.objects.create_user("other@example.com", "other@example.com", "pw-19283")
        other_customer = Customer.objects.create(user=other_user)
        address = Address.objects.create(customer=other_customer, **self.ADDRESS)
        response = self.client.get(reverse("accounts:address_edit", args=[address.pk]))
        self.assertEqual(response.status_code, 404)

    def test_checkout_prefills_from_the_default_address(self):
        self.client.post(reverse("accounts:address_new"), self.ADDRESS)
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        response = self.client.get(reverse("shop:checkout"))
        self.assertEqual(response.context["form"].initial["address_line1"], "12 Coral Way")
        self.assertEqual(response.context["form"].initial["email"], "sam@example.com")


class WishlistTests(SignedInTestCase):
    def test_toggle_adds_then_removes(self):
        url = reverse("accounts:wishlist_toggle", args=[self.product.slug])
        self.client.post(url)
        self.assertEqual(WishlistItem.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_anonymous_toggle_redirects_to_login(self):
        self.client.logout()
        response = self.client.post(
            reverse("accounts:wishlist_toggle", args=[self.product.slug])
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_wishlist_page_lists_saved_products(self):
        WishlistItem.objects.create(customer=self.customer, product=self.product)
        response = self.client.get(reverse("accounts:wishlist"))
        self.assertContains(response, "Torch")

    def test_add_all_to_cart_skips_unavailable_items(self):
        sold_out = Product.objects.create(
            name="Gone Coral", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("50.00"), status=Product.Status.ACTIVE, stock_quantity=0,
        )
        WishlistItem.objects.create(customer=self.customer, product=self.product)
        WishlistItem.objects.create(customer=self.customer, product=sold_out)

        response = self.client.post(reverse("accounts:wishlist_add_all"))
        self.assertRedirects(response, reverse("shop:cart"))
        cart_page = self.client.get(reverse("shop:cart"))
        self.assertContains(cart_page, "Torch")
        self.assertNotContains(cart_page, "Gone Coral")

    def test_a_product_can_only_be_saved_once(self):
        WishlistItem.objects.create(customer=self.customer, product=self.product)
        with self.assertRaises(Exception):
            WishlistItem.objects.create(customer=self.customer, product=self.product)


class OrderHistoryTests(SignedInTestCase):
    def test_orders_placed_while_signed_in_are_linked(self):
        self.client.post(reverse("shop:add_to_cart", args=[self.product.slug]), {"quantity": 1})
        self.client.post(
            reverse("shop:checkout"),
            {
                "email": "sam@example.com", "first_name": "Sam", "last_name": "Rivera",
                "phone": "555-0100", "address_line1": "12 Coral Way", "city": "Wilmington",
                "state": "NC", "postal_code": "28401", "country": "United States",
                "accepts_livestock_terms": "on",
            },
        )
        order = Order.objects.get()
        self.assertEqual(order.customer, self.customer)
        response = self.client.get(reverse("accounts:orders"))
        self.assertContains(response, order.number)

    def test_history_includes_guest_orders_on_the_same_email(self):
        Order.objects.create(
            email="SAM@example.com", first_name="Sam", last_name="Rivera",
            phone="555-0100", address_line1="12 Coral Way", city="Wilmington",
            state="NC", postal_code="28401",
        )
        self.assertEqual(self.customer.orders().count(), 1)

    def test_history_excludes_other_customers_orders(self):
        Order.objects.create(
            email="nope@example.com", first_name="Other", last_name="Person",
            phone="555-0101", address_line1="9 Reef Rd", city="Austin",
            state="TX", postal_code="78701",
        )
        self.assertEqual(self.customer.orders().count(), 0)


class WholesaleTests(SignedInTestCase):
    def test_applying_marks_the_tier_pending(self):
        self.client.post(
            reverse("accounts:wholesale"),
            {"wholesale_company": "Blue Reef LFS", "wholesale_tax_id": "NC-4471"},
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.tier, Customer.Tier.WHOLESALE)
        self.assertIsNone(self.customer.wholesale_approved_at)
        self.assertFalse(self.customer.is_wholesale)

    def test_staff_approval_activates_wholesale(self):
        from django.utils import timezone

        self.customer.tier = Customer.Tier.WHOLESALE
        self.customer.wholesale_approved_at = timezone.now()
        self.customer.save()
        self.assertTrue(self.customer.is_wholesale)
