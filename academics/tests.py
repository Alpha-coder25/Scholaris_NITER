"""Academics tests — syllabus, course offerings & enrollment."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Course, CourseOffering, Department, Enrollment, Semester

User = get_user_model()


class SyllabusTests(TestCase):
    """Admin syllabus management: add / update / delete per department+semester."""

    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.admin = User.objects.create_superuser(username="admin", password="admin12345")
        self.teacher = User.objects.create_user(username="t", password="pw12345678", role="teacher")
        self.c = Client()

    def _url(self, with_params=True):
        url = reverse("academics:syllabus")
        if with_params:
            url += f"?department={self.dept.pk}&semester={self.sem.pk}"
        return url

    def test_admin_adds_course_to_syllabus(self):
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(self._url(), {
            "action": "add", "department": self.dept.pk, "semester": self.sem.pk,
            "code": "CSE-2105", "title": "Algorithms", "credit_hours": "3",
        })
        self.assertEqual(r.status_code, 302)
        course = Course.objects.get(code="CSE-2105")
        self.assertEqual(course.department, self.dept)
        self.assertEqual(course.semester, self.sem)
        self.assertEqual(course.credit_hours, 3)

    def test_duplicate_course_in_semester_rejected(self):
        Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2101", title="DS")
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(self._url(), {
            "action": "add", "department": self.dept.pk, "semester": self.sem.pk,
            "code": "CSE-2101", "title": "Dup", "credit_hours": "3",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Course.objects.filter(code="CSE-2101").count(), 1)

    def test_same_code_ok_in_different_semester(self):
        other = Semester.objects.create(name="Fall 2026")
        Course.objects.create(department=self.dept, semester=other, code="CSE-2101", title="Old")
        self.c.login(username="admin", password="admin12345")
        self.c.post(self._url(), {
            "action": "add", "department": self.dept.pk, "semester": self.sem.pk,
            "code": "CSE-2101", "title": "New", "credit_hours": "3",
        })
        self.assertEqual(Course.objects.filter(code="CSE-2101", semester=self.sem).count(), 1)

    def test_admin_updates_course(self):
        course = Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2101", title="DS", credit_hours=3)
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(self._url(), {
            "action": "update", "course_id": course.pk,
            "department": self.dept.pk, "semester": self.sem.pk,
            "code": "CSE-2101", "title": "Data Structures II", "credit_hours": "4",
        })
        self.assertEqual(r.status_code, 302)
        course.refresh_from_db()
        self.assertEqual(course.title, "Data Structures II")
        self.assertEqual(course.credit_hours, 4)

    def test_admin_deletes_unassigned_course(self):
        course = Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2199", title="Temp")
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(self._url(), {
            "action": "delete", "course_id": course.pk,
            "department": self.dept.pk, "semester": self.sem.pk,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Course.objects.filter(pk=course.pk).exists())

    def test_delete_blocked_when_assigned_to_offering(self):
        course = Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2101", title="DS")
        CourseOffering.objects.create(course=course, semester=self.sem, teacher=self.teacher)
        self.c.login(username="admin", password="admin12345")
        r = self.c.post(self._url(), {
            "action": "delete", "course_id": course.pk,
            "department": self.dept.pk, "semester": self.sem.pk,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())  # not deleted

    def test_syllabus_page_lists_courses_for_selection(self):
        Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2101", title="DS")
        Course.objects.create(department=self.dept, semester=self.sem, code="CSE-2103", title="OOP")
        self.c.login(username="admin", password="admin12345")
        r = self.c.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CSE-2101")
        self.assertContains(r, "CSE-2103")

    def test_syllabus_requires_admin(self):
        self.c.login(username="t", password="pw12345678")
        r = self.c.get(self._url())
        self.assertEqual(r.status_code, 302)  # teachers bounced


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
