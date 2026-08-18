import json
from unittest.mock import patch, MagicMock

from django import mail
from django.test import TestCase

from accounts.models import User
from academics.models import Department, Semester, Course, CourseOffering, Enrollment
from exams.models import Question, Exam, ExamQuestion, ExamAttempt, ExamAnswer
from .models import AIUsageLog, StudentTopicPerformance
from .services import (
    generate_questions,
    create_draft_questions,
    analyze_student_progress,
    generate_ai_progress_insights,
    evaluate_cq_answer,
    _offline_cq_evaluation,
    _extract_topic,
    generation_source_label,
)


class AIUsageLogTest(TestCase):
    """Tests for the AIUsageLog model."""

    def test_create_log(self):
        log = AIUsageLog.objects.create(
            feature="question_generation",
            status="success",
            latency_ms=1200,
            input_tokens=500,
            output_tokens=200,
            model_used="claude-sonnet-4-5",
        )
        self.assertEqual(log.feature, "question_generation")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.latency_ms, 1200)
        self.assertIn("claude-sonnet", log.model_used)

    def test_log_str(self):
        log = AIUsageLog.objects.create(
            feature="cq_evaluation",
            status="success",
            latency_ms=800,
        )
        self.assertIn("cq_evaluation", str(log))
        self.assertIn("800ms", str(log))

    def test_log_with_metadata(self):
        log = AIUsageLog.objects.create(
            feature="progress_analysis",
            status="success",
            metadata={"course_id": 1, "students_analyzed": 25},
        )
        self.assertEqual(log.metadata["course_id"], 1)
        self.assertEqual(log.metadata["students_analyzed"], 25)

    def test_log_ordering(self):
        AIUsageLog.objects.create(feature="question_generation", status="success")
        AIUsageLog.objects.create(feature="cq_evaluation", status="error")
        logs = list(AIUsageLog.objects.values_list("feature", flat=True))
        # Most recent first
        self.assertEqual(logs[0], "cq_evaluation")


class StudentTopicPerformanceTest(TestCase):
    """Tests for the StudentTopicPerformance model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="teststudent", password="pass123", role="student"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.teacher = User.objects.create_user(
            username="testteacher", password="pass123", role="teacher"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )

    def test_create_performance(self):
        perf = StudentTopicPerformance.objects.create(
            student=self.user,
            course_offering=self.offering,
            topic="Data Structures",
            total_questions=10,
            correct_answers=7,
            total_marks_earned=35,
            total_marks_possible=50,
            strength_level="moderate",
        )
        self.assertEqual(perf.accuracy_pct, 70.0)
        self.assertEqual(perf.score_pct, 70.0)

    def test_zero_questions(self):
        perf = StudentTopicPerformance.objects.create(
            student=self.user,
            course_offering=self.offering,
            topic="Empty Topic",
        )
        self.assertEqual(perf.accuracy_pct, 0)
        self.assertEqual(perf.score_pct, 0)

    def test_strong_level(self):
        perf = StudentTopicPerformance.objects.create(
            student=self.user,
            course_offering=self.offering,
            topic="Algorithms",
            total_questions=10,
            correct_answers=9,
            strength_level="strong",
        )
        self.assertIn("strong", str(perf))


class TopicExtractionTest(TestCase):
    """Tests for the _extract_topic helper."""

    def test_explain_pattern(self):
        topic = _extract_topic("Explain the concept of polymorphism in OOP.")
        self.assertIn("polymorphism", topic.lower())

    def test_what_pattern(self):
        topic = _extract_topic("What is a binary search tree?")
        self.assertIn("binary search tree", topic.lower())

    def test_fallback(self):
        topic = _extract_topic("12345")
        self.assertIsInstance(topic, str)
        self.assertTrue(len(topic) > 0)


class OfflineCQEvaluationTest(TestCase):
    """Tests for the offline CQ answer evaluator."""

    def test_good_answer(self):
        ref = "A binary search tree is a tree where each node has at most two children. The left child contains values less than the parent, and the right child contains values greater. This enables O(log n) search time."
        ans = "A binary search tree has two children per node. Left values are smaller, right values are larger. Search time is logarithmic."
        result = _offline_cq_evaluation(ans, ref)
        self.assertIn("suggested_score", result)
        self.assertGreater(result["suggested_score"], 30)
        self.assertTrue(len(result["feedback"]) > 0)

    def test_empty_answer(self):
        result = _offline_cq_evaluation("", "Some reference text here.")
        self.assertEqual(result["suggested_score"], 0)

    def test_empty_reference(self):
        result = _offline_cq_evaluation("My answer", "")
        self.assertEqual(result["suggested_score"], 50)


class OfflineProgressInsightsTest(TestCase):
    """Tests for the offline progress insight generator."""

    def test_no_data(self):
        from .services import _offline_progress_insights
        data = {"topic_summary": [], "student_gaps": [], "class_overview": {"total_students": 0}}
        insights = _offline_progress_insights(data)
        self.assertEqual(len(insights), 1)
        self.assertIn("No exam data", insights[0])

    def test_low_average(self):
        from .services import _offline_progress_insights
        data = {
            "topic_summary": [{"topic": "X", "accuracy_pct": 20}],
            "student_gaps": [{"overall_accuracy_pct": 30}],
            "class_overview": {"total_students": 10, "avg_score_pct": 35},
        }
        insights = _offline_progress_insights(data)
        self.assertTrue(any("low" in i.lower() or "35%" in i for i in insights))

    def test_weak_topics(self):
        from .services import _offline_progress_insights
        data = {
            "topic_summary": [
                {"topic": "Algorithms", "accuracy_pct": 25},
                {"topic": "OS Concepts", "accuracy_pct": 30},
            ],
            "student_gaps": [],
            "class_overview": {"total_students": 10, "avg_score_pct": 55},
        }
        insights = _offline_progress_insights(data)
        self.assertTrue(any("attention" in i.lower() or "Algorithms" in i for i in insights))


class GenerateQuestionsTest(TestCase):
    """Tests for the question generation pipeline (offline path)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.user
        )
        # Create a material with content_text (simulating extracted text)
        from materials.models import Material
        self.material = Material.objects.create(
            course_offering=self.offering,
            uploaded_by=self.user,
            title="Lecture 1: Data Structures",
            content_text="Data structures are ways of organizing and storing data. Arrays provide O(1) access by index. Linked lists allow efficient insertion and deletion. Trees enable hierarchical data organization with O(log n) search in balanced forms. Hash tables provide O(1) average-case lookup using key-value mapping.",
        )

    def test_generate_offline_questions(self):
        """Offline generator produces MCQ and CQ questions."""
        drafts, used_ai = generate_questions(self.material)
        self.assertFalse(used_ai)
        self.assertGreater(len(drafts), 0)
        mcq = [d for d in drafts if d["type"] == "mcq"]
        cq = [d for d in drafts if d["type"] == "cq"]
        self.assertGreater(len(mcq), 0)
        self.assertGreater(len(cq), 0)
        # MCQ has options and correct_answer
        for q in mcq:
            self.assertIn("options", q)
            self.assertGreater(len(q["options"]), 1)
            self.assertIn("correct_answer", q)
            self.assertIn("text", q)

    def test_create_draft_questions(self):
        """create_draft_questions persists Question rows."""
        drafts = [
            {"type": "mcq", "text": "Q1?", "options": ["A", "B"], "correct_answer": 0},
            {"type": "cq", "text": "Q2?", "reference_answer": "ref"},
        ]
        created = create_draft_questions(self.offering, drafts)
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].source, "ai_generated")
        self.assertEqual(created[0].status, "draft")
        self.assertIsNone(created[0].approved_by)
        self.assertEqual(created[1].type, "cq")

    def test_generation_source_label(self):
        self.assertIn("offline", generation_source_label(False))
        self.assertIn("Claude", generation_source_label(True))

    def test_empty_material_fallback(self):
        """Material with no content still produces questions."""
        from materials.models import Material
        mat = Material.objects.create(
            course_offering=self.offering,
            uploaded_by=self.user,
            title="Empty Lecture",
            content_text="",
        )
        drafts, used_ai = generate_questions(mat)
        self.assertGreater(len(drafts), 0)


class AnalyzeStudentProgressTest(TestCase):
    """Tests for the student progress analysis service."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.student1 = User.objects.create_user(
            username="student1", password="pass123", role="student"
        )
        self.student2 = User.objects.create_user(
            username="student2", password="pass123", role="student"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )
        Enrollment.objects.create(student=self.student1, course_offering=self.offering)
        Enrollment.objects.create(student=self.student2, course_offering=self.offering)

        # Create questions and exam
        q1 = Question.objects.create(
            course_offering=self.offering, type="mcq",
            text="What is a binary search tree?",
            options=["A tree", "A graph", "A list"],
            correct_answer=0, source="manual", status="approved",
            approved_by=self.teacher,
        )
        q2 = Question.objects.create(
            course_offering=self.offering, type="cq",
            text="Explain the concept of polymorphism.",
            correct_answer="Polymorphism is...", source="manual", status="approved",
            approved_by=self.teacher,
        )

        from django.utils import timezone
        now = timezone.now()
        exam = Exam.objects.create(
            course_offering=self.offering, title="Test Exam",
            total_duration_seconds=1800, start_time=now, end_time=now + __import__('datetime').timedelta(hours=1),
            created_by=self.teacher,
        )
        eq1 = ExamQuestion.objects.create(exam=exam, question=q1, order=1, time_limit_seconds=30, marks=5)
        eq2 = ExamQuestion.objects.create(exam=exam, question=q2, order=2, time_limit_seconds=60, marks=10)

        # Create attempts and answers
        att1 = ExamAttempt.objects.create(exam=exam, student=self.student1, status="graded")
        ExamAnswer.objects.create(
            attempt=att1, exam_question=eq1, question_started_at=now,
            answer_data=0, submitted_at=now, auto_score=5, locked=False,
        )
        ExamAnswer.objects.create(
            attempt=att1, exam_question=eq2, question_started_at=now,
            answer_data="My answer", submitted_at=now, manual_score=8, locked=False,
        )

        att2 = ExamAttempt.objects.create(exam=exam, student=self.student2, status="graded")
        ExamAnswer.objects.create(
            attempt=att2, exam_question=eq1, question_started_at=now,
            answer_data=1, submitted_at=now, auto_score=0, locked=False,
        )
        ExamAnswer.objects.create(
            attempt=att2, exam_question=eq2, question_started_at=now,
            answer_data="Another answer", submitted_at=now, manual_score=5, locked=False,
        )

    def test_analyze_returns_structure(self):
        result = analyze_student_progress(self.offering)
        self.assertIn("topic_summary", result)
        self.assertIn("student_gaps", result)
        self.assertIn("class_overview", result)
        self.assertEqual(result["class_overview"]["total_students"], 2)

    def test_topic_summary_sorted_by_weakness(self):
        result = analyze_student_progress(self.offering)
        topics = result["topic_summary"]
        self.assertGreater(len(topics), 0)
        # Should be sorted by score ascending (weakest first)
        for i in range(len(topics) - 1):
            self.assertLessEqual(
                topics[i]["score_pct"], topics[i + 1]["score_pct"]
            )

    def test_student_gaps(self):
        result = analyze_student_progress(self.offering)
        gaps = result["student_gaps"]
        self.assertEqual(len(gaps), 2)
        # student2 has lower accuracy (0% on MCQ)
        self.assertEqual(gaps[0]["student_id"], self.student2.id)

    def test_no_data_returns_empty(self):
        offering2 = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher, section="B"
        )
        result = analyze_student_progress(offering2)
        self.assertEqual(result["class_overview"]["total_students"], 0)


class EvaluateCQAnswerTest(TestCase):
    """Tests for the CQ answer evaluation service (offline path)."""

    def test_with_reference(self):
        result = evaluate_cq_answer(
            "A hash table uses a hash function to map keys to array indices.",
            "A hash table maps keys to values using a hash function for O(1) lookup.",
            "What is a hash table?",
        )
        self.assertIn("suggested_score", result)
        self.assertIn("feedback", result)
        self.assertIsInstance(result["strengths"], list)
        self.assertIsInstance(result["gaps"], list)

    def test_empty_answer(self):
        result = evaluate_cq_answer("", "Some reference", "Question?")
        self.assertEqual(result["suggested_score"], 0)
        self.assertTrue(any("missing" in g.lower() for g in result["gaps"]))

    def test_empty_reference(self):
        result = evaluate_cq_answer("My answer", "", "Question?")
        self.assertEqual(result["suggested_score"], 0)


class AIGenerationWithMockTest(TestCase):
    """Tests for AI generation with mocked Anthropic API."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.user
        )
        from materials.models import Material
        self.material = Material.objects.create(
            course_offering=self.offering,
            uploaded_by=self.user,
            title="Lecture 1",
            content_text="Binary search trees organize data hierarchically. Each node has at most two children. Left child < parent < right child.",
        )

    @patch("ai_integration.services.anthropic")
    @patch("ai_integration.services.settings")
    def test_anthropic_generation_success(self, mock_settings, mock_anthropic):
        """Mock Anthropic API returns structured questions."""
        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_settings.AI_MODEL = "claude-sonnet-4-5"

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_message = MagicMock()
        mock_message.content = [MagicMock(type="text", text=json.dumps({
            "questions": [
                {"type": "mcq", "text": "What is BST?", "options": ["Tree", "Graph"], "correct_index": 0},
                {"type": "cq", "text": "Explain BST", "reference_answer": "BST is..."},
            ]
        }))]
        mock_message.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_message

        with patch("ai_integration.services.anthropic", mock_anthropic):
            with patch("ai_integration.services.settings", mock_settings):
                drafts, used_ai = generate_questions(self.material)

        self.assertTrue(used_ai)
        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0]["type"], "mcq")
        self.assertEqual(drafts[1]["type"], "cq")

    def test_anthropic_not_installed_fallback(self):
        """Without anthropic module, falls back to offline."""
        drafts, used_ai = generate_questions(self.material)
        self.assertFalse(used_ai)
        self.assertGreater(len(drafts), 0)


class RefreshTopicPerformanceTest(TestCase):
    """Tests for the student topic performance cache refresh."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.student = User.objects.create_user(
            username="student1", password="pass123", role="student"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )
        Enrollment.objects.create(student=self.student, course_offering=self.offering)

        # Create questions and exam
        q1 = Question.objects.create(
            course_offering=self.offering, type="mcq",
            text="What is a binary search tree?",
            options=["A tree", "A graph"],
            correct_answer=0, source="manual", status="approved",
            approved_by=self.teacher,
        )

        from django.utils import timezone
        import datetime
        now = timezone.now()
        exam = Exam.objects.create(
            course_offering=self.offering, title="Test Exam",
            total_duration_seconds=1800, start_time=now,
            end_time=now + datetime.timedelta(hours=1),
            created_by=self.teacher,
        )
        self.eq1 = ExamQuestion.objects.create(
            exam=exam, question=q1, order=1, time_limit_seconds=30, marks=5
        )

        # Create attempt and answer
        self.attempt = ExamAttempt.objects.create(
            exam=exam, student=self.student, status="graded"
        )
        ExamAnswer.objects.create(
            attempt=self.attempt, exam_question=self.eq1,
            question_started_at=now, answer_data=0, submitted_at=now,
            auto_score=5, locked=False,
        )

    def test_refresh_creates_performance_records(self):
        """refresh_student_topic_performance creates StudentTopicPerformance records."""
        from .services import refresh_student_topic_performance

        count = refresh_student_topic_performance(self.offering)
        self.assertEqual(count, 1)

        perf = StudentTopicPerformance.objects.get(
            student=self.student, course_offering=self.offering
        )
        self.assertEqual(perf.total_questions, 1)
        self.assertEqual(perf.correct_answers, 1)
        self.assertEqual(perf.strength_level, "strong")

    def test_refresh_specific_student(self):
        """refresh can target a specific student."""
        from .services import refresh_student_topic_performance

        other_student = User.objects.create_user(
            username="student2", password="pass123", role="student"
        )
        Enrollment.objects.create(student=other_student, course_offering=self.offering)

        count = refresh_student_topic_performance(self.offering, student=self.student)
        self.assertEqual(count, 1)
        self.assertFalse(
            StudentTopicPerformance.objects.filter(student=other_student).exists()
        )

    def test_refresh_updates_existing_records(self):
        """Refresh updates existing records rather than creating duplicates."""
        from .services import refresh_student_topic_performance

        refresh_student_topic_performance(self.offering)
        refresh_student_topic_performance(self.offering)

        self.assertEqual(
            StudentTopicPerformance.objects.filter(
                student=self.student, course_offering=self.offering
            ).count(),
            1,
        )

    def test_grade_answer_triggers_refresh(self):
        """Grading an answer triggers topic cache refresh."""
        from exams.services import grade_answer
        from .models import StudentTopicPerformance

        # Create a CQ answer to grade
        q2 = Question.objects.create(
            course_offering=self.offering, type="cq",
            text="Explain polymorphism.",
            correct_answer="Polymorphism is...",
            source="manual", status="approved", approved_by=self.teacher,
        )
        eq2 = ExamQuestion.objects.create(
            exam=self.attempt.exam, question=q2, order=2,
            time_limit_seconds=60, marks=10,
        )
        ans = ExamAnswer.objects.create(
            attempt=self.attempt, exam_question=eq2,
            question_started_at=self.attempt.started_at,
            answer_data="My answer", submitted_at=self.attempt.started_at,
            locked=False,
        )

        # Grade it
        grade_answer(ans, 8, "Good attempt", grader=self.teacher)

        # Cache should be updated
        perf = StudentTopicPerformance.objects.filter(
            student=self.student, course_offering=self.offering
        ).first()
        self.assertIsNotNone(perf)
        self.assertGreater(perf.total_questions, 0)


class WeakTopicsNotificationTest(TestCase):
    """Tests for the weak topics email notification service."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.student = User.objects.create_user(
            username="student1", password="pass123", role="student",
            email="student1@test.com",
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )
        Enrollment.objects.create(student=self.student, course_offering=self.offering)

    def test_no_notification_when_above_threshold(self):
        """No email sent when accuracy is above threshold."""
        from .services import check_and_notify_weak_topics

        StudentTopicPerformance.objects.create(
            student=self.student,
            course_offering=self.offering,
            topic="Good Topic",
            total_questions=10,
            correct_answers=8,
            strength_level="strong",
        )

        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            notified = check_and_notify_weak_topics(self.offering)

        self.assertEqual(len(notified), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_notification_sent_for_critical_topics(self):
        """Email sent when accuracy is below threshold."""
        from .services import check_and_notify_weak_topics

        StudentTopicPerformance.objects.create(
            student=self.student,
            course_offering=self.offering,
            topic="Weak Topic",
            total_questions=10,
            correct_answers=2,
            strength_level="critical",
        )

        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            AI_WEAK_TOPIC_THRESHOLD=30,
        ):
            notified = check_and_notify_weak_topics(self.offering)

        self.assertIn("student1@test.com", notified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Weak Topics", mail.outbox[0].subject)
        self.assertIn("CS101", mail.outbox[0].subject)

    def test_notification_disabled_by_setting(self):
        """No email sent when AI_NOTIFY_WEAK_TOPICS is False."""
        from .services import check_and_notify_weak_topics

        StudentTopicPerformance.objects.create(
            student=self.student,
            course_offering=self.offering,
            topic="Weak Topic",
            total_questions=10,
            correct_answers=2,
            strength_level="critical",
        )

        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            AI_NOTIFY_WEAK_TOPICS=False,
        ):
            notified = check_and_notify_weak_topics(self.offering)

        self.assertEqual(len(notified), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_specific_student_notification(self):
        """Notification can target a specific student."""
        from .services import check_and_notify_weak_topics

        other = User.objects.create_user(
            username="student2", password="pass123", role="student",
            email="student2@test.com",
        )
        Enrollment.objects.create(student=other, course_offering=self.offering)

        # Both have weak topics
        StudentTopicPerformance.objects.create(
            student=self.student, course_offering=self.offering,
            topic="Topic A", total_questions=10, correct_answers=2,
            strength_level="critical",
        )
        StudentTopicPerformance.objects.create(
            student=other, course_offering=self.offering,
            topic="Topic B", total_questions=10, correct_answers=1,
            strength_level="critical",
        )

        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            AI_WEAK_TOPIC_THRESHOLD=30,
        ):
            notified = check_and_notify_weak_topics(self.offering, student=self.student)

        self.assertIn("student1@test.com", notified)
        self.assertNotIn("student2@test.com", notified)
        self.assertEqual(len(mail.outbox), 1)

    def test_no_email_without_address(self):
        """Student without email doesn't cause errors."""
        from .services import check_and_notify_weak_topics

        no_email_student = User.objects.create_user(
            username="noemail", password="pass123", role="student", email=""
        )
        Enrollment.objects.create(student=no_email_student, course_offering=self.offering)

        StudentTopicPerformance.objects.create(
            student=no_email_student, course_offering=self.offering,
            topic="Weak", total_questions=10, correct_answers=1,
            strength_level="critical",
        )

        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            notified = check_and_notify_weak_topics(self.offering)

        self.assertEqual(len(notified), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_content_includes_topics(self):
        """Email body includes the weak topic names."""
        from .services import check_and_notify_weak_topics

        StudentTopicPerformance.objects.create(
            student=self.student, course_offering=self.offering,
            topic="Binary Search Trees", total_questions=10, correct_answers=1,
            strength_level="critical",
        )

        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            AI_WEAK_TOPIC_THRESHOLD=30,
        ):
            check_and_notify_weak_topics(self.offering)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Binary Search Trees", mail.outbox[0].body)


class TeacherStudentOverviewTest(TestCase):
    """Tests for the teacher student overview service."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.student1 = User.objects.create_user(
            username="student1", password="pass123", role="student"
        )
        self.student2 = User.objects.create_user(
            username="student2", password="pass123", role="student"
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )
        Enrollment.objects.create(student=self.student1, course_offering=self.offering)
        Enrollment.objects.create(student=self.student2, course_offering=self.offering)

        # Create questions
        q1 = Question.objects.create(
            course_offering=self.offering, type="mcq",
            text="What is a binary search tree?",
            options=["A tree", "A graph"],
            correct_answer=0, source="manual", status="approved",
            approved_by=self.teacher,
        )
        q2 = Question.objects.create(
            course_offering=self.offering, type="mcq",
            text="Explain polymorphism.",
            options=["OOP concept", "Data structure"],
            correct_answer=0, source="manual", status="approved",
            approved_by=self.teacher,
        )

        from django.utils import timezone
        import datetime
        now = timezone.now()
        exam = Exam.objects.create(
            course_offering=self.offering, title="Test Exam",
            total_duration_seconds=1800, start_time=now,
            end_time=now + datetime.timedelta(hours=1),
            created_by=self.teacher,
        )
        eq1 = ExamQuestion.objects.create(exam=exam, question=q1, order=1, time_limit_seconds=30, marks=5)
        eq2 = ExamQuestion.objects.create(exam=exam, question=q2, order=2, time_limit_seconds=30, marks=5)

        # Student 1: good performance
        att1 = ExamAttempt.objects.create(exam=exam, student=self.student1, status="graded")
        ExamAnswer.objects.create(
            attempt=att1, exam_question=eq1, question_started_at=now,
            answer_data=0, submitted_at=now, auto_score=5, locked=False,
        )
        ExamAnswer.objects.create(
            attempt=att1, exam_question=eq2, question_started_at=now,
            answer_data=0, submitted_at=now, auto_score=5, locked=False,
        )

        # Student 2: poor performance
        att2 = ExamAttempt.objects.create(exam=exam, student=self.student2, status="graded")
        ExamAnswer.objects.create(
            attempt=att2, exam_question=eq1, question_started_at=now,
            answer_data=1, submitted_at=now, auto_score=0, locked=False,
        )
        ExamAnswer.objects.create(
            attempt=att2, exam_question=eq2, question_started_at=now,
            answer_data=1, submitted_at=now, auto_score=0, locked=False,
        )

    def test_overview_returns_all_students(self):
        """Overview includes all enrolled students."""
        from .services import generate_teacher_student_overview

        summaries = generate_teacher_student_overview(self.offering)
        self.assertEqual(len(summaries), 2)
        student_ids = {s["student"].id for s in summaries}
        self.assertIn(self.student1.id, student_ids)
        self.assertIn(self.student2.id, student_ids)

    def test_overview_sorted_by_risk(self):
        """Students are sorted by risk level (high first)."""
        from .services import generate_teacher_student_overview

        summaries = generate_teacher_student_overview(self.offering)
        # student2 has 0% accuracy (high risk), student1 has 100% (low risk)
        self.assertEqual(summaries[0]["student"].id, self.student2.id)
        self.assertEqual(summaries[0]["risk_level"], "high")
        self.assertEqual(summaries[1]["student"].id, self.student1.id)
        self.assertEqual(summaries[1]["risk_level"], "low")

    def test_overview_includes_weak_topics(self):
        """Overview includes weak topics for struggling students."""
        from .services import generate_teacher_student_overview

        summaries = generate_teacher_student_overview(self.offering)
        student2_summary = next(s for s in summaries if s["student"].id == self.student2.id)
        self.assertGreater(len(student2_summary["weak_topics"]), 0)

    def test_overview_includes_strong_topics(self):
        """Overview includes strong topics for performing students."""
        from .services import generate_teacher_student_overview

        summaries = generate_teacher_student_overview(self.offering)
        student1_summary = next(s for s in summaries if s["student"].id == self.student1.id)
        self.assertGreater(len(student1_summary["strong_topics"]), 0)

    def test_overview_no_data_students(self):
        """Students with no exam data get no_data risk level."""
        from .services import generate_teacher_student_overview

        student3 = User.objects.create_user(
            username="student3", password="pass123", role="student"
        )
        Enrollment.objects.create(student=student3, course_offering=self.offering)

        summaries = generate_teacher_student_overview(self.offering)
        student3_summary = next(s for s in summaries if s["student"].id == student3.id)
        self.assertEqual(student3_summary["risk_level"], "no_data")
        self.assertEqual(student3_summary["accuracy_pct"], 0)


class CSVExportTest(TestCase):
    """Tests for the CSV export services."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher1", password="pass123", role="teacher"
        )
        self.student = User.objects.create_user(
            username="student1", password="pass123", role="student",
            email="student1@test.com",
            first_name="John", last_name="Doe",
        )
        self.dept = Department.objects.create(name="CSE", short_code="CS")
        self.sem = Semester.objects.create(name="Semester 5", number=5)
        self.course = Course.objects.create(
            department=self.dept, semester=self.sem, code="CS101", title="Intro to CS"
        )
        self.offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher
        )
        Enrollment.objects.create(student=self.student, course_offering=self.offering)

        # Create questions and exam
        q1 = Question.objects.create(
            course_offering=self.offering, type="mcq",
            text="What is a binary search tree?",
            options=["A tree", "A graph"],
            correct_answer=0, source="manual", status="approved",
            approved_by=self.teacher,
        )
        from django.utils import timezone
        import datetime
        now = timezone.now()
        exam = Exam.objects.create(
            course_offering=self.offering, title="Test Exam",
            total_duration_seconds=1800, start_time=now,
            end_time=now + datetime.timedelta(hours=1),
            created_by=self.teacher,
        )
        eq1 = ExamQuestion.objects.create(exam=exam, question=q1, order=1, time_limit_seconds=30, marks=5)
        att = ExamAttempt.objects.create(exam=exam, student=self.student, status="graded")
        ExamAnswer.objects.create(
            attempt=att, exam_question=eq1, question_started_at=now,
            answer_data=0, submitted_at=now, auto_score=5, locked=False,
        )

    def test_export_performance_csv(self):
        """Performance CSV includes student data and headers."""
        from .services import export_student_performance_csv

        csv_content, filename = export_student_performance_csv(self.offering)
        self.assertIn("student1", csv_content)
        self.assertIn("John Doe", csv_content)
        self.assertIn("student1@test.com", csv_content)
        self.assertIn("CS101", filename)
        self.assertTrue(filename.endswith(".csv"))

    def test_export_performance_csv_headers(self):
        """Performance CSV has correct headers."""
        from .services import export_student_performance_csv

        csv_content, _ = export_student_performance_csv(self.offering)
        first_line = csv_content.strip().split("\n")[0]
        self.assertIn("Student Name", first_line)
        self.assertIn("Accuracy", first_line)
        self.assertIn("Risk Level", first_line)
        self.assertIn("Weak Topics", first_line)

    def test_export_topic_csv(self):
        """Topic CSV includes topic performance data."""
        from .services import export_topic_analysis_csv

        # First refresh cache so StudentTopicPerformance records exist
        from .services import refresh_student_topic_performance
        refresh_student_topic_performance(self.offering)

        csv_content, filename = export_topic_analysis_csv(self.offering)
        self.assertIn("student1", csv_content)
        self.assertIn("binary", csv_content.lower())
        self.assertTrue(filename.endswith(".csv"))

    def test_export_topic_csv_empty(self):
        """Topic CSV with no data has only headers."""
        from .services import export_topic_analysis_csv

        offering2 = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.teacher, section="B"
        )
        csv_content, filename = export_topic_analysis_csv(offering2)
        lines = csv_content.strip().split("\n")
        self.assertEqual(len(lines), 1)  # Only header
        self.assertIn("Topic", lines[0])

    def test_csv_view_returns_download(self):
        """CSV export view returns a downloadable file."""
        self.client.login(username="teacher1", password="pass123")
        resp = self.client.get(f"/ai/teacher/course/{self.offering.pk}/export/performance/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("CS101", resp["Content-Disposition"])

    def test_csv_view_requires_teacher(self):
        """Students cannot access CSV export."""
        self.client.login(username="student1", password="pass123")
        resp = self.client.get(f"/ai/teacher/course/{self.offering.pk}/export/performance/")
        self.assertNotEqual(resp.status_code, 200)

    def test_csv_view_other_teacher_forbidden(self):
        """Teacher cannot export another teacher's offering."""
        other_teacher = User.objects.create_user(
            username="teacher2", password="pass123", role="teacher"
        )
        self.client.login(username="teacher2", password="pass123")
        resp = self.client.get(f"/ai/teacher/course/{self.offering.pk}/export/performance/")
        self.assertEqual(resp.status_code, 404)

