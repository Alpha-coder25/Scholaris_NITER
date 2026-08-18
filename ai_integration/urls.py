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
        "admin/ai-usage/",
        views.ai_usage_dashboard,
        name="ai_usage_dashboard",
    ),
]
