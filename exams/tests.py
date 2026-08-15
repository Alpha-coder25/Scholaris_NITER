"""Exam engine tests — timers, grading, permissions, builder edge cases."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import CourseOffering, Department, Enrollment, Semester, Course
from .models import Exam, ExamAnswer, ExamAttempt, ExamQuestion, Question
from .services import attempt_state, create_attempt, current_answer, heartbeat, submit_answer

User = get_user_model()


class ExamBase(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE", short_code="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.course = Course.objects.create(department=self.dept, code="CSE-2101", title="Data Structures")
        self.teacher = User.objects.create_user(username="t1", password="pw12345678", role="teacher")
        self.student = User.objects.create_user(username="s1", password="pw12345678", role="student")
        self.other_student = User.objects.create_user(username="s2", password="pw12345678", role="student")
        self.offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        Enrollment.objects.create(student=self.student, course_offering=self.offering)

        self.mcq = Question.objects.create(
            course_offering=self.offering, type="mcq", text="What is 2+2?",
            options=["3", "4", "5"], correct_answer=1, status="approved",
        )
        self.cq = Question.objects.create(
            course_offering=self.offering, type="cq", text="Explain testing.",
            correct_answer="Write tests.", status="approved",
        )
        self.exam = Exam.objects.create(
            course_offering=self.offering, title="Mid", total_duration_seconds=120,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1), created_by=self.teacher,
        )
        self.eq_mcq = ExamQuestion.objects.create(exam=self.exam, question=self.mcq, order=1, time_limit_seconds=30, marks=5)
        self.eq_cq = ExamQuestion.objects.create(exam=self.exam, question=self.cq, order=2, time_limit_seconds=30, marks=10)


# ---------------------------------------------------------------------------
# Exam engine unit tests (server-side timer enforcement)
# ---------------------------------------------------------------------------
class ExamEngineTests(ExamBase):
    def _expire(self, answer, extra_seconds=5):
        answer.question_started_at = timezone.now() - timedelta(
            seconds=answer.exam_question.time_limit_seconds + extra_seconds
        )
        answer.save(update_fields=["question_started_at"])

    def test_create_attempt_starts_at_question_one(self):
        attempt = create_attempt(self.exam, self.student)
        self.assertEqual(attempt.status, "in_progress")
        self.assertEqual(current_answer(attempt).exam_question_id, self.eq_mcq.pk)

    def test_mcq_auto_graded_correct(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        ans = attempt.answers.get(exam_question=self.eq_mcq)
        self.assertEqual(ans.auto_score, 5)
        self.assertFalse(ans.locked)

    def test_mcq_auto_graded_wrong(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 0)
        ans = attempt.answers.get(exam_question=self.eq_mcq)
        self.assertEqual(ans.auto_score, 0)

    def test_submit_just_under_limit_accepted(self):
        attempt = create_attempt(self.exam, self.student)
        ans = current_answer(attempt)
        # Elapsed just under the limit (29s < 30s) must be accepted; a
        # real-world submit always lands a hair before the stored deadline.
        ans.question_started_at = timezone.now() - timedelta(seconds=29)
        ans.save(update_fields=["question_started_at"])
        submit_answer(attempt, 1)
        ans.refresh_from_db()
        self.assertEqual(ans.auto_score, 5)
        self.assertFalse(ans.locked)

    def test_submit_after_limit_locks_with_no_credit(self):
        attempt = create_attempt(self.exam, self.student)
        ans = current_answer(attempt)
        self._expire(ans)
        submit_answer(attempt, 1)  # correct answer, but late
        ans.refresh_from_db()
        self.assertTrue(ans.locked)
        self.assertEqual(ans.auto_score, 0)  # no credit for late answers

    def test_overall_timer_expiry_finalizes(self):
        attempt = create_attempt(self.exam, self.student)
        # Rewind the attempt's own clock so the overall 120s limit is exceeded.
        attempt.started_at = timezone.now() - timedelta(seconds=200)
        attempt.save(update_fields=["started_at"])
        submit_answer(attempt, 1)
        attempt.refresh_from_db()
        self.assertNotEqual(attempt.status, "in_progress")

    def test_heartbeat_walkaway_advances_and_locks_blank(self):
        attempt = create_attempt(self.exam, self.student)
        ans = current_answer(attempt)
        self._expire(ans)
        changed = heartbeat(attempt)
        ans.refresh_from_db()
        self.assertTrue(changed)
        self.assertTrue(ans.locked)
        self.assertIsNone(ans.answer_data)
        # advanced to question 2
        self.assertEqual(current_answer(attempt).exam_question_id, self.eq_cq.pk)

    def test_heartbeat_noop_within_limit(self):
        attempt = create_attempt(self.exam, self.student)
        changed = heartbeat(attempt)
        self.assertFalse(changed)

    def test_heartbeat_finalizes_when_overall_time_up(self):
        attempt = create_attempt(self.exam, self.student)
        # Rewind the attempt's own clock so the overall 120s limit is exceeded.
        attempt.started_at = timezone.now() - timedelta(seconds=200)
        attempt.save(update_fields=["started_at"])
        heartbeat(attempt)
        attempt.refresh_from_db()
        self.assertNotEqual(attempt.status, "in_progress")

    def test_finalize_after_last_question(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        submit_answer(attempt, "my cq answer")
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "submitted")  # CQ pending -> submitted
        self.assertEqual(current_answer(attempt), None)

    def test_submit_after_finalized_is_noop(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        submit_answer(attempt, "text")
        attempt.refresh_from_db()
        result = submit_answer(attempt, "extra")  # nothing left to answer
        self.assertIsNotNone(result)
        attempt.refresh_from_db()
        self.assertEqual(attempt.answers.count(), 2)

    def test_attempt_graded_once_all_cq_graded(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        submit_answer(attempt, "answer text")
        cq_answer = attempt.answers.get(exam_question=self.eq_cq)
        self.assertEqual(attempt.status, "submitted")
        from .services import grade_answer
        grade_answer(cq_answer, 8, "Good", grader=self.teacher)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "graded")
        self.assertEqual(attempt.total_score, 5 + 8)

    def test_one_attempt_per_student_enforced(self):
        create_attempt(self.exam, self.student)
        with self.assertRaises(Exception):
            create_attempt(self.exam, self.student)  # unique (exam, student)

    def test_attempt_state_finished_when_done(self):
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        submit_answer(attempt, "text")
        state = attempt_state(attempt)
        self.assertTrue(state["finished"])


# ---------------------------------------------------------------------------
# Exam view tests (permissions, windows, flow)
# ---------------------------------------------------------------------------
class ExamViewTests(ExamBase):
    def setUp(self):
        super().setUp()
        self.c = Client()

    def test_exam_take_requires_login(self):
        r = self.c.get(reverse("exams:exam_take", args=[self.exam.pk]))
        self.assertIn(r.status_code, (302, 403))

    def test_non_enrolled_student_blocked(self):
        self.c.login(username="s2", password="pw12345678")
        r = self.c.get(reverse("exams:exam_take", args=[self.exam.pk]))
        self.assertNotEqual(r.status_code, 200)  # redirected away

    def test_exam_window_not_open_cannot_start(self):
        self.exam.start_time = timezone.now() + timedelta(days=1)
        self.exam.save()
        self.c.login(username="s1", password="pw12345678")
        r = self.c.get(reverse("exams:exam_take", args=[self.exam.pk]))
        self.assertEqual(r.status_code, 302)  # redirected, no attempt created
        self.assertFalse(ExamAttempt.objects.filter(exam=self.exam, student=self.student).exists())

    def test_answer_api_rejects_student_b_accessing_student_a_attempt(self):
        self.c.login(username="s1", password="pw12345678")
        attempt = create_attempt(self.exam, self.student)
        self.c.login(username="s2", password="pw12345678")
        r = self.c.post(reverse("exams:attempt_view", args=[attempt.pk]))
        self.assertEqual(r.status_code, 404)  # IDOR blocked

    def test_answer_after_submit_returns_error(self):
        self.c.login(username="s1", password="pw12345678")
        self.c.get(reverse("exams:exam_take", args=[self.exam.pk]), follow=True)
        attempt = ExamAttempt.objects.get(exam=self.exam, student=self.student)
        # answer both questions (mcq then cq)
        for _ in range(2):
            ans = current_answer(attempt)
            payload = {"answer": 1 if ans.exam_question.question.is_mcq else "text"}
            self.c.post(reverse("exams:attempt_answer", args=[attempt.pk]),
                        data=json.dumps(payload), content_type="application/json")
        attempt.refresh_from_db()
        r = self.c.post(reverse("exams:attempt_answer", args=[attempt.pk]),
                        data=json.dumps({"answer": "x"}), content_type="application/json")
        self.assertIn(b"error", r.content)  # no active question / already submitted

    def test_answer_api_rejects_malformed_json(self):
        """A non-object JSON body (fuzz) must return 400, not crash."""
        self.c.login(username="s1", password="pw12345678")
        self.c.get(reverse("exams:exam_take", args=[self.exam.pk]), follow=True)
        attempt = ExamAttempt.objects.get(exam=self.exam, student=self.student)
        for bad in ["1", "\"hi\"", "[1,2]", "{"]:
            r = self.c.post(reverse("exams:attempt_answer", args=[attempt.pk]),
                            data=bad, content_type="application/json")
            self.assertEqual(r.status_code, 400)
            self.assertIn(b"error", r.content)

    def test_teacher_only_views(self):
        self.c.login(username="s1", password="pw12345678")
        r = self.c.get(reverse("exams:grading_queue", args=[self.offering.pk]))
        self.assertEqual(r.status_code, 302)  # student cannot grade
        self.c.login(username="t1", password="pw12345678")
        r = self.c.get(reverse("exams:grading_queue", args=[self.offering.pk]))
        self.assertEqual(r.status_code, 200)

    def test_teacher_cannot_touch_another_teachers_question(self):
        other_teacher = User.objects.create_user(username="t2", password="pw12345678", role="teacher")
        self.c.login(username="t2", password="pw12345678")
        r = self.c.post(reverse("exams:question_edit", args=[self.mcq.pk]),
                        {"text": "hacked", "type": "mcq", "options": ["a", "b"], "correct_index": 0})
        self.mcq.refresh_from_db()
        self.assertNotEqual(self.mcq.text, "hacked")  # blocked

    def test_exam_builder_rejects_empty_selection(self):
        self.c.login(username="t1", password="pw12345678")
        r = self.c.post(reverse("exams:exam_builder", args=[self.offering.pk]), {
            "title": "Empty exam", "duration_minutes": "5",
            "start_time": (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(r.status_code, 200)  # re-renders with error
        self.assertFalse(Exam.objects.filter(title="Empty exam").exists())

    def test_exam_builder_rejects_bad_duration(self):
        self.c.login(username="t1", password="pw12345678")
        r = self.c.post(reverse("exams:exam_builder", args=[self.offering.pk]), {
            "title": "Bad", "duration_minutes": "abc",
            "start_time": (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            f"q_{self.mcq.pk}": "on",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Exam.objects.filter(title="Bad").exists())

    def test_exam_builder_creates_ordered_questions(self):
        self.c.login(username="t1", password="pw12345678")
        r = self.c.post(reverse("exams:exam_builder", args=[self.offering.pk]), {
            "title": "Real", "duration_minutes": "5",
            "start_time": (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            f"q_{self.cq.pk}": "on", f"q_{self.mcq.pk}": "on",
            f"limit_{self.cq.pk}": "60", f"marks_{self.cq.pk}": "10",
            f"limit_{self.mcq.pk}": "20", f"marks_{self.mcq.pk}": "5",
        })
        self.assertEqual(r.status_code, 302)
        exam = Exam.objects.get(title="Real")
        orders = list(exam.exam_questions.values_list("order", flat=True))
        self.assertEqual(orders, [1, 2])  # submission order preserved

    def test_grading_queue_only_own_offering(self):
        other_dept = Department.objects.create(name="EEE")
        other_course = Course.objects.create(department=other_dept, code="EEE-1", title="Circuits")
        other_teacher = User.objects.create_user(username="t3", password="pw12345678", role="teacher")
        CourseOffering.objects.create(course=other_course, semester=self.sem, teacher=other_teacher)
        self.c.login(username="t3", password="pw12345678")
        r = self.c.get(reverse("exams:grading_queue", args=[self.offering.pk]))
        self.assertEqual(r.status_code, 404)  # not your offering -> not found

    def test_student_result_page_idor(self):
        attempt = create_attempt(self.exam, self.student)
        self.c.login(username="s2", password="pw12345678")
        r = self.c.get(reverse("exams:attempt_result", args=[attempt.pk]))
        self.assertEqual(r.status_code, 404)

    def test_other_teacher_cannot_edit_offering_question(self):
        other_teacher = User.objects.create_user(username="t5", password="pw12345678", role="teacher")
        self.c.login(username="t5", password="pw12345678")
        r = self.c.get(reverse("exams:question_edit", args=[self.mcq.pk]))
        self.assertEqual(r.status_code, 302)  # redirected to home, not 200

    def test_exam_builder_fuzz_rejects_garbage(self):
        """Wrong types / huge strings / negative numbers must not create exams."""
        self.c.login(username="t1", password="pw12345678")
        base = {
            "title": "Fuzz", "duration_minutes": "-5",
            "start_time": (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            f"q_{self.mcq.pk}": "on",
            f"limit_{self.mcq.pk}": "-999", f"marks_{self.mcq.pk}": "0",
        }
        r = self.c.post(reverse("exams:exam_builder", args=[self.offering.pk]), base)
        self.assertEqual(r.status_code, 200)  # re-renders with error, no crash
        self.assertFalse(Exam.objects.filter(title="Fuzz").exists())

        # Oversized title (5,000 chars) must be rejected, not crash the DB.
        big = dict(base, title="x" * 5000, duration_minutes="5")
        r = self.c.post(reverse("exams:exam_builder", args=[self.offering.pk]), big)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Exam.objects.filter(title="x" * 5000).exists())

    def test_grading_rejects_negative_and_non_numeric_marks(self):
        self.c.login(username="t1", password="pw12345678")
        attempt = create_attempt(self.exam, self.student)
        submit_answer(attempt, 1)
        submit_answer(attempt, "text")
        cq = attempt.answers.get(exam_question=self.eq_cq)
        for bad in ("-3", "abc", ""):
            self.c.post(reverse("exams:grading_queue", args=[self.offering.pk]),
                        {"answer_id": cq.pk, "marks": bad})
        cq.refresh_from_db()
        self.assertIsNone(cq.manual_score)  # never graded with junk marks

    def test_student_cannot_submit_to_other_students_attempt(self):
        self.c.login(username="s1", password="pw12345678")
        attempt = create_attempt(self.exam, self.student)
        self.c.login(username="s2", password="pw12345678")
        r = self.c.post(reverse("exams:attempt_answer", args=[attempt.pk]),
                        data=json.dumps({"answer": 1}), content_type="application/json")
        self.assertEqual(r.status_code, 404)  # IDOR blocked, not just rejected
        self.assertEqual(attempt.answers.exclude(submitted_at__isnull=True).count(), 0)

    def test_grading_other_offering_answer_404(self):
        """A teacher grading an answer from another teacher's offering gets 404."""
        other_teacher = User.objects.create_user(username="t6", password="pw12345678", role="teacher")
        other_offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=other_teacher, section="B")
        other_q = Question.objects.create(
            course_offering=other_offering, type="cq", text="Other?",
            correct_answer="x", status="approved")
        other_exam = Exam.objects.create(
            course_offering=other_offering, title="Other", total_duration_seconds=60,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1), created_by=other_teacher,
        )
        ExamQuestion.objects.create(exam=other_exam, question=other_q, order=1, time_limit_seconds=30, marks=5)
        attempt = create_attempt(other_exam, self.student)
        submit_answer(attempt, "text")
        ans = attempt.answers.get(exam_question__question=other_q)
        self.c.login(username="t1", password="pw12345678")
        self.c.post(reverse("exams:grading_queue", args=[self.offering.pk]),
                    {"answer_id": ans.pk, "marks": "5"})
        ans.refresh_from_db()
        self.assertIsNone(ans.manual_score)  # t1 cannot grade t6's answer
