from decimal import Decimal, InvalidOperation
import msal
import uuid
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
import requests



from .models import UserProfile
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
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        confirm_password = request.POST.get(
            "confirm_password",
            ""
        )

        if not first_name or not last_name or not email or not password:
            messages.error(
                request,
                "Please fill in all required fields."
            )
            return render(
                request,
                "accounts/register.html"
            )

        if password != confirm_password:
            messages.error(
                request,
                "Passwords do not match."
            )
            return render(
                request,
                "accounts/register.html"
            )

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

        User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

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
# MICROSOFT LOGIN
# ==========================================================


    

   



# ==========================================================
# PROFILE
# ==========================================================

@login_required
def profile(request):

    user = request.user

    # Get the user's profile.
    # If the profile does not exist, create it automatically
    # with a starting budget of R1650.00.
    user_profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "available_amount": Decimal("1650.00"),
        },
    )

    # Make sure an existing profile with no budget
    # also receives the default R1650.00.
    if user_profile.available_amount is None:
        user_profile.available_amount = Decimal("1650.00")
        user_profile.save(update_fields=["available_amount"])

    # Get saved location from the session.
    latitude = request.session.get("user_latitude")
    longitude = request.session.get("user_longitude")
    address = request.session.get(
    "user_address"
)

    # Display the user's saved database budget.
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

    # Validate latitude

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

    # Validate longitude

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
    # Save coordinates to session
    # ------------------------------------------------------

    request.session["user_latitude"] = str(
        latitude_decimal
    )

    request.session["user_longitude"] = str(
        longitude_decimal
    )

    # ------------------------------------------------------
    # Reverse geocode coordinates
    # ------------------------------------------------------

    address = "Address could not be determined."

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

        # Keep the coordinates even if
        # address lookup fails.
        pass

    # ------------------------------------------------------
    # Save address to session
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

        if not first_name or not last_name or not email:

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

        # Check whether another account already
        # uses this email address.
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

        user.first_name = first_name
        user.last_name = last_name
        user.email = email

        # Keep username in sync for accounts created
        # through your normal registration system.
        #
        # This is especially useful because your normal
        # registration currently uses the email as username.
        if user.username == request.user.email:
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
