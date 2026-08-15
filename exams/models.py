from django.conf import settings
from django.db import models


class Question(models.Model):
    """Question bank entry for a course offering.

    source='ai_generated' questions stay status='draft' (invisible to students)
    until a teacher approves them — AI drafts, humans publish.
    """

    TYPE_CHOICES = [("mcq", "MCQ"), ("cq", "CQ")]
    SOURCE_CHOICES = [("manual", "Manual"), ("ai_generated", "AI-generated")]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("approved", "Approved"),
        ("discarded", "Discarded"),
    ]

    course_offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="questions",
    )
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    text = models.TextField()
    options = models.JSONField(default=list, blank=True)  # MCQ: list of option strings
    correct_answer = models.JSONField(null=True, blank=True)  # MCQ: option index; CQ: reference answer
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_questions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_type_display()}] {self.text[:60]}"

    @property
    def is_mcq(self):
        return self.type == "mcq"


class Exam(models.Model):
    course_offering = models.ForeignKey(
        "academics.CourseOffering", on_delete=models.CASCADE, related_name="exams"
    )
    title = models.CharField(max_length=200)
    total_duration_seconds = models.PositiveIntegerField(default=900)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_exams"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.title} — {self.course_offering}"

    @property
    def is_scheduled(self):
        from django.utils import timezone

        return self.start_time > timezone.now()

    @property
    def is_open(self):
        from django.utils import timezone

        now = timezone.now()
        return self.start_time <= now and (self.end_time is None or now <= self.end_time)

    @property
    def is_closed(self):
        from django.utils import timezone

        return self.end_time is not None and self.end_time < timezone.now()

    @property
    def max_score(self):
        return sum(eq.marks for eq in self.exam_questions.all()) or 0

    @property
    def question_count(self):
        return self.exam_questions.count()


class ExamQuestion(models.Model):
    """Ordered join table: which questions are in an exam, in what order,
    with per-question time limit and marks."""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="exam_questions")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="exam_usages")
    order = models.PositiveIntegerField()
    time_limit_seconds = models.PositiveIntegerField(default=60)
    marks = models.PositiveIntegerField(default=5)

    class Meta:
        ordering = ["order"]
        unique_together = ("exam", "order")

    def __str__(self):
        return f"Q{self.order} ({self.time_limit_seconds}s / {self.marks} marks)"


class ExamAttempt(models.Model):
    STATUS_CHOICES = [
        ("in_progress", "In progress"),
        ("submitted", "Submitted"),
        ("graded", "Graded"),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_attempts"
    )
    started_at = models.DateTimeField(auto_now_add=True)  # server-set; overall timer base
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="in_progress")

    class Meta:
        ordering = ["-started_at"]
        unique_together = ("exam", "student")  # one attempt per student per exam

    def __str__(self):
        return f"{self.student} — {self.exam.title}"

    @property
    def total_score(self):
        return sum(
            (a.auto_score or 0) + (a.manual_score or 0) for a in self.answers.all()
        )

    @property
    def max_score(self):
        return self.exam.max_score

    @property
    def has_pending_cq(self):
        return self.answers.filter(
            exam_question__question__type="cq", manual_score__isnull=True
        ).exists()


class ExamAnswer(models.Model):
    """One answer to one exam question. question_started_at is set by the
    server and is the basis for per-question timer enforcement."""

    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="answers")
    exam_question = models.ForeignKey(
        ExamQuestion, on_delete=models.CASCADE, related_name="answers"
    )
    question_started_at = models.DateTimeField()  # server-set, never trusted from client
    answer_data = models.JSONField(null=True, blank=True)  # MCQ: option index; CQ: text
    submitted_at = models.DateTimeField(null=True, blank=True)
    auto_score = models.IntegerField(null=True, blank=True)  # MCQ, set on submit
    manual_score = models.IntegerField(null=True, blank=True)  # CQ, set by teacher
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="graded_answers",
    )
    graded_comment = models.TextField(blank=True)
    locked = models.BooleanField(default=False)  # True once timer expired or submitted

    class Meta:
        ordering = ["exam_question__order"]
        unique_together = ("attempt", "exam_question")

    def __str__(self):
        return f"{self.attempt} — {self.exam_question}"
