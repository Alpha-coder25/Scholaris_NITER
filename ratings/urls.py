from django.urls import path

from . import views

app_name = "ratings"

urlpatterns = [
    path("student/course/<int:offering_id>/rate/", views.rate_offering, name="rate_offering"),
]
