from django.urls import path

from apps.shop import views

app_name = "shop"

urlpatterns = [
    path("cart/", views.cart_detail, name="cart"),
    path("cart/add/<slug:slug>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<slug:slug>/", views.update_cart, name="update_cart"),
    path("cart/remove/<slug:slug>/", views.remove_from_cart, name="remove_from_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/discount/", views.apply_discount, name="apply_discount"),
    path("checkout/points/", views.apply_points, name="apply_points"),
    path("checkout/gift-card/", views.apply_gift_card, name="apply_gift_card"),
    path("orders/lookup/", views.order_lookup, name="order_lookup"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("orders/<str:number>/confirmation/", views.order_confirmation, name="order_confirmation"),
    path("orders/<str:number>/live-arrival-claim/", views.doa_claim, name="doa_claim"),
]
