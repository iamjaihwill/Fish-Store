from django.urls import path

from apps.reviews import views

app_name = "reviews"

urlpatterns = [
    path("product/<slug:slug>/reviews/", views.product_reviews, name="list"),
    path("product/<slug:slug>/reviews/new/", views.submit_review, name="submit"),
]
