from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/analytics/", views.admin_analytics, name="admin_analytics"),
    path("teacher/dashboard/", views.teacher_dashboard, name="teacher_dashboard"),
    path(
        "teacher/course/<int:offering_id>/",
        views.teacher_course_detail,
        name="teacher_course",
    ),
    path("teacher/ratings/", views.teacher_ratings, name="teacher_ratings"),
    path("student/dashboard/", views.student_dashboard, name="student_dashboard"),
    path(
        "student/course/<int:offering_id>/",
        views.student_course_detail,
        name="student_course",
    ),
]
