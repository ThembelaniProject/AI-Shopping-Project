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



def microsoft_login(request):


    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    if not settings.MICROSOFT_CLIENT_ID:
        messages.error(
            request,
            "Microsoft login is not configured yet."
        )
        return redirect("accounts:login")

    if not settings.MICROSOFT_CLIENT_SECRET:
        messages.error(
            request,
            "Microsoft login is not configured yet."
        )
        return redirect("accounts:login")

    msal_app = msal.ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=settings.MICROSOFT_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )

    state = str(uuid.uuid4())

    request.session["microsoft_auth_state"] = state

    authorization_url = msal_app.get_authorization_request_url(
        scopes=settings.MICROSOFT_SCOPE,
        state=state,
        redirect_uri=settings.MICROSOFT_REDIRECT_URI,
    )

    return redirect(authorization_url)


def microsoft_callback(request):

    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    error = request.GET.get("error")

    if error:
        error_description = request.GET.get(
            "error_description",
            "Microsoft login was cancelled or failed."
        )

        messages.error(
            request,
            error_description
        )

        return redirect("accounts:login")

    state = request.GET.get("state")

    saved_state = request.session.get(
        "microsoft_auth_state"
    )

    if not state or state != saved_state:
        messages.error(
            request,
            "Invalid Microsoft login session."
        )

        return redirect("accounts:login")

    # State is no longer needed.
    request.session.pop(
        "microsoft_auth_state",
        None
    )

    authorization_code = request.GET.get("code")

    if not authorization_code:
        messages.error(
            request,
            "Microsoft did not return an authorization code."
        )

        return redirect("accounts:login")

    msal_app = msal.ConfidentialClientApplication(
        settings.MICROSOFT_CLIENT_ID,
        authority=settings.MICROSOFT_AUTHORITY,
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )

    result = msal_app.acquire_token_by_authorization_code(
        authorization_code,
        scopes=settings.MICROSOFT_SCOPE,
        redirect_uri=settings.MICROSOFT_REDIRECT_URI,
    )

    if "error" in result:
        messages.error(
            request,
            "Microsoft authentication failed."
        )

        return redirect("accounts:login")

    claims = result.get("id_token_claims", {})

    # ------------------------------------------------------
    # Verify DUT tenant
    # ------------------------------------------------------

    tenant_id = claims.get("tid")

    if tenant_id != settings.MICROSOFT_TENANT_ID:

        messages.error(
            request,
            "Only DUT Microsoft accounts are allowed."
        )

        return redirect("accounts:login")

    # ------------------------------------------------------
    # Get email
    # ------------------------------------------------------

    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or ""
    ).strip().lower()

    if not email:

        messages.error(
            request,
            "Microsoft did not provide an email address."
        )

        return redirect("accounts:login")

    # ------------------------------------------------------
    # Verify DUT email domain
    # ------------------------------------------------------

    if not email.endswith("@dut4life.ac.za"):

        messages.error(
            request,
            "Only DUT student Microsoft accounts are allowed."
        )

        return redirect("accounts:login")

    # ------------------------------------------------------
    # Get user's name
    # ------------------------------------------------------

    first_name = (
        claims.get("given_name")
        or ""
    ).strip()

    last_name = (
        claims.get("family_name")
        or ""
    ).strip()

    full_name = (
        claims.get("name")
        or ""
    ).strip()

    # ------------------------------------------------------
    # Find or create Django user
    # ------------------------------------------------------

    user = User.objects.filter(
        email__iexact=email
    ).first()

    if user is None:

        username = email

        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        # Disable password login for this
        # Microsoft-created account.
        user.set_unusable_password()

        user.save()

    else:

        changed = False

        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True

        if last_name and user.last_name != last_name:
            user.last_name = last_name
            changed = True

        if changed:
            user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                ]
            )

    # ------------------------------------------------------
    # Login Django user
    # ------------------------------------------------------

    login(
        request,
        user,
        backend="django.contrib.auth.backends.ModelBackend",
    )

    messages.success(
        request,
        "Welcome to AI Shopping!"
    )

    return redirect(
        "shopping:dashboard"
    )


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

    latitude = request.POST.get("latitude", "").strip()
    longitude = request.POST.get("longitude", "").strip()

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
    # Validate coordinates
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
    # Save to session
    # ------------------------------------------------------

    request.session["user_latitude"] = str(
        latitude_decimal
    )

    request.session["user_longitude"] = str(
        longitude_decimal
    )

    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "latitude": str(latitude_decimal),
            "longitude": str(longitude_decimal),
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