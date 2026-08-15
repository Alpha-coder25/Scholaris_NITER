from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import role_required
from academics.models import CourseOffering, Department
from exams.models import ExamAnswer, ExamAttempt
from ratings.views import aggregate_for_offering


def home(request):
    """Landing page for visitors; role dashboard for logged-in users."""
    if not request.user.is_authenticated:
        return render(request, "dashboard/landing.html")
    if request.user.role == "admin":
        return redirect("dashboard:admin_dashboard")
    if request.user.role == "teacher":
        return redirect("dashboard:teacher_dashboard")
    return redirect("dashboard:student_dashboard")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@role_required("admin")
def admin_dashboard(request):
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .prefetch_related("enrollments", "ratings")
        .order_by("-semester__start_date", "course__code")
    )
    total_students = (
        request.user.__class__.objects.filter(role="student", is_active=True).count()
    )
    total_teachers = (
        request.user.__class__.objects.filter(role="teacher", is_active=True).count()
    )
    context = {
        "offerings": offerings,
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_courses": offerings.count(),
        "departments": Department.objects.all(),
    }
    return render(request, "admin/dashboard.html", context)


@role_required("admin")
def admin_analytics(request):
    # Course load per teacher
    teacher_rows = []
    for teacher in request.user.__class__.objects.filter(role="teacher").order_by(
        "first_name"
    ):
        t_offerings = teacher.taught_offerings.all()
        rating_counts = sum(o.ratings.count() for o in t_offerings)
        teacher_rows.append(
            {
                "teacher": teacher,
                "offering_count": t_offerings.count(),
                "student_total": sum(o.enrollment_count for o in t_offerings),
                "rating_total": rating_counts,
                "avg_rating": _weighted_avg_rating(t_offerings),
            }
        )

    # Rating trends by offering (aggregated/anonymised, threshold-gated)
    offering_ratings = []
    for offering in (
        CourseOffering.objects.select_related("course", "teacher")
        .prefetch_related("ratings")
        .order_by("course__code")
    ):
        agg = aggregate_for_offering(offering)
        offering_ratings.append(
            {
                "offering": offering,
                "agg": agg,
                "needed": max(0, settings.RATING_MIN_RESPONSES - offering.ratings.count()),
            }
        )

    context = {
        "teacher_rows": teacher_rows,
        "offering_ratings": offering_ratings,
        "departments": Department.objects.all(),
    }
    return render(request, "admin/analytics.html", context)


def _weighted_avg_rating(offerings):
    ratings = [r for o in offerings for r in o.ratings.all()]
    if not ratings:
        return None
    return round(sum(r.stars for r in ratings) / len(ratings), 1)


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------
@role_required("teacher")
def teacher_dashboard(request):
    offerings = (
        request.user.taught_offerings.select_related("course", "semester")
        .prefetch_related("enrollments", "exams")
        .order_by("-semester__start_date", "course__code")
    )
    for o in offerings:
        o.pending_grading = ExamAnswer.objects.filter(
            attempt__exam__course_offering=o,
            exam_question__question__type="cq",
            manual_score__isnull=True,
            submitted_at__isnull=False,
        ).count()
    context = {"offerings": offerings}
    return render(request, "teacher/dashboard.html", context)


@role_required("teacher")
def teacher_course_detail(request, offering_id):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester", "teacher"),
        pk=offering_id,
        teacher=request.user,
    )
    exams = offering.exams.all()
    my_rating = aggregate_for_offering(offering)
    context = {
        "offering": offering,
        "materials": offering.materials.all(),
        "exams": exams,
        "students": offering.enrollments.select_related("student").order_by(
            "student__first_name", "student__username"
        ),
        "my_rating": my_rating,
        "rating_needed": max(0, settings.RATING_MIN_RESPONSES - offering.ratings.count()),
        "question_counts": {
            "draft": offering.questions.filter(status="draft").count(),
            "approved": offering.questions.filter(status="approved").count(),
        },
        "pending_grading": ExamAnswer.objects.filter(
            attempt__exam__course_offering=offering,
            exam_question__question__type="cq",
            manual_score__isnull=True,
            submitted_at__isnull=False,
        ).count(),
    }
    return render(request, "teacher/course_detail.html", context)


@role_required("teacher")
def teacher_ratings(request):
    offerings = request.user.taught_offerings.prefetch_related("ratings").order_by(
        "-semester__start_date", "course__code"
    )
    rows = []
    for o in offerings:
        agg = aggregate_for_offering(o)
        rows.append({"offering": o, "agg": agg, "needed": max(0, settings.RATING_MIN_RESPONSES - o.ratings.count())})
    return render(request, "teacher/ratings.html", {"rows": rows})


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
@role_required("student")
def student_dashboard(request):
    enrollments = (
        request.user.enrollments.select_related(
            "course_offering", "course_offering__course", "course_offering__teacher",
            "course_offering__semester",
        )
        .order_by("-course_offering__semester__start_date", "course_offering__course__code")
    )

    for e in enrollments:
        o = e.course_offering
        o.upcoming_exams = [
            x for x in o.exams.all() if x.is_scheduled
        ]
        o.attempts = (
            ExamAttempt.objects.filter(exam__course_offering=o, student=request.user)
            .select_related("exam")
            .order_by("-started_at")
        )
        o.rated = o.ratings.filter(student=request.user).exists()

    context = {"enrollments": enrollments}
    return render(request, "student/dashboard.html", context)


@role_required("student")
def student_course_detail(request, offering_id):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester", "teacher"),
        pk=offering_id,
    )
    if not offering.enrollments.filter(student=request.user).exists():
        messages.error(request, "You're not enrolled in this course.")
        return redirect("dashboard:home")

    exams = []
    for exam in offering.exams.all().prefetch_related("exam_questions"):
        attempt = ExamAttempt.objects.filter(exam=exam, student=request.user).first()
        exams.append({"exam": exam, "attempt": attempt})

    my_rating = offering.ratings.filter(student=request.user).first()
    context = {
        "offering": offering,
        "materials": offering.materials.all(),
        "exams": exams,
        "my_rating": my_rating,
    }
    return render(request, "student/course_detail.html", context)
