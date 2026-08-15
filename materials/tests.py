"""Materials tests — upload validation, versioning, AI generation flow."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import Course, CourseOffering, Department, Enrollment, Semester
from ai_integration.services import create_draft_questions, extract_text, generate_questions
from exams.models import Question
from .models import Material

User = get_user_model()


class MaterialTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.course = Course.objects.create(department=self.dept, code="CSE-2101", title="DS")
        self.teacher = User.objects.create_user(username="t", password="pw12345678", role="teacher")
        self.other_teacher = User.objects.create_user(username="t2", password="pw12345678", role="teacher")
        self.student = User.objects.create_user(username="s", password="pw12345678", role="student")
        self.offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)
        Enrollment.objects.create(student=self.student, course_offering=self.offering)
        self.c = Client()

    def _upload(self, name="notes.txt", content=b"Linked lists are a linear data structure. Each node stores data and a pointer.", client=None):
        client = client or self.c
        return client.post(reverse("materials:upload", args=[self.offering.pk]), {
            "title": "Lecture 1",
            "file": SimpleUploadedFile(name, content, content_type="text/plain"),
        })

    def test_teacher_uploads_material(self):
        self.c.login(username="t", password="pw12345678")
        r = self._upload()
        self.assertEqual(r.status_code, 302)
        m = Material.objects.get(course_offering=self.offering)
        self.assertEqual(m.version, 1)
        self.assertTrue(m.content_text)  # DB-cached text for serverless

    def test_upload_without_file_rejected(self):
        self.c.login(username="t", password="pw12345678")
        r = self.c.post(reverse("materials:upload", args=[self.offering.pk]), {"title": "No file"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Material.objects.count(), 0)

    def test_upload_without_title_rejected(self):
        self.c.login(username="t", password="pw12345678")
        r = self.c.post(reverse("materials:upload", args=[self.offering.pk]), {
            "title": "  ",
            "file": SimpleUploadedFile("n.txt", b"data", content_type="text/plain"),
        })
        self.assertEqual(Material.objects.count(), 0)

    def test_upload_versioning(self):
        self.c.login(username="t", password="pw12345678")
        self._upload()
        self._upload(content=b"v2 content here. Second upload bumps the version number.")
        versions = list(Material.objects.filter(course_offering=self.offering).values_list("version", flat=True))
        self.assertEqual(sorted(versions), [1, 2])  # same title -> new version, history kept

    def test_non_teacher_cannot_upload(self):
        self.c.login(username="s", password="pw12345678")
        self._upload()
        self.assertEqual(Material.objects.count(), 0)

    def test_other_teacher_cannot_upload_to_this_offering(self):
        self.c.login(username="t2", password="pw12345678")
        self._upload()
        self.assertEqual(Material.objects.count(), 0)

    LONG_LECTURE = (b"A linked list is a linear data structure in which elements are not stored at "
                    b"contiguous memory locations. Each element, called a node, contains the data and a "
                    b"pointer to the next node in the sequence. The head of a linked list is a special "
                    b"pointer that references the first node. If the list is empty, the head is null. "
                    b"Traversal starts at the head and follows the next pointers until a node whose next "
                    b"pointer is null is reached. A singly linked list supports efficient insertion and "
                    b"deletion at the beginning in constant time. Insertion at the end requires a full "
                    b"traversal and takes linear time. A doubly linked list adds a previous pointer to "
                    b"each node, making deletion of a known node run in constant time. A circular linked "
                    b"list connects the last node back to the head, forming a loop. Linked lists are "
                    b"commonly compared to arrays, which offer constant time random access by index. "
                    b"Implementing a stack with a linked list is straightforward, since push and pop both "
                    b"happen at the head in constant time.")

    def test_ai_generation_creates_draft_questions(self):
        self.c.login(username="t", password="pw12345678")
        self._upload(content=self.LONG_LECTURE)
        m = Material.objects.get(course_offering=self.offering)
        r = self.c.get(reverse("materials:generate_questions", args=[self.offering.pk, m.pk]))
        self.assertEqual(r.status_code, 302)
        drafts = Question.objects.filter(course_offering=self.offering, source="ai_generated", status="draft")
        self.assertGreaterEqual(drafts.count(), 3)
        # drafts must include at least one MCQ and one CQ
        self.assertTrue(drafts.filter(type="mcq").exists())
        self.assertTrue(drafts.filter(type="cq").exists())

    def test_ai_generation_scoped_to_material_offering(self):
        other_offering = CourseOffering.objects.create(
            course=self.course, semester=self.sem, teacher=self.other_teacher, section="B")
        m = Material.objects.create(
            course_offering=other_offering, uploaded_by=self.other_teacher,
            title="Other", content_text="Some other text about something entirely different.")
        self.c.login(username="t", password="pw12345678")
        r = self.c.get(reverse("materials:generate_questions", args=[other_offering.pk, m.pk]))
        self.assertEqual(r.status_code, 404)  # teacher t has no access to t2's offering


class AiIntegrationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CSE")
        self.sem = Semester.objects.create(name="Spring 2026")
        self.course = Course.objects.create(department=self.dept, code="CSE-2101", title="DS")
        self.teacher = User.objects.create_user(username="t", password="pw12345678", role="teacher")
        self.offering = CourseOffering.objects.create(course=self.course, semester=self.sem, teacher=self.teacher)

    def test_offline_generator_output_shape(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        m = Material.objects.create(
            course_offering=self.offering, uploaded_by=self.teacher, title="Mat",
            file=SimpleUploadedFile("m.txt", b"Line one about a linked list is a real sentence here. "
                                            b"Another longer sentence describes node pointers and traversal. "
                                            b"A third sentence explains why arrays give constant time access. "
                                            b"A fourth sentence covers dynamic memory allocation costs."))
        drafts, used_ai = generate_questions(m)
        self.assertFalse(used_ai)  # no API key in tests -> offline generator
        mcq = [d for d in drafts if d["type"] == "mcq"]
        cq = [d for d in drafts if d["type"] == "cq"]
        self.assertGreaterEqual(len(mcq), 1)
        self.assertGreaterEqual(len(cq), 1)
        for d in mcq:
            self.assertGreaterEqual(len(d["options"]), 3)
            self.assertIn(d["correct_answer"], range(len(d["options"])))
        self.assertTrue(all(d["text"] and d["text"].strip() for d in drafts))

    def test_create_draft_questions_persists_unapproved(self):
        drafts = [
            {"type": "mcq", "text": "Q?", "options": ["a", "b"], "correct_answer": 1},
            {"type": "cq", "text": "W?", "reference_answer": "A"},
        ]
        created = create_draft_questions(self.offering, drafts)
        self.assertEqual(len(created), 2)
        for q in created:
            self.assertEqual(q.status, "draft")
            self.assertIsNone(q.approved_by)
            self.assertEqual(q.source, "ai_generated")

    def test_extract_text_from_txt(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("a.txt", "hello world".encode(), content_type="text/plain")
        self.assertEqual(extract_text(f).strip(), "hello world")
