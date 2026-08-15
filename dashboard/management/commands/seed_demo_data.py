"""Seed realistic demo data for the Scholaris hackathon demo.

Idempotent — safe to run repeatedly (get_or_create everywhere).

There are NO published demo credentials. Each seeded user gets a strong random
password (printed once to the console at seed time), or — for deterministic
setups like CI — the value of the SEED_PASSWORD environment variable.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from academics.models import Course, CourseOffering, Department, Enrollment, Semester
from exams.models import Exam, ExamQuestion, Question
from materials.models import Material
from ratings.models import Rating

User = get_user_model()

LECTURE_NOTES = """Lecture 4 — Linked Lists (CSE-2101 Data Structures)

A linked list is a linear data structure in which elements are not stored at
contiguous memory locations. Instead, each element, called a node, contains
two parts: the data and a pointer (or reference) to the next node in the
sequence. Because of this, a linked list can grow and shrink dynamically at
runtime, unlike a static array whose size is fixed when it is created.

The head of a linked list is a special pointer that references the first node.
If the list is empty, the head is null. Traversal starts at the head and
follows the next pointers until a node whose next pointer is null is reached,
which marks the end of the list.

The singly linked list supports efficient insertion and deletion at the
beginning of the list in constant time, O(1). Insertion at the end, however,
requires a full traversal and therefore takes linear time, O(n). Searching for
an element also takes O(n) in the worst case because the list is not indexed
like an array.

A doubly linked list extends the singly linked list by adding a previous
pointer to each node. This makes traversal in both directions possible and
makes deletion of a node whose pointer is known run in O(1) time, at the cost
of one extra pointer per node.

A circular linked list connects the last node back to the head, forming a
loop. This is useful for applications such as round-robin scheduling in
operating systems, where the scheduler repeatedly cycles through a fixed set
of processes.

Linked lists are commonly compared to arrays. Arrays offer O(1) random access
by index and better cache locality, while linked lists offer O(1) insertion
and deletion at known positions and dynamic sizing without reallocation. The
choice between them depends on the dominant operations of the application:
frequent insertions and deletions favour a linked list, while frequent random
access favours an array.

Implementing a stack with a linked list is straightforward: push is insertion
at the head and pop is deletion of the head, both O(1). The same structure can
implement a queue using a head and a tail pointer so that enqueue appends at
the tail and dequeue removes from the head, also in constant time.
"""


class Command(BaseCommand):
    help = "Seed demo departments, users, courses, materials, questions, exam and ratings."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Scholaris demo data…")

        def password_for(user):
            """Deterministic via SEED_PASSWORD when set; otherwise random."""
            if settings.SEED_PASSWORD:
                return settings.SEED_PASSWORD
            return secrets.token_urlsafe(16)

        generated = {}  # username -> password, printed once at the end

        # ------------------------------------------------------------- departments
        depts = {
            "CSE": Department.objects.get_or_create(
                name="Computer Science & Engineering", defaults={"short_code": "CSE"}
            )[0],
            "EEE": Department.objects.get_or_create(
                name="Electrical & Electronic Engineering", defaults={"short_code": "EEE"}
            )[0],
            "TE": Department.objects.get_or_create(
                name="Textile Engineering", defaults={"short_code": "TE"}
            )[0],
            "IPE": Department.objects.get_or_create(
                name="Industrial & Production Engineering", defaults={"short_code": "IPE"}
            )[0],
            "FDAE": Department.objects.get_or_create(
                name="Fashion Design & Apparel Engineering", defaults={"short_code": "FDAE"}
            )[0],
        }

        # -------------------------------------------------------------- semester
        semester, _ = Semester.objects.get_or_create(
            name="Spring 2026",
            defaults={
                "start_date": timezone.now().date() - timedelta(days=45),
                "end_date": timezone.now().date() + timedelta(days=120),
                "is_active": True,
            },
        )
        Semester.objects.get_or_create(
            name="Fall 2025",
            defaults={
                "start_date": timezone.now().date() - timedelta(days=220),
                "end_date": timezone.now().date() - timedelta(days=40),
                "is_active": False,
            },
        )

        # ---------------------------------------------------------------- users
        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "first_name": "Institution",
                "last_name": "Admin",
                "role": "admin",
                "is_staff": True,
                "email": "admin@niter.edu.bd",
            },
        )
        admin_pw = password_for(admin)
        admin.set_password(admin_pw)
        admin.is_staff = True
        admin.save()
        generated["admin"] = admin_pw

        def make_user(username, first, last, role, dept, emp_id=None, stu_id=None):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": role,
                    "department": dept,
                    "employee_id": emp_id or "",
                    "student_id_no": stu_id or "",
                    "email": f"{username}@niter.edu.bd",
                },
            )
            pw = password_for(user)
            user.set_password(pw)
            user.save()
            generated[user.username] = pw
            return user

        t_hasan = make_user("t.hasan", "Mahmudul", "Hasan", "teacher", depts["CSE"], "T-101")
        t_karim = make_user("t.karim", "Ayesha", "Karim", "teacher", depts["EEE"], "T-102")
        t_islam = make_user("t.islam", "Rafiqul", "Islam", "teacher", depts["TE"], "T-103")

        students = {
            "s.rahman": make_user("s.rahman", "Sabrina", "Rahman", "student", depts["CSE"], stu_id="2020-CSE-001"),
            "s.ahmed": make_user("s.ahmed", "Tanvir", "Ahmed", "student", depts["CSE"], stu_id="2021-CSE-014"),
            "s.chowdhury": make_user("s.chowdhury", "Nusrat", "Chowdhury", "student", depts["CSE"], stu_id="2021-CSE-022"),
            "s.hossain": make_user("s.hossain", "Arif", "Hossain", "student", depts["CSE"], stu_id="2022-CSE-007"),
            "s.uddin": make_user("s.uddin", "Rakib", "Uddin", "student", depts["CSE"], stu_id="2022-CSE-031"),
            "s.kabir": make_user("s.kabir", "Farzana", "Kabir", "student", depts["EEE"], stu_id="2021-EEE-009"),
            "s.mia": make_user("s.mia", "Jahid", "Mia", "student", depts["EEE"], stu_id="2022-EEE-018"),
            "s.sultana": make_user("s.sultana", "Mehjabin", "Sultana", "student", depts["TE"], stu_id="2022-TE-011"),
        }

        # --------------------------------------------------------------- courses
        def make_course(dept, code, title, credits):
            course, _ = Course.objects.get_or_create(
                department=dept,
                code=code,
                defaults={"title": title, "credit_hours": credits},
            )
            return course

        c_ds = make_course(depts["CSE"], "CSE-2101", "Data Structures", 3)
        c_oop = make_course(depts["CSE"], "CSE-2103", "Object Oriented Programming", 3)
        c_os = make_course(depts["CSE"], "CSE-3101", "Operating Systems", 3)
        c_eee = make_course(depts["EEE"], "EEE-1101", "Basic Electrical Engineering", 3)
        c_te = make_course(depts["TE"], "TE-1101", "Yarn Manufacturing I", 3)

        # ------------------------------------------------------------ offerings
        def make_offering(course, teacher, section="A"):
            offering, _ = CourseOffering.objects.get_or_create(
                course=course,
                semester=semester,
                section=section,
                defaults={"teacher": teacher},
            )
            if offering.teacher_id != teacher.pk:
                offering.teacher = teacher
                offering.save()
            return offering

        o_ds = make_offering(c_ds, t_hasan)
        o_oop = make_offering(c_oop, t_hasan)
        o_os = make_offering(c_os, t_hasan)
        o_eee = make_offering(c_eee, t_karim)
        o_te = make_offering(c_te, t_islam)

        # ---------------------------------------------------------- enrollments
        def enroll(student, offering):
            Enrollment.objects.get_or_create(student=student, course_offering=offering)

        cse_students = [students["s.rahman"], students["s.ahmed"], students["s.chowdhury"],
                        students["s.hossain"], students["s.uddin"]]
        for s in cse_students:
            enroll(s, o_ds)
            enroll(s, o_oop)
        enroll(students["s.kabir"], o_eee)
        enroll(students["s.mia"], o_eee)
        enroll(students["s.sultana"], o_te)

        # -------------------------------------------------------------- material
        material, _ = Material.objects.get_or_create(
            course_offering=o_ds,
            title="Lecture 4 — Linked Lists",
            defaults={"uploaded_by": t_hasan, "version": 1},
        )
        if not material.content_text:
            material.content_text = LECTURE_NOTES
        if not material.file.name or not material.file.storage.exists(material.file.name):
            material.file.save("linked_lists_lecture_4.txt", ContentFile(LECTURE_NOTES.encode("utf-8")))
            material.uploaded_by = t_hasan
            material.version = 1
            material.save()

        # -------------------------------------------------------------- questions
        def make_question(qtype, text, options=None, correct=None, source="manual",
                          status="approved", ref="", by=None):
            q, _ = Question.objects.get_or_create(
                course_offering=o_ds,
                type=qtype,
                text=text,
                defaults={
                    "options": options or [],
                    "correct_answer": correct if qtype == "mcq" else ref,
                    "source": source,
                    "status": status,
                    "approved_by": by,
                },
            )
            return q

        q1 = make_question(
            "mcq",
            "What is the head of a linked list?",
            ["The last node in the list", "A pointer referencing the first node",
             "A node with no data", "A pointer referencing the last node"],
            correct=1,
            by=t_hasan,
        )
        q2 = make_question(
            "mcq",
            "What is the time complexity of inserting a node at the beginning of a singly linked list?",
            ["O(n)", "O(log n)", "O(1)", "O(n log n)"],
            correct=2,
            by=t_hasan,
        )
        q3 = make_question(
            "mcq",
            "Why do linked lists use more memory per element than arrays?",
            ["They store duplicate data", "Each node stores an extra pointer",
             "They store index numbers", "They use a larger data type"],
            correct=1,
            by=t_hasan,
        )
        q4 = make_question(
            "mcq",
            "Which data structure is well suited to round-robin CPU scheduling?",
            ["Static array", "Singly linked list", "Circular linked list", "Hash table"],
            correct=2,
            by=t_hasan,
        )
        q5 = make_question(
            "cq",
            "Compare arrays and linked lists. When would you prefer a linked list over an array, and why?",
            ref="Arrays offer O(1) random access and cache locality; linked lists offer O(1) "
                "insertion/deletion at known positions and dynamic sizing. Prefer linked lists when "
                "the dominant operations are frequent insertions and deletions.",
            by=t_hasan,
        )
        q6 = make_question(
            "cq",
            "Explain how a queue can be implemented using a singly linked list, and state the "
            "time complexity of enqueue and dequeue.",
            ref="Keep a head and a tail pointer: enqueue appends at the tail and dequeue removes "
                "from the head, both in O(1) time.",
            by=t_hasan,
        )
        # A couple of unapproved AI drafts to show the review flow
        make_question(
            "mcq",
            "In a singly linked list, how is the end of the list detected?",
            ["The head pointer becomes null", "A node whose next pointer is null is reached",
             "The tail pointer equals the head", "The node count reaches capacity"],
            correct=1, source="ai_generated", status="draft",
        )
        make_question(
            "cq",
            "Explain how a doubly linked list differs from a singly linked list, and give one "
            "operation whose complexity improves as a result.",
            source="ai_generated", status="draft",
            ref="",
        )

        # ----------------------------------------------------------------- exam
        now = timezone.now()
        exam, _ = Exam.objects.get_or_create(
            course_offering=o_ds,
            title="Midterm 1 — Linked Lists",
            defaults={
                "total_duration_seconds": 300,
                "start_time": now - timedelta(minutes=10),
                "end_time": now + timedelta(days=7),
                "created_by": t_hasan,
            },
        )
        order = 0
        for question, limit, marks in [
            (q1, 20, 5), (q2, 20, 5), (q3, 20, 5), (q4, 20, 5), (q5, 60, 10), (q6, 60, 10),
        ]:
            order += 1
            ExamQuestion.objects.get_or_create(
                exam=exam,
                question=question,
                defaults={"order": order, "time_limit_seconds": limit, "marks": marks},
            )

        # ---------------------------------------------------------------- ratings
        rating_specs = [
            (students["s.rahman"], o_ds, 5, "Clear explanations and great examples in class."),
            (students["s.ahmed"], o_ds, 4, "Exams were well timed and fair."),
            (students["s.chowdhury"], o_ds, 4, "Materials were always available before class."),
            (students["s.hossain"], o_ds, 3, "Good course, would like more practice problems."),
            (students["s.kabir"], o_eee, 5, "Very supportive during office hours."),
            (students["s.mia"], o_eee, 4, "Quizzes helped a lot."),
        ]
        for student, offering, stars, comment in rating_specs:
            Rating.objects.get_or_create(
                course_offering=offering,
                student=student,
                defaults={"stars": stars, "comment": comment},
            )

        if settings.SEED_PASSWORD:
            self.stdout.write(self.style.SUCCESS(
                "Done. All seeded users use the SEED_PASSWORD you provided."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Done. Seeded account passwords:"))
            for username, pw in sorted(generated.items()):
                self.stdout.write(f"  {username:<16} {pw}")
            self.stdout.write(self.style.WARNING(
                "These passwords were generated once and are not stored anywhere — "
                "save them now if you need to log in as a seeded user."
            ))
