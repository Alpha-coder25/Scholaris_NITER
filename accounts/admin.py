from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class ScholarisUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Scholaris", {"fields": ("role", "department", "student_id_no", "employee_id")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Scholaris", {"fields": ("role", "department", "student_id_no", "employee_id")}),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "department")
