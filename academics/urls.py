from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    path("admin/syllabus/", views.syllabus, name="syllabus"),
    path("admin/course-offerings/", views.course_offering_list, name="course_offerings"),
    path("admin/enroll-students/", views.admin_enroll_students, name="admin_enroll_students"),
    path("teacher/course/<int:offering_id>/students/", views.teacher_manage_students, name="teacher_manage_students"),
    path("enroll/", views.enroll, name="enroll"),
]
