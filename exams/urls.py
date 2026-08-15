from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    # Teacher — question bank
    path(
        "teacher/course/<int:offering_id>/questions/",
        views.question_review,
        name="question_review",
    ),
    path("teacher/questions/<int:question_id>/edit/", views.question_edit, name="question_edit"),
    path(
        "teacher/course/<int:offering_id>/questions/add/",
        views.add_manual_question,
        name="add_manual_question",
    ),
    # Teacher — exam build & grading
    path(
        "teacher/course/<int:offering_id>/exams/new/",
        views.exam_builder,
        name="exam_builder",
    ),
    path("teacher/exams/<int:exam_id>/", views.exam_detail, name="exam_detail"),
    path(
        "teacher/course/<int:offering_id>/grading/",
        views.grading_queue,
        name="grading_queue",
    ),
    path("teacher/exams/<int:exam_id>/gradebook/", views.gradebook, name="gradebook"),
    # Student — take the exam
    path("student/exams/<int:exam_id>/take/", views.exam_take, name="exam_take"),
    path("student/exam-attempts/<int:attempt_id>/", views.attempt_view, name="attempt_view"),
    path(
        "student/exam-attempts/<int:attempt_id>/answer/",
        views.attempt_answer,
        name="attempt_answer",
    ),
    path(
        "student/exam-attempts/<int:attempt_id>/heartbeat/",
        views.attempt_heartbeat,
        name="attempt_heartbeat",
    ),
    path(
        "student/exam-attempts/<int:attempt_id>/result/",
        views.attempt_result,
        name="attempt_result",
    ),
]
