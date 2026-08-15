"""Ratings tests — privacy threshold, one-per-student, role rules."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import Course, CourseOffering, Department, Enrollment, Semester
from ratings.models import Rating
from ratings.views import aggregate_for_offering

User = get_user_model()


class RatingTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.course = Course.objects.create(department=self.dept, code="CSE-2101", title="DS")
        self.teacher = User.objects.create_user(username="t", password="pw12345678", role="teacher")
        self.students = [
            User.objects.create_user(username=f"s{i}", password="pw12345678", role="student")
            for i in range(5)
        ]
        self.offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        for s in self.students:
            Enrollment.objects.create(student=s, course_offering=self.offering)
        self.c = Client()

    def test_student_rates(self):
        self.c.login(username="s0", password="pw12345678")
        r = self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]),
                        {"stars": "5", "comment": "Great"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Rating.objects.filter(student=self.students[0], stars=5).count(), 1)

    def test_invalid_stars_rejected(self):
        self.c.login(username="s0", password="pw12345678")
        self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]), {"stars": "9"})
        self.assertEqual(Rating.objects.count(), 0)
        self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]), {"stars": "0"})
        self.assertEqual(Rating.objects.count(), 0)

    def test_non_enrolled_cannot_rate(self):
        outsider = User.objects.create_user(username="out", password="pw12345678", role="student")
        self.c.login(username="out", password="pw12345678")
        r = self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]), {"stars": "5"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Rating.objects.count(), 0)

    def test_one_rating_per_student_updates(self):
        self.c.login(username="s0", password="pw12345678")
        self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]), {"stars": "2"})
        self.c.post(reverse("ratings:rate_offering", args=[self.offering.pk]), {"stars": "5"})
        self.assertEqual(Rating.objects.filter(student=self.students[0]).count(), 1)
        self.assertEqual(Rating.objects.get(student=self.students[0]).stars, 5)

    def test_aggregate_hidden_below_threshold(self):
        self.assertIsNone(aggregate_for_offering(self.offering))
        Rating.objects.create(course_offering=self.offering, student=self.students[0], stars=5)
        Rating.objects.create(course_offering=self.offering, student=self.students[1], stars=4)
        self.assertIsNone(aggregate_for_offering(self.offering))  # 2 < 3

    def test_aggregate_shown_above_threshold(self):
        for i, s in enumerate(self.students[:4]):
            Rating.objects.create(course_offering=self.offering, student=s, stars=4 if i % 2 else 5)
        agg = aggregate_for_offering(self.offering)
        self.assertIsNotNone(agg)
        self.assertEqual(agg["count"], 4)
        self.assertEqual(agg["avg"], 4.5)

    def test_teacher_rating_page_shows_aggregate(self):
        for s in self.students[:3]:
            Rating.objects.create(course_offering=self.offering, student=s, stars=5)
        self.c.login(username="t", password="pw12345678")
        r = self.c.get(reverse("dashboard:teacher_ratings"))
        self.assertContains(r, "anonymous responses")
