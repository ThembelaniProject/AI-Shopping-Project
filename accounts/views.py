from decimal import Decimal, InvalidOperation
import msal
import uuid
import re
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect

from .models import UserProfile


# ==========================================================
# LOGIN
# ==========================================================

def login_view(request):

    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    if request.method == "POST":

        email = request.POST.get(
            "email",
            ""
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        if not email or not password:

            messages.error(
                request,
                "Please enter your email and password."
            )

            return render(
                request,
                "accounts/login.html"
            )

        try:

            user = User.objects.get(
                email__iexact=email
            )

        except User.DoesNotExist:

            messages.error(
                request,
                "Invalid email or password."
            )

            return render(
                request,
                "accounts/login.html"
            )

        user = authenticate(
            request,
            username=user.username,
            password=password
        )

        if user is not None:

            login(
                request,
                user
            )

            return redirect(
                "shopping:dashboard"
            )

        messages.error(
            request,
            "Invalid email or password."
        )

    return render(
        request,
        "accounts/login.html"
    )


# ==========================================================
# REGISTER
# ==========================================================

def register_view(request):

    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":

        first_name = request.POST.get(
            "first_name",
            ""
        ).strip()

        last_name = request.POST.get(
            "last_name",
            ""
        ).strip()

        email = request.POST.get(
            "email",
            ""
        ).strip().lower()

        password = request.POST.get(
            "password",
            ""
        )

        confirm_password = request.POST.get(
            "confirm_password",
            ""
        )

        # --------------------------------------------------
        # POLICY ACCEPTANCE
        # --------------------------------------------------

        accept_policy = request.POST.get(
            "accept_policy"
        )

        if accept_policy != "on":

            messages.error(
                request,
                "You must accept the Privacy Policy and Terms & Conditions before creating your account."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # REQUIRED FIELDS
        # --------------------------------------------------

        if (
            not first_name
            or not last_name
            or not email
            or not password
        ):

            messages.error(
                request,
                "Please fill in all required fields."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # DUT STUDENT EMAIL VALIDATION
        # --------------------------------------------------

        dut_email_pattern = (
            r"^[0-9]{8}@dut4life\.ac\.za$"
        )

        if not re.match(
            dut_email_pattern,
            email,
            re.IGNORECASE
        ):

            messages.error(
                request,
                "Please use a valid DUT student email address."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # PASSWORD VALIDATION
        # --------------------------------------------------

        if len(password) < 8:

            messages.error(
                request,
                "Password must be at least 8 characters long."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # PASSWORD CONFIRMATION
        # --------------------------------------------------

        if password != confirm_password:

            messages.error(
                request,
                "Passwords do not match."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # CHECK EMAIL
        # --------------------------------------------------

        if User.objects.filter(
            email__iexact=email
        ).exists():

            messages.error(
                request,
                "An account with this email already exists."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # CHECK USERNAME
        # --------------------------------------------------

        if User.objects.filter(
            username=email
        ).exists():

            messages.error(
                request,
                "An account with this email already exists."
            )

            return render(
                request,
                "accounts/register.html"
            )

        # --------------------------------------------------
        # CREATE USER
        # --------------------------------------------------

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        # --------------------------------------------------
        # CREATE USER PROFILE
        # --------------------------------------------------

        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "available_amount": Decimal("1650.00"),
            },
        )

        # --------------------------------------------------
        # SUCCESS
        # --------------------------------------------------

        messages.success(
            request,
            "Account created successfully. Please log in."
        )

        return redirect(
            "accounts:login"
        )

    return render(
        request,
        "accounts/register.html"
    )


# ==========================================================
# PRIVACY POLICY
# ==========================================================

def privacy_policy(request):

    return render(
        request,
        "accounts/privacy_policy.html"
    )


# ==========================================================
# TERMS & CONDITIONS
# ==========================================================

def terms_conditions(request):

    return render(
        request,
        "accounts/terms_conditions.html"
    )


# ==========================================================
# MICROSOFT LOGIN
# ==========================================================


# ==========================================================
# PROFILE
# ==========================================================

@login_required
def profile(request):

    user = request.user

    user_profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "available_amount": Decimal("1650.00"),
        },
    )

    if user_profile.available_amount is None:

        user_profile.available_amount = Decimal("1650.00")

        user_profile.save(
            update_fields=["available_amount"]
        )

    # ------------------------------------------------------
    # Get saved location from session
    # ------------------------------------------------------

    latitude = request.session.get(
        "user_latitude"
    )

    longitude = request.session.get(
        "user_longitude"
    )

    address = request.session.get(
        "user_address"
    )

    # ------------------------------------------------------
    # Shopping budget
    # ------------------------------------------------------

    amount = user_profile.available_amount

    return render(
        request,
        "accounts/profile.html",
        {
            "user": user,
            "profile": user_profile,
            "profile_user": user,
            "user_latitude": latitude,
            "user_longitude": longitude,
            "user_address": address,
            "shopping_budget": amount,
        },
    )


# ==========================================================
# UPDATE USER LOCATION
# ==========================================================

@login_required
def update_location(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    latitude = request.POST.get(
        "latitude",
        ""
    ).strip()

    longitude = request.POST.get(
        "longitude",
        ""
    ).strip()

    if not latitude or not longitude:

        return JsonResponse(
            {
                "success": False,
                "error": "Latitude and longitude are required.",
            },
            status=400,
        )

    try:

        latitude_decimal = Decimal(latitude)

        longitude_decimal = Decimal(longitude)

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid latitude or longitude.",
            },
            status=400,
        )

    # ------------------------------------------------------
    # Validate latitude
    # ------------------------------------------------------

    if not (
        Decimal("-90")
        <= latitude_decimal
        <= Decimal("90")
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid latitude.",
            },
            status=400,
        )

    # ------------------------------------------------------
    # Validate longitude
    # ------------------------------------------------------

    if not (
        Decimal("-180")
        <= longitude_decimal
        <= Decimal("180")
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid longitude.",
            },
            status=400,
        )

    # ------------------------------------------------------
    # Save coordinates
    # ------------------------------------------------------

    request.session["user_latitude"] = str(
        latitude_decimal
    )

    request.session["user_longitude"] = str(
        longitude_decimal
    )

    # ------------------------------------------------------
    # Reverse geocode
    # ------------------------------------------------------

    address = (
        "Address could not be determined."
    )

    try:

        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": str(latitude_decimal),
                "lon": str(longitude_decimal),
                "format": "json",
                "addressdetails": 1,
            },
            headers={
                "User-Agent": "AI-Shopping-DUT/1.0"
            },
            timeout=10,
        )

        response.raise_for_status()

        location_data = response.json()

        address = location_data.get(
            "display_name",
            address
        )

    except (
        requests.RequestException,
        ValueError,
    ):

        pass

    # ------------------------------------------------------
    # Save address
    # ------------------------------------------------------

    request.session["user_address"] = address

    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "latitude": str(latitude_decimal),
            "longitude": str(longitude_decimal),
            "address": address,
        }
    )


# ==========================================================
# UPDATE SHOPPING BUDGET
# ==========================================================

@login_required
def update_budget(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    amount = request.POST.get(
        "amount",
        "",
    ).strip()

    try:

        amount_decimal = Decimal(amount)

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "Please enter a valid amount.",
            },
            status=400,
        )

    if amount_decimal < 0:

        return JsonResponse(
            {
                "success": False,
                "error": "Amount cannot be negative.",
            },
            status=400,
        )

    amount_decimal = amount_decimal.quantize(
        Decimal("0.01")
    )

    request.session["shopping_budget"] = str(
        amount_decimal
    )

    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "amount": str(amount_decimal),
        }
    )


# ==========================================================
# EDIT PROFILE
# ==========================================================

@login_required
def edit_profile(request):

    user = request.user

    if request.method == "POST":

        first_name = request.POST.get(
            "first_name",
            ""
        ).strip()

        last_name = request.POST.get(
            "last_name",
            ""
        ).strip()

        email = request.POST.get(
            "email",
            ""
        ).strip().lower()

        if (
            not first_name
            or not last_name
            or not email
        ):

            messages.error(
                request,
                "Please fill in all required fields."
            )

            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                }
            )

        # --------------------------------------------------
        # Check duplicate email
        # --------------------------------------------------

        email_exists = User.objects.filter(
            email__iexact=email
        ).exclude(
            pk=user.pk
        ).exists()

        if email_exists:

            messages.error(
                request,
                "An account with this email already exists."
            )

            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                }
            )

        # --------------------------------------------------
        # Update user
        # --------------------------------------------------

        old_email = user.email

        user.first_name = first_name

        user.last_name = last_name

        user.email = email

        # Keep username synchronized with email
        if user.username == old_email:

            user.username = email

        user.save()

        messages.success(
            request,
            "Your account details have been updated."
        )

        return redirect(
            "accounts:profile"
        )

    return render(
        request,
        "accounts/edit_profile.html",
        {
            "user": user,
        }
    )
