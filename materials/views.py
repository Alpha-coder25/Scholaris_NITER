from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from academics.models import CourseOffering
from accounts.decorators import role_required
from ai_integration.services import (
    create_draft_questions,
    extract_text,
    generate_questions,
    generation_source_label,
)

from .models import Material


@role_required("teacher")
def upload(request, offering_id):
    """Teacher: upload a lecture material (re-uploads bump the version)."""
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course", "semester"),
        pk=offering_id,
        teacher=request.user,
    )

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        file = request.FILES.get("file")
        if not title or not file:
            messages.error(request, "Provide both a title and a file.")
            return redirect("materials:upload", offering_id=offering.pk)

        # Extract text first, then seek back so Django can still save the file
        content_text = extract_text(file)
        file.seek(0)

        last_version = (
            offering.materials.filter(title=title).order_by("-version").first()
        )
        version = (last_version.version + 1) if last_version else 1
        material = Material.objects.create(
            course_offering=offering,
            uploaded_by=request.user,
            title=title,
            file=file,
            version=version,
            content_text=content_text,
        )
        messages.success(
            request,
            f"Uploaded “{material.title}” (v{version}). "
            f"Now generate draft questions from it.",
        )
        return redirect("materials:upload", offering_id=offering.pk)

    return render(
        request,
        "teacher/material_upload.html",
        {"offering": offering, "materials": offering.materials.all()},
    )


@role_required("teacher")
def generate_questions_from_material(request, offering_id, material_id):
    """Teacher: trigger AI question generation for one material.

    Runs synchronously in the hackathon build (the service layer is the same
    one a Celery task would call in production). Drafts are created with
    source='ai_generated' and status='draft' — students never see them until
    the teacher approves.
    """
    offering = get_object_or_404(
        CourseOffering, pk=offering_id, teacher=request.user
    )
    material = get_object_or_404(
        Material, pk=material_id, course_offering=offering
    )

    drafts, used_ai = generate_questions(material)
    created = create_draft_questions(offering, drafts)

    messages.success(
        request,
        f"{len(created)} draft questions generated from “{material.title}” "
        f"via {generation_source_label(used_ai)}. Review and approve them below — "
        f"nothing is shown to students until you approve.",
    )
    return redirect("exams:question_review", offering_id=offering.pk)
