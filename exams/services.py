"""
Exam engine — server-authoritative timer enforcement.

The client shows a countdown for UX only. Every state transition is decided
here, on the server, using timestamps the server itself wrote:

  * `ExamAttempt.started_at`          — base of the overall exam timer
  * `ExamAnswer.question_started_at`  — base of the per-question timer

On every answer submission, heartbeat, or page render we recompute elapsed
time from those timestamps and compare against the stored limits. A student
cannot extend a question by pausing JS, tampering with local state, or
reloading the page — the deadline never moves.
"""
from django.utils import timezone

from .models import ExamAnswer, ExamAttempt


# ---------------------------------------------------------------------------
# Attempt lifecycle
# ---------------------------------------------------------------------------
def create_attempt(exam, student):
    """Start an attempt: create it and immediately serve question 1."""
    attempt = ExamAttempt.objects.create(exam=exam, student=student)
    advance(attempt)
    return attempt


def current_answer(attempt):
    """The first unanswered exam question of this attempt (None if finished)."""
    return (
        attempt.answers.filter(submitted_at__isnull=True)
        .order_by("exam_question__order")
        .first()
    )


def _elapsed(answer):
    return (timezone.now() - answer.question_started_at).total_seconds()


def _overall_elapsed(attempt):
    return (timezone.now() - attempt.started_at).total_seconds()


def submit_answer(attempt, answer_data):
    """Accept an answer for the current question.

    Enforcement rules (all server-side):
      * If the per-question time limit has expired, the answer is locked as-is
        and receives no credit (auto_score stays 0 for MCQ).
      * If the overall exam duration has expired, the whole attempt is
        finalised on the spot.
      * Otherwise MCQ answers are auto-graded immediately against the stored
        correct answer; CQ answers enter the teacher's grading queue.
    """
    now = timezone.now()
    answer = current_answer(attempt)
    if answer is None:
        return finalize(attempt)

    eq = answer.exam_question
    question = eq.question

    within_limit = _elapsed(answer) <= eq.time_limit_seconds
    within_overall = _overall_elapsed(attempt) <= attempt.exam.total_duration_seconds

    if not within_limit:
        # Timer expired: lock whatever was submitted (or blank), no credit.
        answer.answer_data = answer_data
        answer.submitted_at = now
        answer.locked = True
        answer.auto_score = 0 if question.is_mcq else None
        answer.save(update_fields=["answer_data", "submitted_at", "locked", "auto_score"])
    elif not within_overall:
        answer.answer_data = answer_data
        answer.submitted_at = now
        answer.locked = True
        answer.auto_score = 0 if question.is_mcq else None
        answer.save(update_fields=["answer_data", "submitted_at", "locked", "auto_score"])
        return finalize(attempt)
    else:
        answer.answer_data = answer_data
        answer.submitted_at = now
        answer.locked = False
        if question.is_mcq:
            answer.auto_score = (
                eq.marks if answer_data == question.correct_answer else 0
            )
        answer.save(
            update_fields=["answer_data", "submitted_at", "locked", "auto_score"]
        )

    return advance(attempt)


def heartbeat(attempt):
    """Safety net for 'student walks away': if the current question's timer
    has lapsed without a submission, lock it blank and advance; if the overall
    timer has lapsed, finalise. Returns True if state changed."""
    answer = current_answer(attempt)
    if answer is None:
        return finalize(attempt), True

    changed = False
    if _elapsed(answer) > answer.exam_question.time_limit_seconds:
        answer.submitted_at = timezone.now()
        answer.locked = True
        answer.auto_score = 0 if answer.exam_question.question.is_mcq else None
        answer.save(update_fields=["submitted_at", "locked", "auto_score"])
        advance(attempt)
        changed = True
    elif _overall_elapsed(attempt) > attempt.exam.total_duration_seconds:
        answer.submitted_at = timezone.now()
        answer.locked = True
        answer.auto_score = 0 if answer.exam_question.question.is_mcq else None
        answer.save(update_fields=["submitted_at", "locked", "auto_score"])
        finalize(attempt)
        changed = True
    return changed


def advance(attempt):
    """Serve the next unanswered question, or finalise when none remain."""
    answered_ids = set(attempt.answers.values_list("exam_question_id", flat=True))
    next_eq = (
        attempt.exam.exam_questions.exclude(id__in=answered_ids)
        .order_by("order")
        .first()
    )
    if next_eq is not None:
        ExamAnswer.objects.create(
            attempt=attempt,
            exam_question=next_eq,
            question_started_at=timezone.now(),
        )
        return None  # still in progress
    return finalize(attempt)


def finalize(attempt):
    """Mark the attempt submitted (graded if no CQ answers remain pending)."""
    attempt.submitted_at = timezone.now()
    attempt.status = "submitted" if attempt.has_pending_cq else "graded"
    attempt.save(update_fields=["submitted_at", "status"])
    # Lock any stragglers (shouldn't exist, but be safe).
    attempt.answers.filter(submitted_at__isnull=True).update(
        submitted_at=attempt.submitted_at, locked=True
    )
    return attempt


def grade_answer(answer, marks, comment="", grader=None):
    """Teacher grades one CQ answer; marks the attempt graded when all CQ
    answers have a manual score."""
    answer.manual_score = marks
    answer.graded_comment = comment
    answer.graded_by = grader
    answer.save(update_fields=["manual_score", "graded_comment", "graded_by"])

    attempt = answer.attempt
    if not attempt.has_pending_cq:
        attempt.status = "graded"
        attempt.save(update_fields=["status"])
    return answer


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def attempt_state(attempt):
    """Serialisable state used to render (or re-render) the current question."""
    answer = current_answer(attempt)
    eq = answer.exam_question if answer else None
    question = eq.question if eq else None
    now = timezone.now()

    overall_left = max(
        0, int(attempt.exam.total_duration_seconds - _overall_elapsed(attempt))
    )
    question_left = None
    if answer is not None:
        question_left = max(
            0, int(eq.time_limit_seconds - (now - answer.question_started_at).total_seconds())
        )

    total_questions = attempt.exam.question_count
    current_number = eq.order if eq else total_questions

    return {
        "attempt": attempt,
        "answer": answer,
        "exam_question": eq,
        "question": question,
        "current_number": current_number,
        "total_questions": total_questions,
        "question_left": question_left,
        "overall_left": overall_left,
        "overall_deadline_ms": int(
            (attempt.started_at.timestamp() + attempt.exam.total_duration_seconds) * 1000
        ),
        "finished": answer is None,
    }
