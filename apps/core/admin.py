from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

User = get_user_model()

admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Same as Django's, but searchable so customer autocomplete works."""

    search_fields = ("username", "email", "first_name", "last_name")
