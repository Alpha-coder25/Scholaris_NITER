from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render

from academics.models import Department
from .models import User


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    # One-click demo login: /accounts/login/?demo=<username> fills the form
    # with the seeded demo credentials and submits it.
    demo_username = request.GET.get("demo")
    is_demo = False
    if demo_username:
        for demo in settings.DEMO_LOGINS:
            if demo["username"] == demo_username:
                request.POST = request.POST.copy()
                request.POST["username"] = demo["username"]
                request.POST["password"] = demo["password"]
                is_demo = True
                break

    if request.method == "POST" or is_demo:
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("dashboard:home")
        messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


def signup_view(request):
    """Student self-registration. Teachers/admins are created by the institution."""
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        department_id = request.POST.get("department")
        student_id = request.POST.get("student_id_no", "").strip()

        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if User.objects.filter(username=username).exists():
            errors.append("That username is already taken.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            department = Department.objects.filter(pk=department_id).first()
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role="student",
                department=department,
                student_id_no=student_id,
            )
            login(request, user)
            messages.success(request, f"Welcome to Scholaris, {user.first_name or user.username}!")
            return redirect("dashboard:home")

    return render(request, "accounts/signup.html", {"departments": Department.objects.all()})
