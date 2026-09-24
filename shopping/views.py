from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.http import HttpResponse

from accounts.models import UserProfile
from preferences.models import Preference

from .models import PurchaseHistory, ShoppingListAddition, ShoppingListItem


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


def _load_product(request, product_id):
    from products.services.store_api import StoreAPIError, get_product
    try:
        product = get_product(product_id)
    except StoreAPIError as exc:
        messages.error(request, f"Could not load the product: {exc}")
        return None
    except Exception as exc:
        messages.error(request, f"Could not load the product: {exc}")
        return None
    if not product:
        messages.error(request, "Product could not be found.")
    return product


def _product_price(product):
    value = product.get("sale_price") if product.get("on_sale") else product.get("price", "0")
    try:
        return Decimal(str(value).replace(",", "").replace("R", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _product_snapshot(product, fallback_id=""):
    return {
        "product_id": str(product.get("id") or product.get("product_id") or fallback_id),
        "product_name": str(product.get("name") or "Product").strip(),
        "store": str(product.get("store") or "").strip(),
        "category": str(product.get("category") or "").strip(),
        "image_url": str(product.get("image") or "").strip() or None,
        "product_url": str(product.get("url") or "").strip() or None,
        "unit_price": _product_price(product),
    }


@login_required
def add_to_shopping_list(request, product_id):
    if request.method != "POST":
        return redirect("products:detail", product_id=product_id)
    if not _get_user_profile(request).terms_accepted:
        return redirect("accounts:accept_terms")
    product = _load_product(request, product_id)
    if not product:
        return redirect("products:search")
    try:
        quantity = max(1, min(int(request.POST.get("quantity", "1")), 999))
    except (ValueError, TypeError):
        quantity = 1
    snapshot = _product_snapshot(product, product_id)
    item = ShoppingListItem.objects.filter(user=request.user, product_id=snapshot["product_id"]).first()
    if item:
        item.quantity = min(999, item.quantity + quantity)
        for key, value in snapshot.items():
            setattr(item, key, value)
        item.save()
    else:
        item = ShoppingListItem.objects.create(user=request.user, quantity=quantity, **snapshot)

    ShoppingListAddition.objects.create(
        user=request.user,
        product_id=snapshot["product_id"],
        product_name=snapshot["product_name"],
        store=snapshot["store"],
        unit_price=snapshot["unit_price"],
        quantity=quantity,
    )

    messages.success(request, f"{item.product_name} was added to your shopping list.")
    return redirect("shopping:shopping_list")


@login_required
def shopping_list(request):
    profile = _get_user_profile(request)
    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")
    items = ShoppingListItem.objects.filter(user=request.user)
    estimated_total = sum((item.estimated_total for item in items), Decimal("0.00"))
    remaining_after_list = profile.available_amount - _current_month_spending(request.user) - estimated_total
    return render(request, "shopping/shopping_list.html", {
        "items": items,
        "estimated_total": estimated_total,
        "remaining_after_list": remaining_after_list,
    })


@login_required
def remove_from_shopping_list(request, item_id):
    if request.method == "POST":
        ShoppingListItem.objects.filter(id=item_id, user=request.user).delete()
    return redirect("shopping:shopping_list")



@login_required
def analytics(request):
    """Show monthly shopping, store, product and budget analytics."""
    profile = _get_user_profile(request)
    if not profile.terms_accepted:
        return redirect("accounts:accept_terms")

    try:
        months = int(request.GET.get("months", "1"))
    except (TypeError, ValueError):
        months = 1
    months = months if months in (1, 2, 3) else 1

    now = timezone.localtime()
    start_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
    if months == 1:
        start_date = now.replace(day=1)
    else:
        cursor = now.replace(day=1)
        for _ in range(months - 1):
            cursor = (cursor - timezone.timedelta(days=1)).replace(day=1)
        start_date = cursor

    purchases = PurchaseHistory.objects.filter(
        user=request.user,
        purchased_at__gte=start_date,
        purchased_at__lte=now,
    )
    additions = ShoppingListAddition.objects.filter(
        user=request.user,
        added_at__gte=start_date,
        added_at__lte=now,
    )

    store_rows = list(
        purchases.values("store").annotate(
            total=Sum("amount_spent"), items=Sum("quantity")
        ).order_by("-total")
    )
    product_rows = list(
        purchases.values("product_name").annotate(
            total=Sum("amount_spent"), items=Sum("quantity")
        ).order_by("-items")[:10]
    )

    monthly_rows = []
    for offset in range(months - 1, -1, -1):
        cursor = now.replace(day=1)
        for _ in range(offset):
            cursor = (cursor - timezone.timedelta(days=1)).replace(day=1)
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        row_purchases = purchases.filter(purchased_at__gte=cursor, purchased_at__lt=next_month)
        row_additions = additions.filter(added_at__gte=cursor, added_at__lt=next_month)
        spent = row_purchases.aggregate(total=Sum("amount_spent"))["total"] or Decimal("0.00")
        added_items = row_additions.aggregate(total=Sum("quantity"))["total"] or 0
        monthly_rows.append({
            "label": cursor.strftime("%B %Y"),
            "spent": spent,
            "budget": profile.available_amount,
            "remaining": profile.available_amount - spent,
            "added_items": added_items,
        })

    shopping_list_items = ShoppingListItem.objects.filter(user=request.user)
    recent_additions = additions[:20]

    context = {
        "profile": profile,
        "months": months,
        "monthly_rows": monthly_rows,
        "store_rows": store_rows,
        "product_rows": product_rows,
        "recent_additions": recent_additions,
        "shopping_list_items": shopping_list_items,
        "date_from": start_date,
        "date_to": now,
        "total_spent": purchases.aggregate(total=Sum("amount_spent"))["total"] or Decimal("0.00"),
        "total_items": purchases.aggregate(total=Sum("quantity"))["total"] or 0,
        "total_added": additions.aggregate(total=Sum("quantity"))["total"] or 0,
    }
    return render(request, "shopping/analytics.html", context)


@login_required
def analytics_pdf(request):
    """Download a PDF statement for 1, 2 or 3 months."""
    try:
        months = int(request.GET.get("months", "1"))
    except (TypeError, ValueError):
        months = 1
    months = months if months in (1, 2, 3) else 1

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return HttpResponse("PDF support is not installed. Run: pip install reportlab", status=500)

    now = timezone.localtime()
    cursor = now.replace(day=1)
    for _ in range(months - 1):
        cursor = (cursor - timezone.timedelta(days=1)).replace(day=1)
    purchases = PurchaseHistory.objects.filter(
        user=request.user, purchased_at__gte=cursor, purchased_at__lte=now
    )
    total = purchases.aggregate(total=Sum("amount_spent"))["total"] or Decimal("0.00")
    items = purchases.aggregate(total=Sum("quantity"))["total"] or 0
    stores = purchases.values("store").annotate(total=Sum("amount_spent"), items=Sum("quantity")).order_by("-total")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="smartspend-statement-{months}-months.pdf"'
    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(45, y, "SmartSpend Shopping Statement")
    y -= 30
    pdf.setFont("Helvetica", 10)
    pdf.drawString(45, y, f"Period: {cursor:%d %B %Y} - {now:%d %B %Y}")
    y -= 18
    pdf.drawString(45, y, f"Total items purchased: {items}")
    y -= 18
    pdf.drawString(45, y, f"Total spending: R{total:.2f}")
    y -= 28
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(45, y, "Spending by store")
    y -= 20
    pdf.setFont("Helvetica", 10)
    for row in stores:
        store = row["store"] or "Unknown store"
        pdf.drawString(55, y, f"{store}: R{row['total']:.2f} ({row['items']} items)")
        y -= 16
        if y < 60:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 10)
    y -= 10
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(45, y, "Generated by SmartSpend. Figures are based on recorded purchases.")
    pdf.save()
    return response


@login_required
def purchase_from_list(request, item_id):
    if request.method != "POST":
        return redirect("shopping:shopping_list")
    item = ShoppingListItem.objects.filter(id=item_id, user=request.user).first()
    if not item:
        messages.error(request, "Shopping-list item was not found.")
        return redirect("shopping:shopping_list")
    purchase = PurchaseHistory.objects.create(
        user=request.user,
        product_id=item.product_id,
        product_name=item.product_name,
        store=item.store,
        category=item.category,
        image_url=item.image_url,
        product_url=item.product_url,
        unit_price=item.unit_price,
        quantity=item.quantity,
        amount_spent=item.estimated_total,
    )
    item.delete()
    messages.success(request, f"{purchase.product_name} was added to your purchase history.")
    return redirect("shopping:purchase_history")
