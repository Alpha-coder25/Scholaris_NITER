from django.urls import path

from . import views

app_name = "ai_integration"

urlpatterns = [
    path(
        "teacher/course/<int:offering_id>/analytics/",
        views.course_analytics,
        name="course_analytics",
    ),
    path(
        "teacher/course/<int:offering_id>/ai-insights/",
        views.ai_insights,
        name="ai_insights",
    ),
    path(
        "teacher/course/<int:offering_id>/students/",
        views.student_overview,
        name="student_overview",
    ),
    path(
        "teacher/course/<int:offering_id>/export/performance/",
        views.export_performance_csv,
        name="export_performance_csv",
    ),
    path(
        "teacher/course/<int:offering_id>/export/topics/",
        views.export_topic_csv,
        name="export_topic_csv",
    ),
    path(
        "admin/ai-usage/",
        views.ai_usage_dashboard,
        name="ai_usage_dashboard",
    ),
    path(
        "student/course/<int:offering_id>/recommendations/",
        views.student_recommendations,
        name="student_recommendations",
    ),
]
