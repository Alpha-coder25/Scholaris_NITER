import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from academics.models import CourseOffering
from accounts.decorators import role_required

from .models import Exam, ExamAnswer, ExamAttempt, ExamQuestion, Question
from .services import (
    attempt_state,
    create_attempt,
    current_answer,
    grade_answer,
    heartbeat,
    submit_answer,
)


# ---------------------------------------------------------------------------
# Teacher: question bank review (approve / discard / edit / add manual)
# ---------------------------------------------------------------------------
@role_required("teacher")
def question_review(request, offering_id):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester"),
        pk=offering_id,
        teacher=request.user,
    )

    if request.method == "POST":
        action = request.POST.get("action")
        question = get_object_or_404(Question, pk=request.POST.get("question_id"))

        if action == "approve":
            question.status = "approved"
            question.approved_by = request.user
            question.save(update_fields=["status", "approved_by"])
            messages.success(request, "Question approved — it can now be used in exams.")
        elif action == "discard":
            question.status = "discarded"
            question.save(update_fields=["status"])
            messages.info(request, "Question discarded.")
        elif action == "restore":
            question.status = "draft" if question.source == "ai_generated" else "approved"
            question.save(update_fields=["status"])
            messages.info(request, "Question restored.")
        return redirect("exams:question_review", offering_id=offering.pk)

    questions = offering.questions.all()
    drafts = [q for q in questions if q.status == "draft"]
    approved = [q for q in questions if q.status == "approved"]
    discarded = [q for q in questions if q.status == "discarded"]

    return render(
        request,
        "teacher/question_review.html",
        {
            "offering": offering,
            "drafts": drafts,
            "approved": approved,
            "discarded": discarded,
        },
    )


@role_required("teacher")
def question_edit(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    if question.course_offering.teacher_id != request.user.id:
        messages.error(request, "You don't have access to that question.")
        return redirect("dashboard:home")

    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        if not text:
            messages.error(request, "Question text cannot be empty.")
        else:
            qtype = request.POST.get("type", question.type)
            question.text = text
            if qtype == "mcq":
                options = [
                    o.strip()
                    for o in request.POST.getlist("options")
                    if o.strip()
                ]
                correct = request.POST.get("correct_index")
                if len(options) < 2 or correct is None:
                    messages.error(request, "MCQ needs at least 2 options and a correct one.")
                else:
                    question.type = "mcq"
                    question.options = options
                    question.correct_answer = int(correct)
                    question.save()
                    messages.success(request, "Question updated.")
            else:
                question.type = "cq"
                question.correct_answer = request.POST.get("reference_answer", "").strip()
                question.save()
                messages.success(request, "Question updated.")
        return redirect("exams:question_review", offering_id=question.course_offering_id)

    return render(
        request,
        "teacher/question_edit.html",
        {"question": question, "offering": question.course_offering},
    )


@role_required("teacher")
def add_manual_question(request, offering_id):
    offering = get_object_or_404(CourseOffering, pk=offering_id, teacher=request.user)
    if request.method == "POST":
        qtype = request.POST.get("type", "mcq")
        text = request.POST.get("text", "").strip()
        if not text:
            messages.error(request, "Question text cannot be empty.")
        elif qtype == "mcq":
            options = [o.strip() for o in request.POST.getlist("options") if o.strip()]
            correct = request.POST.get("correct_index")
            if len(options) < 2 or correct is None:
                messages.error(request, "MCQ needs at least 2 options and a correct one.")
            else:
                Question.objects.create(
                    course_offering=offering,
                    type="mcq",
                    text=text,
                    options=options,
                    correct_answer=int(correct),
                    source="manual",
                    status="approved",
                    approved_by=request.user,
                )
                messages.success(request, "Manual MCQ added to the approved bank.")
        else:
            Question.objects.create(
                course_offering=offering,
                type="cq",
                text=text,
                correct_answer=request.POST.get("reference_answer", "").strip(),
                source="manual",
                status="approved",
                approved_by=request.user,
            )
            messages.success(request, "Manual CQ added to the approved bank.")
        return redirect("exams:question_review", offering_id=offering.pk)
    return redirect("exams:question_review", offering_id=offering.pk)


# ---------------------------------------------------------------------------
# Teacher: exam builder
# ---------------------------------------------------------------------------
@role_required("teacher")
def exam_builder(request, offering_id):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester"),
        pk=offering_id,
        teacher=request.user,
    )
    approved = offering.questions.filter(status="approved").order_by("type", "-created_at")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        duration_min = request.POST.get("duration_minutes", "")
        start_raw = request.POST.get("start_time", "")
        end_raw = request.POST.get("end_time", "")
        selected = [k[2:] for k in request.POST if k.startswith("q_")]

        errors = []
        if not title:
            errors.append("Exam title is required.")
        if len(title) > 200:
            errors.append("Exam title must be at most 200 characters.")
        if not selected:
            errors.append("Select at least one question.")
        try:
            duration_seconds = int(float(duration_min) * 60)
            if duration_seconds <= 0:
                errors.append("Total duration must be positive.")
        except (TypeError, ValueError):
            errors.append("Total duration must be a number (minutes).")
        start_time = parse_datetime(start_raw) if start_raw else None
        if start_time is None:
            errors.append("A valid start time is required.")
        else:
            start_time = timezone.make_aware(start_time)
        end_time = None
        if end_raw:
            end_time = parse_datetime(end_raw)
            end_time = timezone.make_aware(end_time) if end_time else None

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            exam = Exam.objects.create(
                course_offering=offering,
                title=title,
                total_duration_seconds=duration_seconds,
                start_time=start_time,
                end_time=end_time,
                created_by=request.user,
            )
            for order, qid in enumerate(selected, start=1):
                question = Question.objects.get(pk=qid)
                try:
                    limit = int(request.POST.get(f"limit_{qid}", 60))
                except ValueError:
                    limit = 60
                try:
                    marks = int(request.POST.get(f"marks_{qid}", 5))
                except ValueError:
                    marks = 5
                ExamQuestion.objects.create(
                    exam=exam,
                    question=question,
                    order=order,
                    time_limit_seconds=max(10, limit),
                    marks=max(1, marks),
                )
            messages.success(
                request,
                f"Exam “{exam.title}” created with {len(selected)} questions "
                f"({duration_seconds // 60} min total).",
            )
            return redirect("exams:exam_detail", exam_id=exam.pk)

    mcq = [q for q in approved if q.is_mcq]
    cq = [q for q in approved if not q.is_mcq]
    return render(
        request,
        "teacher/exam_builder.html",
        {"offering": offering, "mcq": mcq, "cq": cq},
    )


@role_required("teacher")
def exam_detail(request, exam_id):
    exam = get_object_or_404(
        Exam.objects.select_related("course_offering", "course_offering__course"),
        pk=exam_id,
    )
    if exam.course_offering.teacher_id != request.user.id:
        messages.error(request, "You don't have access to that exam.")
        return redirect("dashboard:home")

    attempts = (
        exam.attempts.select_related("student")
        .prefetch_related("answers")
        .order_by("student__first_name", "student__username")
    )
    return render(
        request,
        "teacher/exam_detail.html",
        {"exam": exam, "attempts": attempts},
    )


@role_required("teacher")
def grading_queue(request, offering_id):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course"),
        pk=offering_id,
        teacher=request.user,
    )
    pending = (
        ExamAnswer.objects.filter(
            attempt__exam__course_offering=offering,
            exam_question__question__type="cq",
            manual_score__isnull=True,
            submitted_at__isnull=False,
        )
        .select_related(
            "attempt",
            "attempt__student",
            "attempt__exam",
            "exam_question",
            "exam_question__question",
        )
        .order_by("attempt__exam", "attempt__student")
    )

    if request.method == "POST":
        # Scope the answer to *this* offering so a teacher can never grade an
        # answer belonging to another teacher's course.
        answer = get_object_or_404(
            ExamAnswer,
            pk=request.POST.get("answer_id"),
            manual_score__isnull=True,
            attempt__exam__course_offering=offering,
        )
        try:
            marks = int(request.POST.get("marks"))
        except (TypeError, ValueError):
            marks = None
        if marks is None or marks < 0:
            messages.error(request, "Enter a valid mark (0 or more).")
        else:
            grade_answer(
                answer,
                marks,
                request.POST.get("comment", "").strip(),
                grader=request.user,
            )
            messages.success(
                request,
                f"Graded {answer.attempt.student.get_full_name() or answer.attempt.student.username} "
                f"— {marks} marks.",
            )
        return redirect("exams:grading_queue", offering_id=offering.pk)

    return render(
        request,
        "teacher/grading_queue.html",
        {"offering": offering, "pending": pending},
    )


@role_required("teacher")
def gradebook(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if exam.course_offering.teacher_id != request.user.id:
        messages.error(request, "You don't have access to that exam.")
        return redirect("dashboard:home")

    rows = []
    for attempt in exam.attempts.select_related("student").prefetch_related(
        "answers", "answers__exam_question"
    ):
        by_eq = {a.exam_question_id: a for a in attempt.answers.all()}
        rows.append({"attempt": attempt, "by_eq": by_eq})

    # Per-question class breakdown — "60% of the class missed Q4".
    question_stats = []
    for eq in exam.exam_questions.prefetch_related("answers"):
        answers = list(eq.answers.all())
        answered = [a for a in answers if a.submitted_at and a.answer_data is not None]
        correct = [a for a in answered if a.auto_score and a.auto_score > 0]
        stats = {
            "eq": eq,
            "answered": len(answered),
            "correct": len(correct),
            "wrong": len(answered) - len(correct),
            "unanswered": len(answers) - len(answered),
            "total": len(answers),
        }
        stats["pct"] = round(100 * stats["correct"] / stats["total"], 0) if stats["total"] else 0
        question_stats.append(stats)

    return render(
        request,
        "teacher/gradebook.html",
        {"exam": exam, "rows": rows, "question_stats": question_stats},
    )


# ---------------------------------------------------------------------------
# Student: take the exam (server-enforced timers)
# ---------------------------------------------------------------------------
def _get_attempt_for_student(exam, student):
    return ExamAttempt.objects.filter(exam=exam, student=student).first()


@role_required("student")
def exam_take(request, exam_id):
    """Entry point: start the exam (first question) or resume an attempt."""
    exam = get_object_or_404(
        Exam.objects.select_related("course_offering", "course_offering__course"),
        pk=exam_id,
    )
    offering = exam.course_offering
    enrollment = offering.enrollments.filter(student=request.user).first()
    if not enrollment:
        messages.error(request, "You're not enrolled in this course.")
        return redirect("dashboard:home")
    if enrollment.suspended:
        messages.error(request, "Your enrollment in this course has been suspended. Contact your instructor.")
        return redirect("dashboard:home")

    attempt = _get_attempt_for_student(exam, request.user)
    if attempt is None:
        if not exam.is_open:
            messages.error(
                request,
                f"This exam is not open yet — it starts {exam.start_time:%b %d, %I:%M %p}.",
            )
            return redirect("dashboard:home")
        attempt = create_attempt(exam, request.user)
    elif attempt.status != "in_progress":
        return redirect("exams:attempt_result", attempt_id=attempt.pk)

    return redirect("exams:attempt_view", attempt_id=attempt.pk)


@role_required("student")
def attempt_view(request, attempt_id):
    """Render the current question. Enforcement runs on every load, so a
    reload can never extend a question's deadline."""
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "exam__course_offering"),
        pk=attempt_id,
        student=request.user,
    )
    if attempt.status != "in_progress":
        return redirect("exams:attempt_result", attempt_id=attempt.pk)

    heartbeat(attempt)
    if attempt.status != "in_progress":
        return redirect("exams:attempt_result", attempt_id=attempt.pk)

    state = attempt_state(attempt)
    if state["finished"]:
        return redirect("exams:attempt_result", attempt_id=attempt.pk)

    return render(
        request,
        "student/exam_take.html",
        {
            "state": state,
            "exam": attempt.exam,
            "offering": attempt.exam.course_offering,
        },
    )


def _fragment(state):
    return render_to_string("student/_question_fragment.html", {"state": state})


@require_POST
@role_required("student")
def attempt_answer(request, attempt_id):
    """Submit the current question's answer (JSON). Server validates timers."""
    attempt = get_object_or_404(
        ExamAttempt, pk=attempt_id, student=request.user
    )
    if attempt.status != "in_progress":
        return JsonResponse({"status": "error", "error": "Attempt already submitted."})

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JsonResponse(
            {"status": "error", "error": "Malformed request body."}, status=400
        )
    raw = body.get("answer")

    # Inspect the question being answered *before* submitting, then evaluate
    # the result from the just-submitted answer object (state after submit
    # refers to the *next* question).
    cur = current_answer(attempt)
    if cur is None:
        return JsonResponse({"status": "error", "error": "No active question."})
    is_mcq = cur.exam_question.question.is_mcq
    if is_mcq and raw is not None:
        try:
            raw = int(raw)
        except (TypeError, ValueError):
            raw = None

    submit_answer(attempt, raw)
    if attempt.status != "in_progress":
        return JsonResponse(
            {
                "status": "finished",
                "url": f"/student/exam-attempts/{attempt.pk}/result/",
            }
        )

    state = attempt_state(attempt)
    if is_mcq:
        if cur.locked:
            flash = "⏱ Timer expired — answer locked, no marks."
        elif cur.auto_score and cur.auto_score > 0:
            flash = f"✓ Correct! +{cur.auto_score} marks"
        else:
            flash = "✗ Incorrect — moving on."
    else:
        flash = "✓ Answer saved — pending teacher review."
    return JsonResponse(
        {
            "status": "ok",
            "html": _fragment(state),
            "flash": flash,
            "overall_left": state["overall_left"],
        }
    )


@require_POST
@role_required("student")
def attempt_heartbeat(request, attempt_id):
    """Periodic poll so the server can force-advance even if the student
    walks away / closes the tab without submitting."""
    attempt = get_object_or_404(
        ExamAttempt, pk=attempt_id, student=request.user
    )
    if attempt.status != "in_progress":
        return JsonResponse(
            {"status": "finished", "url": f"/student/exam-attempts/{attempt.pk}/result/"}
        )

    changed = heartbeat(attempt)
    if attempt.status != "in_progress":
        return JsonResponse(
            {"status": "finished", "url": f"/student/exam-attempts/{attempt.pk}/result/"}
        )
    state = attempt_state(attempt)
    return JsonResponse(
        {
            "status": "ok",
            "changed": bool(changed),
            "html": _fragment(state) if changed else None,
            "overall_left": state["overall_left"],
        }
    )


@role_required("student")
def attempt_result(request, attempt_id):
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "exam__course_offering"),
        pk=attempt_id,
        student=request.user,
    )
    answers = attempt.answers.select_related("exam_question", "exam_question__question")
    return render(
        request,
        "student/exam_result.html",
        {"attempt": attempt, "answers": answers},
    )
