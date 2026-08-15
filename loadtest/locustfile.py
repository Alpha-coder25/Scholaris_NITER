"""Locust load test for Scholaris.

Simulates realistic mixed traffic: anonymous landing-page hits, one-click
demo logins, dashboard loads per role. Run:

    locust -f loadtest/locustfile.py --headless -u 20 -r 5 -t 60s \
        --host https://scholaris-lime.vercel.app
"""
import random

from locust import HttpUser, between, task


class ScholarisUser(HttpUser):
    wait_time = between(0.5, 2.5)

    @task(5)
    def landing(self):
        self.client.get("/")

    @task(3)
    def login_page(self):
        self.client.get("/accounts/login/")

    @task(2)
    def demo_login_student(self):
        self.client.get("/accounts/login/?demo=s.rahman", name="/login?demo=student")

    @task(1)
    def demo_login_admin(self):
        self.client.get("/accounts/login/?demo=admin", name="/login?demo=admin")

    @task(2)
    def signup_page(self):
        self.client.get("/accounts/signup/")


class AuthedStudent(HttpUser):
    """A logged-in student browsing their dashboard (session kept via cookies)."""
    wait_time = between(1, 3)

    def on_start(self):
        self.client.get("/accounts/login/?demo=s.rahman", name="/login?demo=student")

    @task(3)
    def dashboard(self):
        self.client.get("/student/dashboard/")

    @task(2)
    def enroll_page(self):
        self.client.get("/enroll/")
