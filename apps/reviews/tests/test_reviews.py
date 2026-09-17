from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Customer
from apps.catalog.models import Category, Product, ProductType
from apps.reviews.models import Review, has_purchased, rating_summary
from apps.shop.models import Order, OrderItem

User = get_user_model()


class ReviewBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Corals", product_type=ProductType.CORAL)
        cls.product = Product.objects.create(
            name="Torch", category=cls.category, product_type=ProductType.CORAL,
            price=Decimal("100.00"), status=Product.Status.ACTIVE, stock_quantity=5,
        )

    def make_review(self, **kwargs):
        defaults = {
            "product": self.product,
            "author_name": "Dana",
            "author_email": "dana@example.com",
            "rating": 5,
            "body": "Coloured up in two weeks.",
        }
        return Review.objects.create(**{**defaults, **kwargs})

    def order_for(self, email, status=Order.Status.DELIVERED, product=None):
        order = Order.objects.create(
            email=email, first_name="Dana", last_name="R", phone="555-0100",
            address_line1="1 Reef Rd", city="Austin", state="TX",
            postal_code="78701", status=status,
        )
        OrderItem.objects.create(
            order=order, product=product or self.product, name="Torch",
            unit_price=Decimal("100.00"), quantity=1,
        )
        return order


class ReviewModerationTests(ReviewBase):
    def test_new_reviews_start_pending_and_are_hidden(self):
        review = self.make_review()
        self.assertEqual(review.status, Review.Status.PENDING)
        self.assertEqual(Review.objects.for_product(self.product).count(), 0)

    def test_approving_publishes_and_stamps_the_date(self):
        review = self.make_review()
        review.approve()
        self.assertIsNotNone(review.published_at)
        self.assertEqual(Review.objects.for_product(self.product).count(), 1)

    def test_rejected_reviews_stay_hidden(self):
        self.make_review(status=Review.Status.REJECTED)
        self.assertEqual(Review.objects.for_product(self.product).count(), 0)

    def test_pending_review_is_not_shown_on_the_product_page(self):
        self.make_review(body="Secret pending text")
        response = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(response, "Secret pending text")

    def test_approved_review_appears_on_the_product_page(self):
        self.make_review(body="Visible published text", status=Review.Status.APPROVED)
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "Visible published text")


class RatingSummaryTests(ReviewBase):
    def test_summary_ignores_unapproved_reviews(self):
        self.make_review(rating=5, status=Review.Status.APPROVED)
        self.make_review(rating=1)  # pending
        summary = rating_summary(self.product)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["average"], 5.0)

    def test_average_is_rounded_for_display(self):
        self.make_review(rating=5, status=Review.Status.APPROVED)
        self.make_review(rating=4, status=Review.Status.APPROVED)
        summary = rating_summary(self.product)
        self.assertEqual(summary["average"], 4.5)
        self.assertEqual(summary["rounded"], 4)

    def test_product_without_reviews_has_no_average(self):
        summary = rating_summary(self.product)
        self.assertIsNone(summary["average"])
        self.assertEqual(summary["total"], 0)


class VerifiedPurchaseTests(ReviewBase):
    def test_buyer_email_counts_as_verified(self):
        self.order_for("dana@example.com")
        self.assertTrue(has_purchased(self.product, email="dana@example.com"))

    def test_email_match_is_case_insensitive(self):
        self.order_for("dana@example.com")
        self.assertTrue(has_purchased(self.product, email="DANA@example.com"))

    def test_non_buyer_is_not_verified(self):
        self.assertFalse(has_purchased(self.product, email="stranger@example.com"))

    def test_cancelled_orders_do_not_verify(self):
        self.order_for("dana@example.com", status=Order.Status.CANCELLED)
        self.assertFalse(has_purchased(self.product, email="dana@example.com"))

    def test_buying_a_different_product_does_not_verify(self):
        other = Product.objects.create(
            name="Hammer", category=self.category, product_type=ProductType.CORAL,
            price=Decimal("90.00"), status=Product.Status.ACTIVE, stock_quantity=2,
        )
        self.order_for("dana@example.com", product=other)
        self.assertFalse(has_purchased(self.product, email="dana@example.com"))

    def test_account_orders_verify_the_customer(self):
        user = User.objects.create_user("dana@example.com", "dana@example.com", "pw-192837")
        customer = Customer.objects.create(user=user)
        order = self.order_for("dana@example.com")
        order.customer = customer
        order.save()
        self.assertTrue(has_purchased(self.product, customer=customer))


class ReviewSubmissionTests(ReviewBase):
    def submit(self, **overrides):
        data = {
            "rating": "5",
            "title": "Great torch",
            "body": "Fully extended on day two.",
            "author_name": "Dana",
            "author_email": "dana@example.com",
        }
        data.update(overrides)
        return self.client.post(reverse("reviews:submit", args=[self.product.slug]), data)

    def test_guest_can_submit_a_review(self):
        response = self.submit()
        self.assertRedirects(response, self.product.get_absolute_url())
        review = Review.objects.get()
        self.assertEqual(review.status, Review.Status.PENDING)
        self.assertFalse(review.is_verified_purchase)

    def test_submission_is_marked_verified_when_they_bought_it(self):
        self.order_for("dana@example.com")
        self.submit()
        self.assertTrue(Review.objects.get().is_verified_purchase)

    def test_rating_outside_one_to_five_is_rejected(self):
        response = self.submit(rating="9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.count(), 0)

    def test_body_is_required(self):
        response = self.submit(body="")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.count(), 0)

    def test_guest_must_supply_an_email(self):
        response = self.submit(author_email="")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.count(), 0)

    def test_signed_in_reviewer_is_linked_and_not_asked_for_email(self):
        user = User.objects.create_user(
            "dana@example.com", "dana@example.com", "pw-192837", first_name="Dana"
        )
        customer = Customer.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.get(reverse("reviews:submit", args=[self.product.slug]))
        self.assertNotIn("author_email", response.context["form"].fields)

        self.client.post(
            reverse("reviews:submit", args=[self.product.slug]),
            {"rating": "4", "body": "Solid piece.", "author_name": "Dana", "title": ""},
        )
        review = Review.objects.get()
        self.assertEqual(review.customer, customer)
        self.assertEqual(review.author_email, "dana@example.com")

    def test_review_list_page_shows_only_approved(self):
        self.make_review(body="Approved text", status=Review.Status.APPROVED)
        self.make_review(body="Pending text")
        response = self.client.get(reverse("reviews:list", args=[self.product.slug]))
        self.assertContains(response, "Approved text")
        self.assertNotContains(response, "Pending text")
