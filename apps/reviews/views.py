from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.catalog.models import Product
from apps.reviews.forms import ReviewForm
from apps.reviews.models import Review, has_purchased


def submit_review(request, slug):
    product = get_object_or_404(Product.objects.published(), slug=slug)
    customer = None
    if request.user.is_authenticated:
        from apps.accounts.views import get_customer

        customer = get_customer(request)

    if request.method == "POST":
        form = ReviewForm(request.POST, request.FILES, customer=customer)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.customer = customer
            if customer:
                review.author_email = customer.email
            review.is_verified_purchase = has_purchased(
                product, customer=customer, email=review.author_email
            )
            review.save()
            messages.success(
                request,
                "Thanks — your review is with our team and will appear once it is approved.",
            )
            return redirect(product.get_absolute_url())
    else:
        form = ReviewForm(customer=customer)

    return render(
        request, "reviews/submit.html", {"product": product, "form": form}
    )


def product_reviews(request, slug):
    """All reviews for one product, paginated off the product page."""
    from django.core.paginator import Paginator

    product = get_object_or_404(Product.objects.published(), slug=slug)
    reviews = Review.objects.for_product(product)
    page = Paginator(reviews, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "reviews/list.html",
        {"product": product, "page_obj": page, "reviews": page.object_list},
    )
