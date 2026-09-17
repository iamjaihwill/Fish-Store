from django.urls import path

from apps.cms import views

app_name = "cms"

urlpatterns = [
    path("", views.home, name="home"),
    path("faq/", views.faq, name="faq"),
    path("contact/", views.contact, name="contact"),
    path("live-sales/", views.live_sales, name="live_sales"),
    path("newsletter/", views.newsletter_signup, name="newsletter"),
    path("pages/<slug:slug>/", views.page_detail, name="page"),
]
