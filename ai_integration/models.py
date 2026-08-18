from django.db import models


class AIUsageLog(models.Model):
    """Tracks every AI API call for observability, cost monitoring, and
    quality assurance. Only created when the Anthropic API is actually called
    (not for offline fallback generations).
    """

    FEATURE_CHOICES = [
        ("question_generation", "Question Generation"),
        ("cq_evaluation", "CQ Answer Evaluation"),
        ("progress_analysis", "Student Progress Analysis"),
        ("topic_extraction", "Topic Extraction"),
    ]
    STATUS_CHOICES = [
        ("success", "Success"),
        ("error", "Error"),
        ("fallback", "Offline Fallback"),
    ]

    feature = models.CharField(max_length=30, choices=FEATURE_CHOICES)
    model_used = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="success")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.feature} — {self.status} ({self.latency_ms}ms)"


class StudentTopicPerformance(models.Model):
    """Cached AI analysis of a student's performance on specific topics
    within a course offering. Updated after each exam grading cycle.
    """

    student = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="topic_performances",
        limit_choices_to={"role": "student"},
    )
    course_offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="topic_performances",
    )
    topic = models.CharField(max_length=200)
    total_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    total_marks_earned = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total_marks_possible = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    strength_level = models.CharField(
        max_length=10,
        choices=[
            ("strong", "Strong"),
            ("moderate", "Moderate"),
            ("weak", "Weak"),
            ("critical", "Critical"),
        ],
        default="moderate",
    )
    ai_analysis = models.TextField(blank=True)
    last_analyzed = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "course_offering", "topic")
        ordering = ["student", "course_offering", "topic"]

    def __str__(self):
        return f"{self.student} — {self.topic} ({self.strength_level})"

    @property
    def accuracy_pct(self):
        if self.total_questions == 0:
            return 0
        return round(100 * self.correct_answers / self.total_questions, 1)

    @property
    def score_pct(self):
        if self.total_marks_possible == 0:
            return 0
        return round(100 * float(self.total_marks_earned) / float(self.total_marks_possible), 1)
