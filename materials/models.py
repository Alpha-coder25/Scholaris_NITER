from django.conf import settings
from django.db import models


class Material(models.Model):
    """A lecture material for a course offering. Re-uploads bump `version` —
    history is never destroyed, access is scoped to the offering."""

    course_offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="materials",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="materials"
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="materials/%Y/%m/", blank=True)
    # Extracted text kept in the DB — survives serverless deploys where the
    # file itself lives on ephemeral disk (Vercel). AI generation reads this.
    content_text = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.title} (v{self.version})"

    @property
    def filename(self):
        return self.file.name.split("/")[-1]
