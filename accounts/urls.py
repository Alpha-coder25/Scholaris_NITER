from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    # Admin: manage teachers & students
    path("admin/users/", views.admin_user_list, name="admin_users"),
    path("admin/users/add/", views.admin_user_add, name="admin_user_add"),
    path("admin/users/<int:user_id>/edit/", views.admin_user_edit, name="admin_user_edit"),
    path("admin/students/", views.admin_students_by_cohort, name="admin_students"),
]
