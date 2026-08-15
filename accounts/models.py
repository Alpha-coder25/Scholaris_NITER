from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

ROLE_CHOICES = [
    ("admin", "Admin"),
    ("teacher", "Teacher"),
    ("student", "Student"),
]


class UserManager(DjangoUserManager):
    """Superusers are institution admins — default their role accordingly."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """NITER user — role drives everything (permissions, nav, dashboards)."""

    objects = UserManager()

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
    batch = models.CharField("Batch (admission year)", max_length=10, blank=True)
    section = models.CharField("Section", max_length=10, blank=True)

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def display_id(self):
        return self.student_id_no or self.employee_id or "—"
