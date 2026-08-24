from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required

from .models import Course, CourseOffering, Department, Enrollment, Semester

User = get_user_model()


@role_required("admin")
def syllabus(request):
    """Admin: manage a department's semester syllabus — add / update / delete
    the courses listed for that department & semester."""
    departments = Department.objects.all()
    semesters = Semester.objects.all()

    dept_id = request.GET.get("department") or request.POST.get("department")
    sem_id = request.GET.get("semester") or request.POST.get("semester")
    department = Department.objects.filter(pk=dept_id).first()
    semester = Semester.objects.filter(pk=sem_id).first()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            code = request.POST.get("code", "").strip().upper()
            title = request.POST.get("title", "").strip()
            credits = request.POST.get("credit_hours", "")
            if not department or not semester:
                messages.error(request, "Choose a department and semester first.")
            elif not code:
                messages.error(request, "Course code is required.")
            elif not title:
                messages.error(request, "Course title is required.")
            elif len(code) > 20:
                messages.error(request, "Course code must be at most 20 characters.")
            elif len(title) > 200:
                messages.error(request, "Course title must be at most 200 characters.")
            else:
                try:
                    credits = int(credits)
                    if credits <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    messages.error(request, "Credit hours must be a positive number.")
                else:
                    if Course.objects.filter(
                        department=department, semester=semester, code=code
                    ).exists():
                        messages.error(request, f"{code} already exists in {semester.name}.")
                    else:
                        Course.objects.create(
                            department=department, semester=semester,
                            code=code, title=title, credit_hours=credits,
                        )
                        messages.success(request, f"Added {code} — {title} to the syllabus.")

        elif action == "delete":
            course = get_object_or_404(Course, pk=request.POST.get("course_id"))
            try:
                with transaction.atomic():
                    course.delete()
                messages.success(request, f"Deleted {course.code} from the syllabus.")
            except ProtectedError:
                messages.error(
                    request,
                    f"Cannot delete {course.code} — it is assigned to a course offering "
                    "(or has exams/materials). Remove those assignments first.",
                )

        elif action == "update":
            course = get_object_or_404(Course, pk=request.POST.get("course_id"))
            code = request.POST.get("code", "").strip().upper()
            title = request.POST.get("title", "").strip()
            credits = request.POST.get("credit_hours", "")
            if not code:
                messages.error(request, "Course code is required.")
            elif not title:
                messages.error(request, "Course title is required.")
            else:
                try:
                    credits = int(credits)
                    if credits <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    messages.error(request, "Credit hours must be a positive number.")
                else:
                    dup = Course.objects.filter(
                        department=course.department, semester=course.semester, code=code
                    ).exclude(pk=course.pk)
                    if dup.exists():
                        messages.error(request, f"{code} already exists in this semester's syllabus.")
                    else:
                        course.code = code
                        course.title = title
                        course.credit_hours = credits
                        course.save()
                        messages.success(request, f"Updated {course.code}.")

        return redirect(
            f"/admin/syllabus/?department={dept_id or ''}&semester={sem_id or ''}"
        )

    courses = Course.objects.none()
    if department and semester:
        courses = (
            Course.objects.filter(department=department, semester=semester)
            .order_by("code")
        )

    return render(
        request,
        "admin/syllabus.html",
        {
            "departments": departments,
            "semesters": semesters,
            "department": department,
            "semester": semester,
            "courses": courses,
        },
    )


@role_required("admin")
def course_offering_list(request):
    """Admin: create a course offering (assign teacher → course → semester)
    and see all existing assignments."""
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .prefetch_related("enrollments")
        .order_by("semester__number", "course__code")
    )

    if request.method == "POST":
        course = get_object_or_404(Course, pk=request.POST.get("course"))
        semester = get_object_or_404(Semester, pk=request.POST.get("semester"))
        teacher_id = request.POST.get("teacher")
        section = request.POST.get("section", "A").strip() or "A"
        teacher = get_object_or_404(User, pk=teacher_id, role="teacher")
        try:
            with transaction.atomic():
                CourseOffering.objects.create(
                    course=course, semester=semester, teacher=teacher, section=section
                )
            messages.success(
                request,
                f"Assigned {course.code} to {teacher.get_full_name() or teacher.username} "
                f"({semester.name}, Section {section}).",
            )
        except IntegrityError:
            # Savepoint inside atomic() lets the duplicate be rejected without
            # poisoning the surrounding transaction.
            messages.error(
                request,
                f"{course.code} Section {section} already exists for {semester.name}.",
            )
        return redirect("academics:course_offerings")

    teachers = (
        User.objects.filter(role="teacher", is_active=True)
        .order_by("first_name", "username")
    )
    context = {
        "offerings": offerings,
        "departments": Department.objects.prefetch_related("courses"),
        "semesters": Semester.objects.all(),
        "teachers": teachers,
    }
    return render(request, "admin/course_offerings.html", context)


@role_required("admin")
def admin_enroll_students(request):
    """Admin: enroll students (individually or by batch/group) into a course
    offering.  Supports filtering by department, batch, and section to bulk-
    assign an entire cohort."""
    departments = Department.objects.all()
    semesters = Semester.objects.all()
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .order_by("semester__number", "course__code")
    )

    # --- Filters (persisted via GET so the form survives POST → redirect) ---
    filter_dept = request.GET.get("filter_dept") or request.POST.get("filter_dept")
    filter_batch = request.GET.get("filter_batch") or request.POST.get("filter_batch")
    filter_section = request.GET.get("filter_section") or request.POST.get("filter_section")
    filter_offering = request.GET.get("filter_offering") or request.POST.get("filter_offering")

    selected_offering = CourseOffering.objects.filter(pk=filter_offering).select_related(
        "course", "semester", "teacher"
    ).first() if filter_offering else None

    # All distinct batch values (sorted descending — newest first)
    all_batches = (
        User.objects.filter(role="student")
        .values_list("batch", flat=True)
        .distinct()
        .order_by("-batch")
    )
    all_sections = (
        User.objects.filter(role="student")
        .values_list("section", flat=True)
        .distinct()
        .order_by("section")
    )

    # Build student queryset with filters
    students_qs = (
        User.objects.filter(role="student", is_active=True)
        .select_related("department")
        .order_by("batch", "department__name", "last_name", "first_name")
    )
    if filter_dept:
        students_qs = students_qs.filter(department_id=filter_dept)
    if filter_batch:
        students_qs = students_qs.filter(batch=filter_batch)
    if filter_section:
        students_qs = students_qs.filter(section=filter_section)

    # If an offering is selected, annotate with enrollment status
    enrolled_student_ids = set()
    if selected_offering:
        enrolled_student_ids = set(
            Enrollment.objects.filter(course_offering=selected_offering)
            .values_list("student_id", flat=True)
        )

    students = []
    for s in students_qs:
        students.append({
            "student": s,
            "already_enrolled": s.pk in enrolled_student_ids,
        })

    # --- Handle POST actions ---
    if request.method == "POST":
        action = request.POST.get("action")
        offering_id = request.POST.get("offering")
        if not offering_id:
            messages.error(request, "Select a course offering first.")
            return redirect("academics:admin_enroll_students")

        offering = get_object_or_404(
            CourseOffering.objects.select_related("course", "semester"),
            pk=offering_id,
        )

        if action == "enroll_selected":
            # Individual checkboxes
            student_ids = [
                int(sid)
                for sid in request.POST.getlist("student_ids")
                if sid.isdigit()
            ]
            if not student_ids:
                messages.error(request, "No students selected.")
                return redirect(
                    f"/admin/enroll-students/?filter_dept={filter_dept or ''}"
                    f"&filter_batch={filter_batch or ''}"
                    f"&filter_section={filter_section or ''}"
                    f"&filter_offering={offering_id}"
                )
            count = 0
            skipped = 0
            for sid in student_ids:
                _, created = Enrollment.objects.get_or_create(
                    student_id=sid, course_offering=offering
                )
                if created:
                    count += 1
                else:
                    skipped += 1
            msg = f"Enrolled {count} student(s) into {offering.course.code}."
            if skipped:
                msg += f" {skipped} already enrolled (skipped)."
            messages.success(request, msg)

        elif action == "enroll_all":
            # Enroll ALL filtered students in a single bulk operation
            if not students:
                messages.error(request, "No students match the current filters.")
                return redirect(
                    f"/admin/enroll-students/?filter_dept={filter_dept or ''}"
                    f"&filter_batch={filter_batch or ''}"
                    f"&filter_section={filter_section or ''}"
                    f"&filter_offering={offering_id}"
                )
            # Collect student IDs that are not yet enrolled
            new_student_ids = [
                entry["student"].pk for entry in students
                if not entry["already_enrolled"]
            ]
            skipped = len(students) - len(new_student_ids)
            if new_student_ids:
                new_enrollments = [
                    Enrollment(student_id=sid, course_offering=offering)
                    for sid in new_student_ids
                ]
                Enrollment.objects.bulk_create(new_enrollments, ignore_conflicts=True)
            count = len(new_student_ids)
            msg = f"Batch-enrolled {count} student(s) into {offering.course.code}."
            if skipped:
                msg += f" {skipped} already enrolled (skipped)."
            messages.success(request, msg)

        elif action == "unenroll_selected":
            student_ids = [
                int(sid)
                for sid in request.POST.getlist("student_ids")
                if sid.isdigit()
            ]
            if not student_ids:
                messages.error(request, "No students selected.")
            else:
                deleted, _ = Enrollment.objects.filter(
                    student_id__in=student_ids, course_offering=offering
                ).delete()
                messages.success(request, f"Removed {deleted} student(s) from {offering.course.code}.")

        return redirect(
            f"/admin/enroll-students/?filter_dept={filter_dept or ''}"
            f"&filter_batch={filter_batch or ''}"
            f"&filter_section={filter_section or ''}"
            f"&filter_offering={offering_id}"
        )

    context = {
        "departments": departments,
        "semesters": semesters,
        "offerings": offerings,
        "selected_offering": selected_offering,
        "students": students,
        "filter_dept": filter_dept or "",
        "filter_batch": filter_batch or "",
        "filter_section": filter_section or "",
        "all_batches": all_batches,
        "all_sections": all_sections,
    }
    return render(request, "admin/enroll_students.html", context)


@role_required("student")
def enroll(request):
    """Student: browse open offerings and enrol."""
    student = request.user
    enrolled_ids = set(
        student.enrollments.values_list("course_offering_id", flat=True)
    )
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .order_by("semester__number", "course__code")
    )

    if request.method == "POST":
        offering = get_object_or_404(CourseOffering, pk=request.POST.get("offering"))
        if offering.pk in enrolled_ids:
            messages.info(request, "You're already enrolled in that course.")
        else:
            Enrollment.objects.create(student=student, course_offering=offering)
            messages.success(
                request, f"Enrolled in {offering.display_name}. Welcome aboard!"
            )
        return redirect("academics:enroll")

    context = {
        "offerings": offerings,
        "enrolled_ids": enrolled_ids,
    }
    return render(request, "student/enroll.html", context)
