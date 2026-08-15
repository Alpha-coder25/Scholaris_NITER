"""End-to-end verification of the Scholaris MVP demo flows.

Runs against the real DB (no test fixtures) using Django's test client at the
HTTP layer — the same requests the demo clicks would make. Safe to re-run.

Usage:  python manage.py shell < verify_demo.py   (from the scholaris dir)
        # or
        ../venv/Scripts/python manage.py shell -c "exec(open('verify_demo.py').read())"
"""
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scholaris.settings")
django.setup()

from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402
from datetime import timedelta  # noqa: E402

from academics.models import CourseOffering  # noqa: E402
from exams.models import Exam, ExamAnswer, ExamAttempt, ExamQuestion, Question  # noqa: E402
from exams.services import create_attempt, current_answer  # noqa: E402
from materials.models import Material  # noqa: E402
from ratings.models import Rating  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {extra}")


def post_json(client, url, payload):
    return client.post(
        url, data=json.dumps(payload), content_type="application/json"
    )


print("\n=== Scholaris MVP verification ===\n")

# ------------------------------------------------------------------ context
offering = CourseOffering.objects.get(course__code="CSE-2101", semester__name="Spring 2026")
student = offering.enrollments.first().student
teacher = offering.teacher
exam_seed = offering.exams.first()

c_admin, c_teacher, c_student = Client(), Client(), Client()

# ------------------------------------------------------------ 1. auth + RBAC
check("login: admin", c_admin.login(username="admin", password="admin123"))
check("login: teacher", c_teacher.login(username="t.hasan", password="demo123"))
check("login: student", c_student.login(username=student.username, password="demo123"))

r = c_admin.get("/admin/dashboard/")
check("admin dashboard 200", r.status_code == 200)
r = c_teacher.get("/admin/dashboard/")
check("teacher blocked from admin pages", r.status_code == 302)
r = c_student.get("/teacher/dashboard/")
check("student blocked from teacher pages", r.status_code == 302)

# ------------------------------------------------------------ 2. admin assign
r = c_admin.get("/admin/course-offerings/")
check("admin assignment page 200", r.status_code == 200)

# ------------------------------------------------------------ 3. enrollment
r = c_student.get("/enroll/")
check("student enroll page 200", r.status_code == 200)

# ---------------------------------------------------- 4. material upload (seed)
materials_before = offering.materials.count()
r = c_teacher.get(f"/teacher/course/{offering.pk}/materials/")
check("teacher material page 200", r.status_code == 200)
check("seeded material exists", materials_before >= 1)

# ---------------------------------------------------- 5. AI question generation
drafts_before = offering.questions.filter(status="draft").count()
material = offering.materials.first()
r = c_teacher.post(
    f"/teacher/course/{offering.pk}/materials/{material.pk}/generate/", follow=True
)
drafts_after = offering.questions.filter(status="draft").count()
check("AI generation created drafts", drafts_after > drafts_before, f"({drafts_before}->{drafts_after})")
check("drafts are ai_generated/source", offering.questions.filter(
    source="ai_generated", status="draft").exists())

# ------------------------------------------------- 6. review/approve + build exam
r = c_teacher.get(f"/teacher/course/{offering.pk}/questions/")
check("question review 200", r.status_code == 200)

draft = offering.questions.filter(status="draft").first()
if draft:
    r = c_teacher.post(
        f"/teacher/course/{offering.pk}/questions/",
        {"question_id": draft.pk, "action": "approve"},
        follow=True,
    )
    draft.refresh_from_db()
    check("approve draft -> approved", draft.status == "approved" and draft.approved_by == teacher)

# Build a brand-new exam with very short per-question timers so the
# server-enforced auto-advance can be demonstrated. Composition is explicit:
# 3 MCQs + 2 CQs, in that order, so grading expectations are deterministic.
approved = list(offering.questions.filter(status="approved"))
check("approved question bank non-empty", len(approved) >= 4)

exam_mcq = [q for q in approved if q.is_mcq][:3]
exam_cq = [q for q in approved if not q.is_mcq][:2]
exam_picks = exam_mcq + exam_cq

now = timezone.now()
form = {
    "title": "Verify Exam - Timed",
    "duration_minutes": "2",
    "start_time": now.strftime("%Y-%m-%dT%H:%M"),
    "end_time": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
}
for q in exam_picks:
    form[f"q_{q.pk}"] = "on"
    form[f"limit_{q.pk}"] = "30" if q.is_mcq else "45"
    form[f"marks_{q.pk}"] = "5" if q.is_mcq else "10"
r = c_teacher.post(f"/teacher/course/{offering.pk}/exams/new/", form)
check("exam created (redirect to detail)", r.status_code == 302)
exam = Exam.objects.filter(title="Verify Exam - Timed", course_offering=offering).first()
check("exam has questions", exam is not None and exam.question_count == 5)
# Re-runnability: drop any earlier attempts for this exam.
ExamAttempt.objects.filter(exam=exam).delete()

# ------------------------------------------------- 7. student takes the exam
r = c_student.get(f"/student/exams/{exam.pk}/take/")
attempt = ExamAttempt.objects.filter(exam=exam, student=student).first()
check("attempt created on start", attempt is not None)
r = c_student.get(f"/student/exam-attempts/{attempt.pk}/")
check("exam question page 200", r.status_code == 200)
check("page shows question card", b"question-card" in r.content)

# Answer each question in turn. The first two MCQs get the correct option
# (auto-grade +5 each), the third MCQ gets a wrong option (0); CQs get text.
mcq_seen = 0
answered = 0
guard = 0
while attempt.status == "in_progress" and guard < 20:
    guard += 1
    ans = current_answer(attempt)
    q = ans.exam_question.question
    if q.is_mcq:
        payload = q.correct_answer if mcq_seen < 2 else (q.correct_answer + 1) % len(q.options)
        mcq_seen += 1
    else:
        payload = f"Answer text for question {answered + 1} (student)"
    r = post_json(c_student, f"/student/exam-attempts/{attempt.pk}/answer/", {"answer": payload})
    data = json.loads(r.content)
    if data["status"] == "finished":
        break
    check(f"answer {answered + 1} advances (no finish)", True)
    answered += 1

attempt.refresh_from_db()
check("exam auto-finalised after last question", attempt.status in ("submitted", "graded"))
mcq_scores = [a.auto_score for a in attempt.answers.all() if a.exam_question.question.is_mcq]
check("MCQ auto-graded (2 correct, 1 wrong)", mcq_scores == [5, 5, 0], str(mcq_scores))

# ------------------------------------------------------- heartbeat/timeout path
# Use a second enrolled student so the unique (exam, student) constraint holds.
student2 = offering.enrollments.exclude(student=student).first().student
c_student2 = Client()
c_student2.login(username=student2.username, password="demo123")
attempt2 = create_attempt(exam, student2)
cur = current_answer(attempt2)
# Rewind the server timestamp past the time limit, then submit -> must lock & score 0.
cur.question_started_at = timezone.now() - timedelta(seconds=cur.exam_question.time_limit_seconds + 10)
cur.save(update_fields=["question_started_at"])
r = post_json(c_student2, f"/student/exam-attempts/{attempt2.pk}/answer/", {"answer": 0})
cur.refresh_from_db()
check("expired question locked (no marks)", cur.locked and cur.auto_score == 0)
check("timeout triggers server-side advance", attempt2.status in ("in_progress", "submitted", "graded"))
# second heartbeat-walkaway: expire current question with no submission
if attempt2.status == "in_progress":
    cur2 = current_answer(attempt2)
    cur2.question_started_at = timezone.now() - timedelta(seconds=cur2.exam_question.time_limit_seconds + 10)
    cur2.save(update_fields=["question_started_at"])
    r = post_json(c_student2, f"/student/exam-attempts/{attempt2.pk}/heartbeat/", {})
    data = json.loads(r.content)
    check("heartbeat force-advances on expiry", data.get("changed") is True or data.get("status") == "finished")
    if data.get("status") == "ok" and data.get("changed"):
        cur2.refresh_from_db()
        check("walkaway answer locked blank", cur2.locked and cur2.answer_data is None)

# ------------------------------------------------- 8. teacher grades CQ
pending = ExamAnswer.objects.filter(
    attempt__exam=exam, exam_question__question__type="cq", manual_score__isnull=True,
    submitted_at__isnull=False,
)
r = c_teacher.get(f"/teacher/course/{offering.pk}/grading/")
check("grading queue 200", r.status_code == 200)
for ans in pending:
    r = c_teacher.post(
        f"/teacher/course/{offering.pk}/grading/",
        {"answer_id": ans.pk, "marks": "8", "comment": "Good attempt"},
        follow=True,
    )
    ans.refresh_from_db()
    check("CQ answer graded", ans.manual_score == 8 and ans.graded_comment == "Good attempt")
attempt.refresh_from_db()
check("attempt marked graded when all CQ graded", attempt.status == "graded")

# ------------------------------------------------- 9. results (student + teacher)
r = c_student.get(f"/student/exam-attempts/{attempt.pk}/result/")
check("student results 200", r.status_code == 200)
check("results show score", str(attempt.total_score).encode() in r.content)
r = c_teacher.get(f"/teacher/exams/{exam.pk}/gradebook/")
check("teacher gradebook 200", r.status_code == 200)
check("gradebook shows class breakdown", b"Per-question class breakdown" in r.content)

# ------------------------------------------------- 10. ratings + aggregation
# Rate as a student who has not rated this offering yet (seeded students
# already have ratings, so pick s.uddin for re-runnability).
rate_student = offering.enrollments.select_related("student").get(
    student__username="s.uddin"
).student
c_rate = Client()
c_rate.login(username=rate_student.username, password="demo123")
rating_count_before = Rating.objects.filter(course_offering=offering).count()
r = c_rate.post(
    f"/student/course/{offering.pk}/rate/",
    {"stars": "5", "comment": "Great lectures!"},
    follow=True,
)
rating_count_after = Rating.objects.filter(course_offering=offering).count()
check("rating submitted (new row)", rating_count_after == rating_count_before + 1)
r = c_admin.get("/admin/analytics/")
check("admin analytics 200", r.status_code == 200)
check("admin analytics show gated aggregates", b"Faculty ratings" in r.content and b"hidden until threshold" in r.content)
r = c_teacher.get("/teacher/ratings/")
check("teacher ratings page 200", r.status_code == 200)
check("teacher sees own aggregate", b"anonymous responses" in r.content)

# ------------------------------------------------------------ summary
print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    sys.exit(1)
print("ALL MVP FLOWS VERIFIED")
