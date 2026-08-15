from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    path("admin/syllabus/", views.syllabus, name="syllabus"),
    path("admin/course-offerings/", views.course_offering_list, name="course_offerings"),
    path("enroll/", views.enroll, name="enroll"),
]
