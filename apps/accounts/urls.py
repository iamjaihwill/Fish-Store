from django.contrib.auth import views as auth_views
from django.urls import path

from apps.accounts import views
from apps.accounts.forms import EmailAuthenticationForm

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="cms:home"),
        name="logout",
    ),
    path("register/", views.register, name="register"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url="/account/",
        ),
        name="password_change",
    ),
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.order_history, name="orders"),
    path("profile/", views.profile, name="profile"),
    path("addresses/", views.address_list, name="addresses"),
    path("addresses/new/", views.address_edit, name="address_new"),
    path("addresses/<int:pk>/", views.address_edit, name="address_edit"),
    path("addresses/<int:pk>/delete/", views.address_delete, name="address_delete"),
    path("wishlist/", views.wishlist, name="wishlist"),
    path("wishlist/toggle/<slug:slug>/", views.wishlist_toggle, name="wishlist_toggle"),
    path("wishlist/add-all/", views.wishlist_add_all_to_cart, name="wishlist_add_all"),
    path("wholesale/", views.wholesale, name="wholesale"),
]
