from django.conf import settings
from django.db import models


class Rating(models.Model):
    """Private faculty/course rating. student_id is stored for integrity
    (one rating per student per offering) but never surfaced in any
    aggregate view — only anonymised aggregates past a response threshold."""

    course_offering = models.ForeignKey(
        "academics.CourseOffering", on_delete=models.CASCADE, related_name="ratings"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings"
    )
    stars = models.PositiveSmallIntegerField()  # 1–5
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("course_offering", "student")

    def __str__(self):
        return f"{self.stars}★ — {self.course_offering}"
