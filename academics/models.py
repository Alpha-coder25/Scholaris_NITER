from django.conf import settings
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    short_code = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Semester(models.Model):
    name = models.CharField(max_length=50, unique=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name


class Course(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="courses"
    )
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    credit_hours = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ["code"]
        unique_together = ("department", "code")

    def __str__(self):
        return f"{self.code} — {self.title}"


class CourseOffering(models.Model):
    """A course taught in a specific semester by a specific teacher (section).

    This is the object an Admin creates when assigning a teacher to a course.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="offerings"
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name="offerings"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="taught_offerings",
        limit_choices_to={"role": "teacher"},
    )
    section = models.CharField(max_length=10, default="A", blank=True)

    class Meta:
        ordering = ["-semester", "course__code", "section"]
        unique_together = ("course", "semester", "section")

    def __str__(self):
        return f"{self.course.code} {self.course.title} (Sec {self.section}) — {self.semester.name}"

    @property
    def display_name(self):
        return f"{self.course.code} · {self.course.title} — Section {self.section}"

    @property
    def enrollment_count(self):
        return self.enrollments.count()


class Enrollment(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "student"},
    )
    course_offering = models.ForeignKey(
        CourseOffering, on_delete=models.CASCADE, related_name="enrollments"
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "course_offering")

    def __str__(self):
        return f"{self.student} → {self.course_offering}"
