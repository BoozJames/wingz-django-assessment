from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Ride, RideEvent, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role", "phone_number")}),)
    list_display = ("username", "email", "role", "is_staff")
    list_filter = UserAdmin.list_filter + ("role",)


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "rider", "driver", "pickup_time")
    list_filter = ("status",)
    search_fields = ("rider__email", "driver__email")


@admin.register(RideEvent)
class RideEventAdmin(admin.ModelAdmin):
    list_display = ("id", "ride", "description", "created_at")
    list_filter = ("description",)
