from django.contrib import messages
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from academics.models import CourseOffering

from .models import AIUsageLog, StudentTopicPerformance
from .services import (
    analyze_student_progress,
    evaluate_cq_answer,
    generate_ai_progress_insights,
)


@role_required("teacher")
def course_analytics(request, offering_id):
    """AI-powered analytics for a course offering.
    Shows per-topic and per-student performance analysis.
    """
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester", "teacher"),
        pk=offering_id,
        teacher=request.user,
    )

    progress = analyze_student_progress(offering)
    insights = generate_ai_progress_insights(progress)

    # Get or update cached student topic performances
    from accounts.models import User
    from exams.models import ExamAnswer

    students = User.objects.filter(
        role="student",
        enrollments__course_offering=offering,
    ).distinct()

    student_profiles = []
    for student in students:
        gaps = next(
            (g for g in progress["student_gaps"] if g["student_id"] == student.id),
            None,
        )
        if gaps:
            student_profiles.append({
                "student": student,
                "accuracy_pct": gaps["overall_accuracy_pct"],
                "weak_topics": gaps["weak_topics"],
                "strong_topics": gaps["strong_topics"],
            })

    return render(
        request,
        "ai/course_analytics.html",
        {
            "offering": offering,
            "progress": progress,
            "insights": insights,
            "student_profiles": student_profiles,
        },
    )


@role_required("teacher")
def ai_insights(request, offering_id):
    """AJAX endpoint for refreshing AI insights on a course."""
    offering = get_object_or_404(
        CourseOffering, pk=offering_id, teacher=request.user
    )
    progress = analyze_student_progress(offering)
    insights = generate_ai_progress_insights(progress)

    return render(
        request,
        "ai/_insights_fragment.html",
        {"insights": insights, "progress": progress},
    )


@role_required("admin")
def ai_usage_dashboard(request):
    """Admin view showing AI usage statistics across the platform."""
    logs = AIUsageLog.objects.all()[:100]

    # Aggregate stats
    from django.db.models import Avg, Count, Sum
    stats = (
        AIUsageLog.objects.aggregate(
            total_calls=Count("id"),
            success_count=Count("id", filter=models.Q(status="success")),
            error_count=Count("id", filter=models.Q(status="error")),
            fallback_count=Count("id", filter=models.Q(status="fallback")),
            total_input_tokens=Sum("input_tokens"),
            total_output_tokens=Sum("output_tokens"),
            avg_latency=Avg("latency_ms"),
        )
    )

    # Per-feature breakdown
    feature_stats = []
    for feature, label in AIUsageLog.FEATURE_CHOICES:
        fs = AIUsageLog.objects.filter(feature=feature).aggregate(
            calls=Count("id"),
            success=Count("id", filter=Q(status="success")),
            avg_latency=Avg("latency_ms"),
            tokens=Sum("input_tokens"),
        )
        feature_stats.append({"feature": feature, "label": label, **fs})

    return render(
        request,
        "ai/usage_dashboard.html",
        {
            "logs": logs,
            "stats": stats,
            "feature_stats": feature_stats,
        },
    )
