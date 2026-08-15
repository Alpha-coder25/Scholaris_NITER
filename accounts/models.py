from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_CHOICES = [
    ("admin", "Admin"),
    ("teacher", "Teacher"),
    ("student", "Student"),
]


class User(AbstractUser):
    """NITER user — role drives everything (permissions, nav, dashboards)."""

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="student")
    department = models.ForeignKey(
        "academics.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
    student_id_no = models.CharField("Student ID", max_length=20, blank=True)
    employee_id = models.CharField("Employee ID", max_length=20, blank=True)

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def display_id(self):
        return self.student_id_no or self.employee_id or "—"
