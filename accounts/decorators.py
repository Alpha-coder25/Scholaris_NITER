from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


def role_required(*roles):
    """Gate a view to authenticated users with one of the given roles."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(settings.LOGIN_URL)
            if request.user.role not in roles:
                messages.error(request, "You don't have access to that page.")
                return redirect("dashboard:home")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def enrolled_students(course_offering):
    """Students enrolled in an offering (used for scoping)."""
    return course_offering.enrollments.select_related("student").values_list(
        "student", flat=True
    )
