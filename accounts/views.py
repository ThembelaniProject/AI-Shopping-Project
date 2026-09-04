from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect

def login_view(request):
    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        if not email or not password:
            messages.error(request, "Please enter your email and password.")
            return render(request, "accounts/login.html")

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            messages.error(request, "Invalid email or password.")
            return render(request, "accounts/login.html")

        user = authenticate(
            request,
            username=user.username,
            password=password
        )

        if user is not None:
            login(request, user)
            return redirect("shopping:dashboard")

        messages.error(request, "Invalid email or password.")

    return render(request, "accounts/login.html")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not email or not password:
            messages.error(request, "Please fill in all required fields.")
            return render(request, "accounts/register.html")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "accounts/register.html")

        if User.objects.filter(username=email).exists():
            messages.error(
                request,
                "An account with this email already exists."
            )
            return render(request, "accounts/register.html")

        User.objects.create_user(
            username=email,
            email=email,
            password=password,
        )

        messages.success(
            request,
            "Account created successfully. Please log in."
        )

        return redirect("accounts:login")

    return render(request, "accounts/register.html")