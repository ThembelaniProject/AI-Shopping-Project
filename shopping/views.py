from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.models import UserProfile
from preferences.models import Preference

from .models import PurchaseHistory


DEFAULT_SHOPPING_BUDGET = Decimal("1650.00")


def _get_user_profile(request):
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "available_amount": DEFAULT_SHOPPING_BUDGET,
        },
    )
    return profile


def _current_month_spending(user):
    now = timezone.localtime()
    return (
        PurchaseHistory.objects.filter(
            user=user,
            purchased_at__year=now.year,
            purchased_at__month=now.month,
        ).aggregate(
            total=Sum("amount_spent")
        )["total"]
        or Decimal("0.00")
    )


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
    """Shopping dashboard with budget and recorded spending."""
    profile = _get_user_profile(request)

    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    preference = Preference.objects.filter(
        user=request.user
    ).first()

    monthly_spent = _current_month_spending(request.user)
    monthly_budget = profile.available_amount
    remaining_budget = monthly_budget - monthly_spent

    recent_purchases = PurchaseHistory.objects.filter(
        user=request.user
    )[:5]

    return render(
        request,
        "dashboard.html",
        {
            "profile": profile,
            "preference": preference,
            "monthly_budget": monthly_budget,
            "monthly_spent": monthly_spent,
            "remaining_budget": remaining_budget,
            "recent_purchases": recent_purchases,
        },
    )


@login_required
def purchase_history(request):
    """Display the student's manually recorded purchase history."""
    profile = _get_user_profile(request)

    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    purchases = PurchaseHistory.objects.filter(
        user=request.user
    )

    monthly_spent = _current_month_spending(request.user)
    monthly_budget = profile.available_amount
    remaining_budget = monthly_budget - monthly_spent

    return render(
        request,
        "shopping/purchase_history.html",
        {
            "purchases": purchases,
            "monthly_budget": monthly_budget,
            "monthly_spent": monthly_spent,
            "remaining_budget": remaining_budget,
        },
    )


@login_required
def mark_purchased(request, product_id):
    """Record a product after the student purchases it externally."""
    if request.method != "POST":
        return redirect("products:detail", product_id=product_id)

    profile = _get_user_profile(request)

    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    # Import here to avoid coupling shopping models to the products app.
    from products.services.store_api import (
        StoreAPIError,
        get_product,
    )

    try:
        product = get_product(product_id)
    except StoreAPIError as exc:
        messages.error(
            request,
            f"Could not load the product: {exc}",
        )
        return redirect("products:detail", product_id=product_id)
    except Exception as exc:
        messages.error(
            request,
            f"Could not load the product: {exc}",
        )
        return redirect("products:detail", product_id=product_id)

    if not product:
        messages.error(
            request,
            "Product could not be found.",
        )
        return redirect("products:search")

    try:
        unit_price = Decimal(
            str(
                product.get(
                    "sale_price"
                    if product.get("on_sale")
                    else "price",
                    product.get("price", "0"),
                )
            ).replace(",", "").replace("R", "").strip()
        )
    except (InvalidOperation, ValueError, TypeError):
        unit_price = Decimal("0.00")

    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (ValueError, TypeError):
        quantity = 1

    quantity = max(1, min(quantity, 999))

    default_total = unit_price * quantity

    try:
        amount_spent = Decimal(
            request.POST.get(
                "amount_spent",
                str(default_total),
            )
        )
    except (InvalidOperation, ValueError, TypeError):
        amount_spent = default_total

    if amount_spent < Decimal("0.00"):
        amount_spent = default_total

    purchase = PurchaseHistory.objects.create(
        user=request.user,
        product_id=str(
            product.get("id")
            or product.get("product_id")
            or product_id
        ),
        product_name=str(
            product.get("name")
            or "Product"
        ).strip(),
        store=str(
            product.get("store")
            or ""
        ).strip(),
        category=str(
            product.get("category")
            or ""
        ).strip(),
        image_url=(
            str(product.get("image") or "").strip()
            or None
        ),
        product_url=(
            str(product.get("url") or "").strip()
            or None
        ),
        unit_price=unit_price,
        quantity=quantity,
        amount_spent=amount_spent,
    )

    messages.success(
        request,
        (
            f"{purchase.product_name} was added to your purchase "
            f"history. Recorded spending: R{purchase.amount_spent:.2f}."
        ),
    )

    return redirect("shopping:purchase_history")
