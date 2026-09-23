from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import UserProfile
from preferences.models import Preference


DEFAULT_SHOPPING_BUDGET = Decimal("1650.00")


def _get_user_profile(request):
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "available_amount": DEFAULT_SHOPPING_BUDGET,
        },
    )
    return profile


def home(request):
    """Public landing page and authenticated-user entry point."""
    if not request.user.is_authenticated:
        return render(request, "index.html")

    preference = Preference.objects.filter(
        user=request.user
    ).first()

    if preference is None:
        return redirect("preferences:edit")

    has_preferences = (
        bool(preference.styles)
        or bool(preference.colours)
        or bool(preference.stores)
        or bool(preference.hobbies)
    )

    if not has_preferences:
        return redirect("preferences:edit")

    profile = _get_user_profile(request)

    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    return redirect("shopping:dashboard")


@login_required
def dashboard(request):
    """Shopping dashboard.

    The dashboard helps students search, compare and budget for products.
    It does not provide cart, checkout, order or payment processing.
    """
    profile = _get_user_profile(request)

    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    preference = Preference.objects.filter(
        user=request.user
    ).first()

    return render(
        request,
        "dashboard.html",
        {
            "profile": profile,
            "preference": preference,
        },
    )
