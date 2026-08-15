from django.urls import path

from . import views

app_name = "materials"

urlpatterns = [
    path("teacher/course/<int:offering_id>/materials/", views.upload, name="upload"),
    path(
        "teacher/course/<int:offering_id>/materials/<int:material_id>/generate/",
        views.generate_questions_from_material,
        name="generate_questions",
    ),
]
