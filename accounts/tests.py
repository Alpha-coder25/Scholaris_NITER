"""Authentication & authorization tests."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import Department

User = get_user_model()


class AuthTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.admin = User.objects.create_user(
            username="admin", password="admin123", role="admin", is_staff=True)
        self.teacher = User.objects.create_user(username="t.hasan", password="demo123", role="teacher")
        self.student = User.objects.create_user(username="s.rahman", password="demo123", role="student")
        self.c = Client()

    # ------------------------------------------------------------- login
    def test_login_success(self):
        self.assertTrue(self.c.login(username="t.hasan", password="demo123"))

    def test_login_wrong_password(self):
        self.assertFalse(self.c.login(username="t.hasan", password="wrongpass"))

    def test_unauthenticated_root_serves_landing(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "How it works")

    def test_authenticated_root_redirects_to_dashboard(self):
        self.c.login(username="s.rahman", password="demo123")
        r = self.c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/student/dashboard/", r.url)

    def test_logout_returns_to_landing(self):
        self.c.login(username="s.rahman", password="demo123")
        r = self.c.post(reverse("accounts:logout"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/")

    # ------------------------------------------------------------- RBAC
    def test_student_blocked_from_teacher_pages(self):
        self.c.login(username="s.rahman", password="demo123")
        r = self.c.get("/teacher/dashboard/")
        self.assertEqual(r.status_code, 302)

    def test_teacher_blocked_from_admin_pages(self):
        self.c.login(username="t.hasan", password="demo123")
        r = self.c.get("/admin/dashboard/")
        self.assertEqual(r.status_code, 302)

    def test_student_blocked_from_admin_pages(self):
        self.c.login(username="s.rahman", password="demo123")
        r = self.c.get("/admin/dashboard/")
        self.assertEqual(r.status_code, 302)

    def test_unauthenticated_protected_route_redirects(self):
        r = self.c.get("/teacher/dashboard/")
        self.assertEqual(r.status_code, 302)

    def test_csrf_post_rejected_without_token(self):
        strict = Client(enforce_csrf_checks=True)
        r = strict.post(reverse("accounts:login"), {"username": "t.hasan", "password": "demo123"})
        self.assertEqual(r.status_code, 403)

    def test_login_rotates_session_key(self):
        """Session fixation: logging in must mint a fresh session id."""
        self.c.get("/")
        old_key = self.c.session.session_key
        self.c.login(username="t.hasan", password="demo123")
        self.assertNotEqual(self.c.session.session_key, old_key)

    def test_signup_cannot_set_role_admin(self):
        """Mass assignment: posting role=admin must not elevate a signup."""
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="evil", extra={"role": "admin"}))
        self.assertEqual(r.status_code, 200)  # rejected, stays on form
        self.assertFalse(User.objects.filter(username="evil").exists())

    def test_signup_rejects_bogus_department(self):
        """A nonexistent department id must not crash signup or attach junk."""
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="deptless", extra={"department": "99999"}))
        self.assertEqual(r.status_code, 200)  # stays on form with error
        self.assertFalse(User.objects.filter(username="deptless").exists())

    def test_signup_huge_email_rejected(self):
        r = self.c.post(reverse("accounts:signup"), {
            "username": "bigmail", "password": "secret99", "email": "a" * 500 + "@x.com",
            "role": "student", "student_id_no": "CS 2405999", "batch": "2024", "section": "A",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "at most 254")
        self.assertFalse(User.objects.filter(username="bigmail").exists())

    # ------------------------------------------------------------- signup
    def _student_payload(self, username="newbie", extra=None):
        payload = {
            "username": username, "first_name": "N", "last_name": "B",
            "email": "n@b.com", "password": "secret99", "department": self.dept.pk,
            "role": "student", "student_id_no": "CS 2405009", "batch": "2024", "section": "A",
        }
        payload.update(extra or {})
        return payload

    def test_signup_creates_student_and_logs_in(self):
        r = self.c.post(reverse("accounts:signup"), self._student_payload())
        user = User.objects.get(username="newbie")
        self.assertEqual(user.role, "student")
        self.assertEqual(user.department, self.dept)
        self.assertEqual(user.student_id_no, "CS 2405009")
        self.assertEqual(user.batch, "2024")
        self.assertEqual(user.section, "A")
        self.assertEqual(r.status_code, 302)  # auto-login -> dashboard
        self.assertTrue(self.c.session.get("_auth_user_id"))

    def test_signup_teacher_creates_teacher_account(self):
        r = self.c.post(reverse("accounts:signup"), {
            "username": "newteacher", "first_name": "T", "last_name": "E",
            "email": "t@b.com", "password": "secret99", "department": self.dept.pk,
            "role": "teacher", "employee_id": "T-999",
        })
        user = User.objects.get(username="newteacher")
        self.assertEqual(user.role, "teacher")
        self.assertEqual(user.employee_id, "T-999")
        self.assertEqual(r.status_code, 302)

    def test_signup_student_id_prefix_must_match_department(self):
        """TE-prefixed ID with a CSE department must be rejected."""
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="wrongprefix", extra={"student_id_no": "TE 2405009"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "does not match")
        self.assertFalse(User.objects.filter(username="wrongprefix").exists())

    def test_signup_invalid_student_id_format_rejected(self):
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="badid", extra={"student_id_no": "not-an-id"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "department code + year + serial")
        self.assertFalse(User.objects.filter(username="badid").exists())

    def test_signup_duplicate_student_id_rejected(self):
        self.c.post(reverse("accounts:signup"), self._student_payload(username="first"))
        fresh = Client()  # first signup auto-logs-in; use a fresh session to re-test
        r = fresh.post(reverse("accounts:signup"), self._student_payload(
            username="second", extra={"student_id_no": "CS 2405009"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already registered")
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_signup_batch_derived_from_student_id(self):
        """Leaving batch blank derives it from the ID year (CS 2505999 -> 2025)."""
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="autobatch", extra={"student_id_no": "CS 2505999", "batch": ""}))
        user = User.objects.get(username="autobatch")
        self.assertEqual(user.batch, "2025")
        self.assertEqual(r.status_code, 302)

    def test_signup_empty_username_rejected(self):
        self.c.post(reverse("accounts:signup"), self._student_payload(username="  "))
        self.assertFalse(User.objects.filter(username="").exists())

    def test_signup_duplicate_username_rejected(self):
        self.c.post(reverse("accounts:signup"), self._student_payload(username="dup1"))
        fresh = Client()  # first signup auto-logs-in; use a fresh session to re-test
        r = fresh.post(reverse("accounts:signup"), self._student_payload(username="dup1"))
        self.assertEqual(r.status_code, 200)  # stays on form
        self.assertContains(r, "already taken")
        self.assertEqual(User.objects.filter(username="dup1").count(), 1)

    def test_signup_short_password_rejected(self):
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="shortpw", extra={"password": "123"}))
        self.assertContains(r, "at least 6")
        self.assertFalse(User.objects.filter(username="shortpw").exists())

    def test_signup_huge_username_rejected(self):
        huge = "x" * 5000
        r = self.c.post(reverse("accounts:signup"), self._student_payload(username=huge))
        self.assertEqual(r.status_code, 200)  # no crash, stays on form
        self.assertContains(r, "at most 150")
        self.assertFalse(User.objects.filter(username=huge).exists())

    def test_signup_teacher_without_employee_id_rejected(self):
        r = self.c.post(reverse("accounts:signup"), {
            "username": "noemp", "password": "secret99", "department": self.dept.pk,
            "role": "teacher", "employee_id": "",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Employee ID is required")
        self.assertFalse(User.objects.filter(username="noemp").exists())

    def test_signup_bogus_role_rejected(self):
        r = self.c.post(reverse("accounts:signup"), self._student_payload(
            username="bogusrole", extra={"role": "admin"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "valid role")
        self.assertFalse(User.objects.filter(username="bogusrole").exists())


class AdminUserManagementTests(TestCase):
    """Admin can add / read / update teachers and students."""

    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.admin = User.objects.create_user(
            username="boss", password="boss12345", role="admin", is_staff=True)
        self.c = Client()
        self.c.login(username="boss", password="boss12345")

    def test_directory_lists_teachers_and_students(self):
        User.objects.create_user(username="st", role="student", department=self.dept)
        User.objects.create_user(username="te", role="teacher", department=self.dept)
        r = self.c.get(reverse("accounts:admin_users"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "st")
        self.assertContains(r, "te")

    def test_role_filter_works(self):
        User.objects.create_user(username="st", role="student", department=self.dept)
        User.objects.create_user(username="te", role="teacher", department=self.dept)
        r = self.c.get(reverse("accounts:admin_users") + "?role=teacher")
        self.assertContains(r, "te")
        self.assertNotContains(r, ">st<")

    def test_admin_adds_student(self):
        r = self.c.post(reverse("accounts:admin_user_add"), {
            "role": "student", "username": "newstu", "password": "secret99",
            "department": self.dept.pk, "student_id_no": "CS 2405111",
            "batch": "2024", "section": "A",
        })
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="newstu")
        self.assertEqual(u.role, "student")
        self.assertEqual(u.batch, "2024")
        self.assertEqual(u.section, "A")

    def test_admin_adds_teacher(self):
        r = self.c.post(reverse("accounts:admin_user_add"), {
            "role": "teacher", "username": "newtea", "password": "secret99",
            "department": self.dept.pk, "employee_id": "T-777",
        })
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="newtea")
        self.assertEqual(u.role, "teacher")
        self.assertEqual(u.employee_id, "T-777")

    def test_admin_edits_student(self):
        u = User.objects.create_user(
            username="editme", role="student", department=self.dept,
            student_id_no="CS 2405001", batch="2024", section="A")
        r = self.c.post(reverse("accounts:admin_user_edit", args=[u.pk]), {
            "first_name": "Edited", "last_name": "Name", "email": "e@x.com",
            "department": self.dept.pk, "student_id_no": "CS 2405222",
            "batch": "2025", "section": "B", "password": "",
        })
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(u.first_name, "Edited")
        self.assertEqual(u.batch, "2025")
        self.assertEqual(u.section, "B")
        self.assertEqual(u.student_id_no, "CS 2405222")

    def test_admin_edits_teacher(self):
        u = User.objects.create_user(
            username="edittea", role="teacher", department=self.dept, employee_id="T-1")
        r = self.c.post(reverse("accounts:admin_user_edit", args=[u.pk]), {
            "first_name": "New", "last_name": "Teacher", "email": "nt@x.com",
            "department": self.dept.pk, "employee_id": "T-2", "password": "",
        })
        u.refresh_from_db()
        self.assertEqual(u.employee_id, "T-2")
        self.assertEqual(u.first_name, "New")

    def test_admin_cannot_edit_admin_account(self):
        other_admin = User.objects.create_user(
            username="otherboss", role="admin", is_staff=True)
        r = self.c.get(reverse("accounts:admin_user_edit", args=[other_admin.pk]))
        self.assertEqual(r.status_code, 404)  # only teachers/students editable

    def test_students_by_cohort_grouped_by_year_dept_section(self):
        User.objects.create_user(
            username="a1", role="student", department=self.dept,
            student_id_no="CS 2405001", batch="2024", section="A")
        User.objects.create_user(
            username="a2", role="student", department=self.dept,
            student_id_no="CS 2405002", batch="2024", section="A")
        User.objects.create_user(
            username="b1", role="student", department=self.dept,
            student_id_no="CS 2505001", batch="2025", section="B")
        r = self.c.get(reverse("accounts:admin_students"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Batch 2024")
        self.assertContains(r, "Batch 2025")
        self.assertContains(r, "Section A")
        self.assertContains(r, "Section B")
        self.assertContains(r, "a1")
        self.assertContains(r, "b1")

    def test_teacher_cannot_access_admin_pages(self):
        User.objects.create_user(username="t", password="pw12345678", role="teacher")
        c = Client()
        c.login(username="t", password="pw12345678")
        r = c.get(reverse("accounts:admin_users"))
        self.assertEqual(r.status_code, 302)  # bounced to home
