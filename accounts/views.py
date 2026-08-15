from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render


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
