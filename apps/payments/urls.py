from django.urls import path

from apps.payments import views

app_name = "payments"

urlpatterns = [
    path("orders/<str:number>/pay/", views.pay, name="pay"),
    path("payments/webhook/", views.webhook, name="webhook"),
]
