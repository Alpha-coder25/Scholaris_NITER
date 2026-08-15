"""Locust load test for Scholaris.

Simulates realistic mixed traffic: anonymous landing-page hits, login/signup
pages, and a self-registered student browsing their dashboard. Run:

    locust -f loadtest/locustfile.py --headless -u 20 -r 5 -t 60s \
        --host https://scholaris-lime.vercel.app
"""
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
    def signup_page(self):
        self.client.get("/accounts/signup/")


class AuthedStudent(HttpUser):
    """A self-registered student browsing their dashboard."""
    wait_time = between(1, 3)

    def on_start(self):
        # Self-registration is public; create a throwaway student per load user.
        import uuid

        self.username = f"load_{uuid.uuid4().hex[:10]}"
        self.client.post(
            "/accounts/signup/",
            data={
                "username": self.username,
                "first_name": "Load",
                "last_name": "Test",
                "password": "LoadPass-2026!",
                "department": "",
            },
        )

    @task(3)
    def dashboard(self):
        self.client.get("/student/dashboard/")

    @task(2)
    def enroll_page(self):
        self.client.get("/enroll/")
