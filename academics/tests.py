"""Academics tests — course offerings & enrollment."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Course, CourseOffering, Department, Enrollment, Semester

User = get_user_model()


class AcademicsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.course = Course.objects.create(department=self.dept, code="CSE-2101", title="DS")
        self.admin = User.objects.create_superuser(username="admin", password="admin12345")
        self.teacher = User.objects.create_user(username="t", password="pw12345678", role="teacher")
        self.teacher2 = User.objects.create_user(username="t2", password="pw12345678", role="teacher")
        self.student = User.objects.create_user(username="s", password="pw12345678", role="student")
        self.c = Client()

    def test_admin_creates_offering(self):
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(reverse("academics:course_offerings"), {
            "course": self.course.pk, "semester": self.sem.pk,
            "teacher": self.teacher.pk, "section": "A",
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(CourseOffering.objects.filter(course=self.course, teacher=self.teacher).exists())

    def test_duplicate_offering_rejected(self):
        CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(reverse("academics:course_offerings"), {
            "course": self.course.pk, "semester": self.sem.pk,
            "teacher": self.teacher.pk, "section": "A",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(CourseOffering.objects.count(), 1)

    def test_teacher_cannot_create_offering(self):
        self.c.login(username="t", password="pw12345678")
        r = self.c.post(reverse("academics:course_offerings"), {
            "course": self.course.pk, "semester": self.sem.pk,
            "teacher": self.teacher.pk, "section": "A",
        })
        self.assertEqual(r.status_code, 302)  # bounced to home
        self.assertFalse(CourseOffering.objects.exists())

    def test_student_enrolls(self):
        offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        self.c.login(username="s", password="pw12345678")
        r = self.c.post(reverse("academics:enroll"), {"offering": offering.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Enrollment.objects.filter(student=self.student, course_offering=offering).exists())

    def test_duplicate_enrollment_rejected(self):
        offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        Enrollment.objects.create(student=self.student, course_offering=offering)
        self.c.login(username="s", password="pw12345678")
        self.c.post(reverse("academics:enroll"), {"offering": offering.pk})
        self.assertEqual(Enrollment.objects.filter(student=self.student).count(), 1)

    def test_teacher_cannot_enroll_as_student(self):
        offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        self.c.login(username="t", password="pw12345678")
        r = self.c.get(reverse("academics:enroll"))
        self.assertEqual(r.status_code, 302)  # students only

    def test_offering_requires_teacher_role(self):
        # A student cannot be assigned as the teacher via the admin form
        with self.assertRaises(Exception):
            CourseOffering.objects.create(
                course=self.course, semester=self.sem, teacher=self.student)
