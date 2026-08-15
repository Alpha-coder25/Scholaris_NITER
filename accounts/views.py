import re

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from academics.models import Department
from .models import User

# Department short codes used in student IDs, e.g. "TE 2405038" = Textile
# Engineering, 2024 batch, serial 05038. CS=CSE · EE=EEE · TE=Textile ·
# FD=Fashion Design & Apparel · IP=Industrial & Production.
DEPT_CODE_TO_DEPT = {
    "CS": "Computer Science & Engineering",
    "EE": "Electrical & Electronic Engineering",
    "TE": "Textile Engineering",
    "FD": "Fashion Design & Apparel Engineering",
    "IP": "Industrial & Production Engineering",
}
STUDENT_ID_RE = re.compile(r"^(CS|EE|TE|FD|IP)\s?(\d{7})$")


def _role_home(user):
    if user.role == "admin":
        return "dashboard:admin_dashboard"
    if user.role == "teacher":
        return "dashboard:teacher_dashboard"
    return "dashboard:student_dashboard"


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_role_home(request.user))

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(_role_home(user))
        messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


def _department_code(department):
    """The 2-letter prefix for a department (CS/EE/TE/FD/IP)."""
    if not department:
        return ""
    short = (department.short_code or "").upper()
    # Normalise legacy codes (CSE->CS, EEE->EE, IPE->IP, FDAE->FD).
    return {
        "CSE": "CS", "EEE": "EE", "TE": "TE", "FD": "FD",
        "FDAE": "FD", "IPE": "IP", "IP": "IP", "CS": "CS", "EE": "EE",
    }.get(short, short[:2])


def signup_view(request):
    """Role-first registration: pick Teacher or Student, then fill the
    role-specific form. Teachers self-register here; admins can also create
    and manage both roles from /admin/."""
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    departments = Department.objects.all()
    if request.method == "POST":
        role = request.POST.get("role", "student").strip().lower()
        username = request.POST.get("username", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        department_id = request.POST.get("department")
        department = Department.objects.filter(pk=department_id).first()

        errors = []
        if role not in ("student", "teacher"):
            errors.append("Choose a valid role (Teacher or Student).")
        if len(first_name) > 150 or len(last_name) > 150:
            errors.append("Names must be at most 150 characters each.")
        if len(email) > 254:
            errors.append("Email must be at most 254 characters.")
        if len(password) > 128:
            errors.append("Password must be at most 128 characters.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if department is None:
            errors.append("Select a department.")

        # Username: required and unique.
        if not username:
            errors.append("Username is required.")
        if len(username) > 150:
            errors.append("Username must be at most 150 characters.")
        if username and User.objects.filter(username=username).exists():
            errors.append("That username is already taken.")

        if role == "student":
            student_id = request.POST.get("student_id_no", "").strip()
            batch = request.POST.get("batch", "").strip()
            section = request.POST.get("section", "").strip().upper()
            if len(student_id) > 20:
                errors.append("Student ID must be at most 20 characters.")
            if student_id:
                m = STUDENT_ID_RE.match(student_id) or STUDENT_ID_RE.match(student_id.replace(" ", ""))
                if not m:
                    errors.append(
                        "Student ID must look like the department code + year + serial, "
                        "e.g. TE 2405038 (TE = Textile Engineering)."
                    )
                else:
                    code = m.group(1)
                    expected = _department_code(department)
                    if expected and code != expected:
                        errors.append(
                            f"Student ID prefix {code} does not match the selected "
                            f"department ({department.name}, code {expected})."
                        )
                    if not batch:
                        # Derive batch from the ID year: "TE 2405038" -> 2024.
                        batch = f"20{m.group(2)[:2]}"
                if not errors and User.objects.filter(student_id_no=student_id).exists():
                    errors.append("That Student ID is already registered.")
            else:
                errors.append("Student ID is required for students.")
            if len(batch) > 10:
                errors.append("Batch must be at most 10 characters.")
            if not batch:
                errors.append("Batch (admission year) is required, e.g. 2024.")
            if len(section) > 10:
                errors.append("Section must be at most 10 characters.")
            if not section:
                errors.append("Section is required, e.g. A.")

        else:  # teacher
            employee_id = request.POST.get("employee_id", "").strip()
            if len(employee_id) > 20:
                errors.append("Employee ID must be at most 20 characters.")
            if not employee_id:
                errors.append("Employee ID is required for teachers.")
            if employee_id and User.objects.filter(employee_id=employee_id).exists():
                errors.append("That Employee ID is already registered.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            extra = {}
            if role == "student":
                extra = {
                    "student_id_no": student_id,
                    "batch": batch or f"20{STUDENT_ID_RE.match(student_id.replace(' ', '')).group(2)[:2]}",
                    "section": section,
                }
            else:
                extra = {"employee_id": employee_id}
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=role,
                department=department,
                **extra,
            )
            login(request, user)
            messages.success(request, f"Welcome to Scholaris, {user.first_name or user.username}!")
            return redirect("dashboard:home")

        # Preserve what the user typed so they don't retype everything.
        context = {
            "departments": departments,
            "role": role,
            "values": {
                "username": username, "first_name": first_name, "last_name": last_name,
                "email": email, "department": department_id,
                "student_id_no": request.POST.get("student_id_no", "").strip(),
                "employee_id": request.POST.get("employee_id", "").strip(),
                "batch": request.POST.get("batch", "").strip(),
                "section": request.POST.get("section", "").strip().upper(),
            },
        }
        return render(request, "accounts/signup.html", context)

    return render(request, "accounts/signup.html", {"departments": departments})


# ---------------------------------------------------------------------------
# Admin: manage teachers & students (add / read / update)
# ---------------------------------------------------------------------------
@role_required("admin")
def admin_user_list(request):
    """Directory of all teachers & students, filterable by role/department."""
    role_filter = request.GET.get("role", "")
    dept_filter = request.GET.get("department", "")

    users = User.objects.filter(role__in=["teacher", "student"]).select_related("department")
    if role_filter in ("teacher", "student"):
        users = users.filter(role=role_filter)
    if dept_filter:
        users = users.filter(department_id=dept_filter)
    users = users.order_by("role", "first_name", "username")

    return render(
        request,
        "admin/users.html",
        {
            "users": users,
            "departments": Department.objects.all(),
            "role_filter": role_filter,
            "dept_filter": dept_filter,
        },
    )


@role_required("admin")
def admin_user_add(request):
    if request.method == "POST":
        role = request.POST.get("role", "student").strip().lower()
        username = request.POST.get("username", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        department_id = request.POST.get("department")
        department = Department.objects.filter(pk=department_id).first()

        errors = []
        if role not in ("student", "teacher"):
            errors.append("Choose a valid role.")
        if not username:
            errors.append("Username is required.")
        if username and User.objects.filter(username=username).exists():
            errors.append("That username is already taken.")
        if department is None:
            errors.append("Select a department.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")

        if role == "student":
            student_id = request.POST.get("student_id_no", "").strip()
            batch = request.POST.get("batch", "").strip()
            section = request.POST.get("section", "").strip().upper()
            if student_id:
                m = STUDENT_ID_RE.match(student_id) or STUDENT_ID_RE.match(student_id.replace(" ", ""))
                if not m:
                    errors.append("Student ID must look like TE 2405038 (dept code + 7 digits).")
                else:
                    code = m.group(1)
                    expected = _department_code(department)
                    if expected and code != expected:
                        errors.append(f"Student ID prefix {code} does not match {department.name} (code {expected}).")
                    if not batch:
                        batch = f"20{m.group(2)[:2]}"
                if not errors and User.objects.filter(student_id_no=student_id).exists():
                    errors.append("That Student ID is already registered.")
            else:
                errors.append("Student ID is required.")
            if not batch:
                errors.append("Batch is required.")
            if not section:
                errors.append("Section is required.")
        else:
            employee_id = request.POST.get("employee_id", "").strip()
            if not employee_id:
                errors.append("Employee ID is required.")
            if employee_id and User.objects.filter(employee_id=employee_id).exists():
                errors.append("That Employee ID is already registered.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            extra = {}
            if role == "student":
                extra = {"student_id_no": student_id, "batch": batch, "section": section}
            else:
                extra = {"employee_id": employee_id}
            User.objects.create_user(
                username=username, password=password, email=email,
                first_name=first_name, last_name=last_name,
                role=role, department=department, **extra,
            )
            messages.success(request, f"{role.title()} “{username}” created.")
            return redirect("accounts:admin_users")

    return render(request, "admin/user_form.html", {
        "departments": Department.objects.all(),
        "editing": False,
    })


@role_required("admin")
def admin_user_edit(request, user_id):
    user = get_object_or_404(User, pk=user_id, role__in=["teacher", "student"])

    if request.method == "POST":
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.email = request.POST.get("email", "").strip()
        dept_id = request.POST.get("department")
        user.department = Department.objects.filter(pk=dept_id).first() if dept_id else None
        if user.role == "student":
            user.student_id_no = request.POST.get("student_id_no", "").strip()
            user.batch = request.POST.get("batch", "").strip()
            user.section = request.POST.get("section", "").strip().upper()
        else:
            user.employee_id = request.POST.get("employee_id", "").strip()
        password = request.POST.get("password", "")
        if password:
            if len(password) < 6:
                messages.error(request, "New password must be at least 6 characters.")
            else:
                user.set_password(password)
                messages.success(request, f"Password updated for {user.username}.")
        user.save()
        messages.success(request, f"{user.get_full_name() or user.username} updated.")
        return redirect("accounts:admin_users")

    return render(request, "admin/user_form.html", {
        "departments": Department.objects.all(),
        "editing": user,
    })


@role_required("admin")
def admin_students_by_cohort(request):
    """Student list grouped by year (batch) → department → section."""
    students = (
        User.objects.filter(role="student")
        .select_related("department")
        .order_by("-batch", "department__short_code", "section", "first_name", "last_name")
    )
    # Group: year -> department name -> section -> students
    cohorts = {}
    for s in students:
        year = s.batch or "—"
        dept = s.department.name if s.department else "—"
        sec = s.section or "—"
        cohorts.setdefault(year, {}).setdefault(dept, {}).setdefault(sec, []).append(s)
    return render(request, "admin/students.html", {"cohorts": cohorts})
