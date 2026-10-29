from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class OEPUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("OEP", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("OEP", {"fields": ("email", "role")}),)
    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")
