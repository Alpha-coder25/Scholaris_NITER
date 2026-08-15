"""Authentication & authorization tests."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import Department

User = get_user_model()


class AuthTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        # Usernames/passwords match settings.DEMO_LOGINS so the one-click demo
        # quick-login feature can be tested directly.
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

    def test_demo_quick_login_get_for_each_role(self):
        for username, expected in [("admin", "/admin/dashboard/"),
                                   ("t.hasan", "/teacher/dashboard/"),
                                   ("s.rahman", "/student/dashboard/")]:
            c = Client()
            r = c.get(reverse("accounts:login") + "?demo=" + username)
            self.assertEqual(r.status_code, 302)
            self.assertIn(expected, r.url)

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

    def test_demo_login_ignores_unknown_username(self):
        """?demo= only works for the seeded accounts — unknown names get the form."""
        r = self.c.get(reverse("accounts:login") + "?demo=somebody")
        self.assertEqual(r.status_code, 200)  # plain login form, no auto-login
        self.assertFalse(self.c.session.get("_auth_user_id"))

    def test_signup_cannot_set_role_admin(self):
        """Mass assignment: posting role=admin must not elevate a signup."""
        self.c.post(reverse("accounts:signup"), {
            "username": "evil", "password": "secret99", "role": "admin",
        })
        user = User.objects.get(username="evil")
        self.assertEqual(user.role, "student")

    def test_signup_rejects_bogus_department(self):
        """A nonexistent department id must not crash signup or attach junk."""
        r = self.c.post(reverse("accounts:signup"), {
            "username": "deptless", "password": "secret99", "department": "99999",
        })
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(User.objects.get(username="deptless").department)

    def test_signup_huge_email_rejected(self):
        r = self.c.post(reverse("accounts:signup"), {
            "username": "bigmail", "password": "secret99", "email": "a" * 500 + "@x.com",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "at most 254")
        self.assertFalse(User.objects.filter(username="bigmail").exists())

    # ------------------------------------------------------------- signup
    def test_signup_creates_student_and_logs_in(self):
        r = self.c.post(reverse("accounts:signup"), {
            "username": "newbie", "first_name": "N", "last_name": "B",
            "email": "n@b.com", "password": "secret99", "department": self.dept.pk,
        })
        user = User.objects.get(username="newbie")
        self.assertEqual(user.role, "student")
        self.assertEqual(user.department, self.dept)
        self.assertEqual(r.status_code, 302)  # auto-login -> dashboard
        self.assertTrue(self.c.session.get("_auth_user_id"))

    def test_signup_empty_username_rejected(self):
        self.c.post(reverse("accounts:signup"), {"username": "  ", "password": "secret99"})
        self.assertFalse(User.objects.filter(username="").exists())

    def test_signup_duplicate_username_rejected(self):
        self.c.post(reverse("accounts:signup"), {"username": "dup1", "password": "secret99"})
        fresh = Client()  # first signup auto-logs-in; use a fresh session to re-test
        r = fresh.post(reverse("accounts:signup"), {"username": "dup1", "password": "secret99"})
        self.assertEqual(r.status_code, 200)  # stays on form
        self.assertContains(r, "already taken")
        self.assertEqual(User.objects.filter(username="dup1").count(), 1)

    def test_signup_short_password_rejected(self):
        r = self.c.post(reverse("accounts:signup"), {"username": "shortpw", "password": "123"})
        self.assertContains(r, "at least 6")
        self.assertFalse(User.objects.filter(username="shortpw").exists())

    def test_signup_huge_username_rejected(self):
        huge = "x" * 5000
        r = self.c.post(reverse("accounts:signup"), {"username": huge, "password": "secret99"})
        self.assertEqual(r.status_code, 200)  # no crash, stays on form
        self.assertContains(r, "at most 150")
        self.assertFalse(User.objects.filter(username=huge).exists())
