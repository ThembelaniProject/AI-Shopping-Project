
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
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from .models import UserProfile
from preferences.models import Preference
from shopping.models import PurchaseHistory


# ==========================================================
# CONSTANTS
# ==========================================================

DUT_EMAIL_PATTERN = r"^[0-9]{8}@dut4life\.ac\.za$"

DEFAULT_AVAILABLE_AMOUNT = Decimal("1650.00")


# ==========================================================
# LOGIN
# ==========================================================

def login_view(request):

    # ------------------------------------------------------
    # Already logged in
    # ------------------------------------------------------

    if request.user.is_authenticated:

        return redirect_after_login(
            request.user
        )

    # ------------------------------------------------------
    # Normal email/password login
    # ------------------------------------------------------

    if request.method == "POST":

        email = request.POST.get(
            "email",
            ""
        ).strip().lower()

        password = request.POST.get(
            "password",
            ""
        )

        # --------------------------------------------------
        # Validate fields
        # --------------------------------------------------

        if not email or not password:

            messages.error(
                request,
                "Please enter your email and password."
            )

            return render(
                request,
                "accounts/login.html"
            )

        # --------------------------------------------------
        # Find user
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Authenticate
        # --------------------------------------------------

        authenticated_user = authenticate(
            request,
            username=user.username,
            password=password
        )

        if authenticated_user is not None:

            login(
                request,
                authenticated_user
            )

            return redirect_after_login(
                authenticated_user
            )

        # --------------------------------------------------
        # Invalid password
        # --------------------------------------------------

        messages.error(
            request,
            "Invalid email or password."
        )

    return render(
        request,
        "accounts/login.html"
    )


# ==========================================================
# POST-LOGIN REDIRECT
# ==========================================================

def redirect_after_login(user):
    """
    Decide where the authenticated user should go.

    New user / empty preferences:
        preferences:edit

    Existing user with preferences:
        shopping:dashboard
    """

    # ------------------------------------------------------
    # Find preferences
    # ------------------------------------------------------

    preference = Preference.objects.filter(
        user=user
    ).first()

    # ------------------------------------------------------
    # No preference record
    # ------------------------------------------------------

    if preference is None:

        print(
            f"[LOGIN REDIRECT] {user.email}: "
            "No Preference record -> preferences"
        )

        return redirect(
            "preferences:edit"
        )

    # ------------------------------------------------------
    # Safely get preference values
    # ------------------------------------------------------

    styles = preference.styles or []
    colours = preference.colours or []
    stores = preference.stores or []
    hobbies = preference.hobbies or []

    # ------------------------------------------------------
    # Check if anything has been selected
    # ------------------------------------------------------

    has_preferences = any([
        bool(styles),
        bool(colours),
        bool(stores),
        bool(hobbies),
    ])

    # ------------------------------------------------------
    # Empty preferences
    # ------------------------------------------------------

    if not has_preferences:

        print(
            f"[LOGIN REDIRECT] {user.email}: "
            "Preferences empty -> preferences"
        )

        return redirect(
            "preferences:edit"
        )

    # ------------------------------------------------------
    # Existing user with preferences
    # ------------------------------------------------------

    print(
        f"[LOGIN REDIRECT] {user.email}: "
        "Preferences found -> dashboard"
    )

    return redirect(
        "shopping:dashboard"
    )


# ==========================================================
# REGISTER
# ==========================================================

def register_view(request):

    # ------------------------------------------------------
    # Already logged in
    # ------------------------------------------------------

    if request.user.is_authenticated:

        return redirect_after_login(
            request.user
        )

    # ------------------------------------------------------
    # Registration
    # ------------------------------------------------------

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
                "You must accept the Privacy Policy and "
                "Terms & Conditions before creating your account."
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
        # DUT EMAIL VALIDATION
        # --------------------------------------------------

        if not re.match(
            DUT_EMAIL_PATTERN,
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
                "available_amount":
                    DEFAULT_AVAILABLE_AMOUNT,
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
    
    
@login_required
def accept_terms(request):
    """
    Display and process the terms acceptance page.
    """

    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "available_amount": DEFAULT_AVAILABLE_AMOUNT,
        }
    )

    if request.method == "POST":
        profile.terms_accepted = True
        profile.terms_accepted_at = timezone.now()
        profile.save(
            update_fields=[
                "terms_accepted",
                "terms_accepted_at",
            ]
        )

        messages.success(
            request,
            "Terms and conditions accepted successfully."
        )

        return redirect("shopping:dashboard")

    return render(
        request,
        "accounts/accept_terms.html",
        {
            "profile": profile,
        }
    )

# ==========================================================
# MICROSOFT LOGIN
# ==========================================================

def microsoft_login(request):
    """
    Start Microsoft OAuth login.

    User clicks:

        Continue with DUT Microsoft

    Django redirects to Microsoft.

    Microsoft then redirects to:

        microsoft_callback()
    """

    # ------------------------------------------------------
    # Already logged in
    # ------------------------------------------------------

    if request.user.is_authenticated:

        return redirect_after_login(
            request.user
        )

    # ------------------------------------------------------
    # Check Microsoft configuration
    # ------------------------------------------------------

    client_id = getattr(
        settings,
        "MICROSOFT_CLIENT_ID",
        ""
    )

    client_secret = getattr(
        settings,
        "MICROSOFT_CLIENT_SECRET",
        ""
    )

    redirect_uri = getattr(
        settings,
        "MICROSOFT_REDIRECT_URI",
        ""
    )

    authority = getattr(
        settings,
        "MICROSOFT_AUTHORITY",
        ""
    )

    scopes = getattr(
        settings,
        "MICROSOFT_SCOPE",
        ["User.Read"]
    )

    # ------------------------------------------------------
    # Validate configuration
    # ------------------------------------------------------

    if not client_id:

        messages.error(
            request,
            "Microsoft login is not configured."
        )

        return redirect(
            "accounts:login"
        )

    if not client_secret:

        messages.error(
            request,
            "Microsoft login is not configured."
        )

        return redirect(
            "accounts:login"
        )

    if not redirect_uri:

        messages.error(
            request,
            "Microsoft redirect URI is not configured."
        )

        return redirect(
            "accounts:login"
        )

    if not authority:

        messages.error(
            request,
            "Microsoft authority is not configured."
        )

        return redirect(
            "accounts:login"
        )

    # ------------------------------------------------------
    # Create MSAL application
    # ------------------------------------------------------

    msal_app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential=client_secret,
    )

    # ------------------------------------------------------
    # Generate OAuth state
    # ------------------------------------------------------

    state = str(
        uuid.uuid4()
    )

    request.session[
        "microsoft_oauth_state"
    ] = state

    request.session.modified = True

    # ------------------------------------------------------
    # Create authorization URL
    # ------------------------------------------------------

    try:

        auth_url = (
            msal_app.get_authorization_request_url(
                scopes=scopes,
                redirect_uri=redirect_uri,
                state=state,
            )
        )

    except Exception as exc:

        print(
            "[MICROSOFT LOGIN] "
            "Authorization URL error:",
            exc
        )

        messages.error(
            request,
            "Unable to start Microsoft login."
        )

        return redirect(
            "accounts:login"
        )

    # ------------------------------------------------------
    # Redirect to Microsoft
    # ------------------------------------------------------

    return redirect(
        auth_url
    )


# ==========================================================
# MICROSOFT CALLBACK
# ==========================================================

def microsoft_callback(request):
    """
    Microsoft redirects here after authentication.

    Flow:

        Microsoft
             ↓
        Validate OAuth state
             ↓
        Exchange code
             ↓
        Microsoft Graph
             ↓
        Validate DUT email
             ↓
        Find/create Django user
             ↓
        Django login
             ↓
        Check preferences
             ↓
        Preferences OR Dashboard
    """

    # ======================================================
    # MICROSOFT ERROR
    # ======================================================

    if request.GET.get("error"):

        error_description = request.GET.get(
            "error_description",
            "Microsoft login was cancelled or failed."
        )

        print(
            "[MICROSOFT CALLBACK] Error:",
            request.GET.get("error")
        )

        print(
            "[MICROSOFT CALLBACK] Description:",
            error_description
        )

        messages.error(
            request,
            error_description
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # VALIDATE OAUTH STATE
    # ======================================================

    state = request.GET.get(
        "state"
    )

    saved_state = request.session.pop(
        "microsoft_oauth_state",
        None
    )

    if (
        not state
        or not saved_state
        or state != saved_state
    ):

        print(
            "[MICROSOFT CALLBACK] "
            "OAuth state validation failed."
        )

        messages.error(
            request,
            "Microsoft login security validation failed. "
            "Please try again."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # AUTHORIZATION CODE
    # ======================================================

    code = request.GET.get(
        "code"
    )

    if not code:

        messages.error(
            request,
            "Microsoft did not return an authorization code."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # MICROSOFT SETTINGS
    # ======================================================

    client_id = getattr(
        settings,
        "MICROSOFT_CLIENT_ID",
        ""
    )

    client_secret = getattr(
        settings,
        "MICROSOFT_CLIENT_SECRET",
        ""
    )

    redirect_uri = getattr(
        settings,
        "MICROSOFT_REDIRECT_URI",
        ""
    )

    authority = getattr(
        settings,
        "MICROSOFT_AUTHORITY",
        ""
    )

    scopes = getattr(
        settings,
        "MICROSOFT_SCOPE",
        ["User.Read"]
    )

    # ======================================================
    # VALIDATE CONFIGURATION
    # ======================================================

    if (
        not client_id
        or not client_secret
        or not redirect_uri
        or not authority
    ):

        messages.error(
            request,
            "Microsoft login is not configured correctly."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # MSAL APPLICATION
    # ======================================================

    msal_app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential=client_secret,
    )

    # ======================================================
    # EXCHANGE AUTHORIZATION CODE
    # ======================================================

    try:

        result = (
            msal_app.acquire_token_by_authorization_code(
                code=code,
                scopes=scopes,
                redirect_uri=redirect_uri,
            )
        )

    except Exception as exc:

        print(
            "[MICROSOFT CALLBACK] "
            "Token exchange error:",
            exc
        )

        messages.error(
            request,
            "Unable to complete Microsoft login."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # TOKEN ERROR
    # ======================================================

    if "error" in result:

        print(
            "[MICROSOFT CALLBACK] "
            "Token response:",
            result
        )

        messages.error(
            request,
            result.get(
                "error_description",
                "Microsoft authentication failed."
            )
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # TENANT VALIDATION
    # ======================================================

    id_token_claims = result.get(
        "id_token_claims",
        {}
    )

    microsoft_tenant_id = id_token_claims.get(
        "tid"
    )

    print(
        "[MICROSOFT CALLBACK] Tenant:",
        microsoft_tenant_id
    )

    allowed_tenant_ids = getattr(
        settings,
        "MICROSOFT_ALLOWED_TENANT_IDS",
        []
    )

    if (
        allowed_tenant_ids
        and microsoft_tenant_id not in allowed_tenant_ids
    ):

        print(
            "[MICROSOFT CALLBACK] "
            "Unauthorized tenant:",
            microsoft_tenant_id
        )

        messages.error(
            request,
            "Your Microsoft organization is not authorized "
            "to use SmartSpend."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # ACCESS TOKEN
    # ======================================================

    access_token = result.get(
        "access_token"
    )

    if not access_token:

        messages.error(
            request,
            "Microsoft did not provide an access token."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # MICROSOFT GRAPH
    # ======================================================

    try:

        graph_response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={
                "Authorization":
                    f"Bearer {access_token}"
            },
            timeout=10,
        )

    except requests.RequestException as exc:

        print(
            "[MICROSOFT CALLBACK] "
            "Graph request error:",
            exc
        )

        messages.error(
            request,
            "Could not retrieve your Microsoft account."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # GRAPH RESPONSE
    # ======================================================

    if not graph_response.ok:

        print(
            "[MICROSOFT CALLBACK] "
            "Graph status:",
            graph_response.status_code
        )

        print(
            "[MICROSOFT CALLBACK] "
            "Graph response:",
            graph_response.text
        )

        messages.error(
            request,
            "Could not retrieve your Microsoft account."
        )

        return redirect(
            "accounts:login"
        )

    try:

        microsoft_user = graph_response.json()

    except ValueError:

        messages.error(
            request,
            "Microsoft returned invalid account information."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # DEBUG INFORMATION
    # ======================================================

    print(
        "MICROSOFT GRAPH MAIL:",
        microsoft_user.get("mail")
    )

    print(
        "MICROSOFT GRAPH UPN:",
        microsoft_user.get(
            "userPrincipalName"
        )
    )

    # ======================================================
    # EMAIL
    # ======================================================

    email = (
        microsoft_user.get(
            "userPrincipalName"
        )
        or microsoft_user.get(
            "mail"
        )
        or ""
    ).strip().lower()

    # ======================================================
    # NAME
    # ======================================================

    first_name = (
        microsoft_user.get(
            "givenName"
        )
        or ""
    ).strip()

    last_name = (
        microsoft_user.get(
            "surname"
        )
        or ""
    ).strip()

    # ======================================================
    # VALIDATE EMAIL
    # ======================================================

    if not email:

        messages.error(
            request,
            "Microsoft did not provide an email address."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # DUT STUDENT EMAIL ONLY
    # ======================================================

    if not re.match(
        DUT_EMAIL_PATTERN,
        email,
        re.IGNORECASE
    ):

        print(
            "[MICROSOFT CALLBACK] "
            "Invalid DUT email:",
            email
        )

        messages.error(
            request,
            "Please sign in using your DUT student Microsoft account."
        )

        return redirect(
            "accounts:login"
        )

    # ======================================================
    # FIND DJANGO USER
    # ======================================================

    try:

        user = User.objects.get(
            email__iexact=email
        )

        print(
            "[MICROSOFT CALLBACK] "
            f"Existing user found: {email}"
        )

        # --------------------------------------------------
        # Update name
        # --------------------------------------------------

        changed = False

        if (
            first_name
            and user.first_name != first_name
        ):

            user.first_name = first_name
            changed = True

        if (
            last_name
            and user.last_name != last_name
        ):

            user.last_name = last_name
            changed = True

        if user.email != email:

            user.email = email
            changed = True

        if changed:

            user.save()

    except User.DoesNotExist:

        # --------------------------------------------------
        # Create new user
        # --------------------------------------------------

        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        print(
            "[MICROSOFT CALLBACK] "
            f"New user created: {email}"
        )

    # ======================================================
    # USER PROFILE
    # ======================================================

    UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "available_amount":
                DEFAULT_AVAILABLE_AMOUNT,
        },
    )

    # ======================================================
    # DJANGO LOGIN
    # ======================================================

    login(
        request,
        user,
        backend=(
            "django.contrib.auth.backends.ModelBackend"
        )
    )

    print(
        "[MICROSOFT CALLBACK] "
        f"Successfully logged in: {email}"
    )

    # ======================================================
    # CHECK PREFERENCES
    # ======================================================

    preference = Preference.objects.filter(
        user=user
    ).first()

    # ======================================================
    # NEW USER / NO PREFERENCE RECORD
    # ======================================================

    if preference is None:

        print(
            "[MICROSOFT CALLBACK] "
            f"{email}: No Preference record -> preferences"
        )

        return redirect(
            "preferences:edit"
        )

    # ======================================================
    # READ PREFERENCES
    # ======================================================

    styles = preference.styles or []
    colours = preference.colours or []
    stores = preference.stores or []
    hobbies = preference.hobbies or []

    # ======================================================
    # CHECK WHETHER USER HAS SELECTED ANYTHING
    # ======================================================

    has_preferences = any([
        bool(styles),
        bool(colours),
        bool(stores),
        bool(hobbies),
    ])

    # ======================================================
    # EMPTY PREFERENCES
    # ======================================================

    if not has_preferences:

        print(
            "[MICROSOFT CALLBACK] "
            f"{email}: Empty preferences -> preferences"
        )

        return redirect(
            "preferences:edit"
        )

    # ======================================================
    # EXISTING USER WITH PREFERENCES
    # ======================================================

    print(
        "[MICROSOFT CALLBACK] "
        f"{email}: Preferences found -> dashboard"
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

    user_profile, created = (
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "available_amount":
                    DEFAULT_AVAILABLE_AMOUNT,
            },
        )
    )

    if user_profile.available_amount is None:

        user_profile.available_amount = (
            DEFAULT_AVAILABLE_AMOUNT
        )

        user_profile.save(
            update_fields=[
                "available_amount"
            ]
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
    # Shopping budget / remaining amount
    # ------------------------------------------------------
    # Keep the profile amount aligned with the dashboard:
    # remaining = monthly budget - current month's spending.
    current_month = timezone.localtime()

    monthly_spent = (
        PurchaseHistory.objects.filter(
            user=user,
            purchased_at__year=current_month.year,
            purchased_at__month=current_month.month,
        )
        .aggregate(total=Sum("amount_spent"))
        ["total"]
        or Decimal("0.00")
    )

    monthly_budget = user_profile.available_amount or Decimal("0.00")
    remaining_amount = monthly_budget - monthly_spent

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
            "shopping_budget": monthly_budget,
            "monthly_budget": monthly_budget,
            "monthly_spent": monthly_spent,
            "remaining_amount": remaining_amount,
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
                "error":
                    "Latitude and longitude are required.",
            },
            status=400,
        )

    try:

        latitude_decimal = Decimal(
            latitude
        )

        longitude_decimal = Decimal(
            longitude
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error":
                    "Invalid latitude or longitude.",
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

    request.session[
        "user_latitude"
    ] = str(latitude_decimal)

    request.session[
        "user_longitude"
    ] = str(longitude_decimal)

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
                "lat":
                    str(latitude_decimal),

                "lon":
                    str(longitude_decimal),

                "format":
                    "json",

                "addressdetails":
                    1,
            },
            headers={
                "User-Agent":
                    "AI-Shopping-DUT/1.0"
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

    request.session[
        "user_address"
    ] = address

    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "latitude":
                str(latitude_decimal),

            "longitude":
                str(longitude_decimal),

            "address":
                address,
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

        amount_decimal = Decimal(
            amount
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error":
                    "Please enter a valid amount.",
            },
            status=400,
        )

    if amount_decimal < 0:

        return JsonResponse(
            {
                "success": False,
                "error":
                    "Amount cannot be negative.",
            },
            status=400,
        )

    amount_decimal = amount_decimal.quantize(
        Decimal("0.01")
    )

    request.session[
        "shopping_budget"
    ] = str(amount_decimal)

    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "amount":
                str(amount_decimal),
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

        # --------------------------------------------------
        # Validate fields
        # --------------------------------------------------

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

        email_exists = (
            User.objects
            .filter(
                email__iexact=email
            )
            .exclude(
                pk=user.pk
            )
            .exists()
        )

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

        # Keep username synchronized
        # when it was originally the email.
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
