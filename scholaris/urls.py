from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django's built-in admin lives at /django-admin/ so that the app's own
    # /admin/* pages (dashboard, course assignment, analytics) are not shadowed.
    path("django-admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("", include("academics.urls")),
    path("", include("materials.urls")),
    path("", include("exams.urls")),
    path("", include("ratings.urls")),
    path("", include("ai_integration.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
