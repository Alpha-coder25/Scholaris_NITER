from django.conf import settings


def site_globals(request):
    """Expose site-wide values and role helpers to every template."""
    role = None
    if request.user.is_authenticated:
        role = request.user.role

    # Distinct accent colour per role for quick visual orientation in demos.
    role_accent = {
        "admin": "violet",
        "teacher": "emerald",
        "student": "sky",
    }.get(role, "slate")

    return {
        "SITE_NAME": "Scholaris",
        "user_role": role,
        "role_accent": role_accent,
        "RATING_MIN_RESPONSES": settings.RATING_MIN_RESPONSES,
    }
