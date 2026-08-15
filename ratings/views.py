from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from academics.models import CourseOffering
from accounts.decorators import role_required

from .models import Rating


@role_required("student")
def rate_offering(request, offering_id):
    """Student rates the course/teacher — private, aggregated, never public."""
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester", "teacher"),
        pk=offering_id,
    )
    if not offering.enrollments.filter(student=request.user).exists():
        messages.error(request, "Only enrolled students can rate this course.")
        return redirect("dashboard:home")

    existing = Rating.objects.filter(
        course_offering=offering, student=request.user
    ).first()

    if request.method == "POST":
        try:
            stars = int(request.POST.get("stars"))
        except (TypeError, ValueError):
            stars = 0
        if not 1 <= stars <= 5:
            messages.error(request, "Pick a rating from 1 to 5 stars.")
        else:
            comment = request.POST.get("comment", "").strip()
            rating = existing
            if rating is None:
                rating = Rating(
                    course_offering=offering, student=request.user, stars=stars
                )
            rating.stars = stars
            rating.comment = comment
            rating.save()
            messages.success(
                request,
                "Thanks! Your rating is kept private and only shown aggregated "
                "to the teacher and admin.",
            )
            return redirect("dashboard:student_course", offering_id=offering.pk)

    return render(
        request,
        "student/rate_offering.html",
        {"offering": offering, "existing": existing},
    )


def aggregate_for_offering(offering):
    """Anonymised aggregate; None until the minimum response threshold is met."""
    ratings = list(offering.ratings.all())
    count = len(ratings)
    if count < settings.RATING_MIN_RESPONSES:
        return None
    return {
        "count": count,
        "avg": round(sum(r.stars for r in ratings) / count, 1),
        "distribution": {
            star: sum(1 for r in ratings if r.stars == star) for star in range(1, 6)
        },
        "comments": [r.comment for r in ratings if r.comment],
    }
