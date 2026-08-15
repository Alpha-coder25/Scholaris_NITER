from django.contrib import admin

from .models import Course, CourseOffering, Department, Enrollment, Semester


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "short_code")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "department", "credit_hours")
    list_filter = ("department",)


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("course", "semester", "teacher", "section")
    list_filter = ("semester", "teacher")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course_offering", "registered_at")
