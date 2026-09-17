from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("shop/", views.shop, name="shop"),
    path("search/", views.search, name="search"),
    path("category/<slug:slug>/", views.category_detail, name="category"),
    path("collection/<slug:slug>/", views.collection_detail, name="collection"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
]
