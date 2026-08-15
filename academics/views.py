from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required

from .models import Course, CourseOffering, Department, Enrollment, Semester

User = get_user_model()


@role_required("admin")
def course_offering_list(request):
    """Admin: create a course offering (assign teacher → course → semester)
    and see all existing assignments."""
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .prefetch_related("enrollments")
        .order_by("-semester__start_date", "course__code")
    )

    if request.method == "POST":
        course = get_object_or_404(Course, pk=request.POST.get("course"))
        semester = get_object_or_404(Semester, pk=request.POST.get("semester"))
        teacher_id = request.POST.get("teacher")
        section = request.POST.get("section", "A").strip() or "A"
        teacher = get_object_or_404(User, pk=teacher_id, role="teacher")
        try:
            CourseOffering.objects.create(
                course=course, semester=semester, teacher=teacher, section=section
            )
            messages.success(
                request,
                f"Assigned {course.code} to {teacher.get_full_name() or teacher.username} "
                f"({semester.name}, Section {section}).",
            )
        except IntegrityError:
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


@role_required("student")
def enroll(request):
    """Student: browse open offerings and enrol."""
    student = request.user
    enrolled_ids = set(
        student.enrollments.values_list("course_offering_id", flat=True)
    )
    offerings = (
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .order_by("-semester__start_date", "course__code")
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
