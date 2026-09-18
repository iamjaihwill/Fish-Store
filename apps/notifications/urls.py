from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("cart/recover/<str:token>/", views.recover_cart, name="recover_cart"),
]
