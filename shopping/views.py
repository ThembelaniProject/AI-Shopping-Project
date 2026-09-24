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
    """Download a professional bank-statement-style SmartSpend analysis PDF."""
    try:
        months = int(request.GET.get("months", "1"))
    except (TypeError, ValueError):
        months = 1
    months = months if months in (1, 2, 3) else 1

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return HttpResponse(
            "PDF support is not installed. Run: pip install reportlab",
            status=500,
        )

    now = timezone.localtime()
    cursor = now.replace(day=1)
    for _ in range(months - 1):
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    purchases = PurchaseHistory.objects.filter(
        user=request.user,
        purchased_at__gte=cursor,
        purchased_at__lte=now,
    )
    additions = ShoppingListAddition.objects.filter(
        user=request.user,
        added_at__gte=cursor,
        added_at__lte=now,
    )

    total = purchases.aggregate(total=Sum("amount_spent"))["total"] or Decimal("0.00")
    items = purchases.aggregate(total=Sum("quantity"))["total"] or 0
    total_added = additions.aggregate(total=Sum("quantity"))["total"] or 0

    profile = _get_user_profile(request)
    monthly_budget = profile.available_amount or Decimal("0.00")
    period_budget = monthly_budget * months
    remaining = period_budget - total

    stores = list(
        purchases.values("store")
        .annotate(total=Sum("amount_spent"), items=Sum("quantity"))
        .order_by("-total")
    )
    products = list(
        purchases.values("product_name")
        .annotate(total=Sum("amount_spent"), items=Sum("quantity"))
        .order_by("-items", "-total")[:10]
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="smartspend-statement-{months}-months.pdf"'
    )

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    # SmartSpend's own clean bank-statement-inspired visual language.
    # It is intentionally not an exact Capitec reproduction.
    dark = colors.HexColor("#111111")
    accent = colors.HexColor("#D71920")
    light = colors.HexColor("#F4F4F4")
    border = colors.HexColor("#D8D8D8")
    muted = colors.HexColor("#666666")
    green = colors.HexColor("#16803A")
    red = colors.HexColor("#B42318")

    margin = 42
    content_width = width - (margin * 2)

    def money(value):
        return f"R{Decimal(value or 0):,.2f}"

    def draw_header(y):
        pdf.setFillColor(dark)
        pdf.rect(0, height - 74, width, 74, fill=1, stroke=0)

        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 21)
        pdf.drawString(margin, height - 39, "SmartSpend")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, height - 55, "AI Shopping & Budget Statement")

        pdf.setFillColor(accent)
        pdf.rect(width - margin - 82, height - 58, 82, 20, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(width - margin - 41, height - 51, "STATEMENT")

    def new_page():
        pdf.showPage()
        draw_header(height - 92)
        return height - 100

    def draw_section_title(title, y):
        pdf.setFillColor(dark)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin, y, title)
        pdf.setStrokeColor(border)
        pdf.line(margin, y - 5, width - margin, y - 5)
        return y - 22

    def draw_pie(cx, cy, radius, rows):
        total_value = sum(float(row["total"] or 0) for row in rows)
        if total_value <= 0:
            pdf.setFillColor(colors.HexColor("#DDDDDD"))
            pdf.circle(cx, cy, radius, fill=1, stroke=0)
            pdf.setFillColor(muted)
            pdf.setFont("Helvetica", 8)
            pdf.drawCentredString(cx, cy - 4, "No data")
            return

        palette = [
            colors.HexColor("#D71920"),
            colors.HexColor("#333333"),
            colors.HexColor("#777777"),
            colors.HexColor("#AAAAAA"),
            colors.HexColor("#555555"),
            colors.HexColor("#C7C7C7"),
            colors.HexColor("#E85D63"),
            colors.HexColor("#222222"),
        ]

        angle = 90
        legend_x = cx + radius + 24
        legend_y = cy + radius - 4

        for index, row in enumerate(rows):
            value = float(row["total"] or 0)
            extent = 360 * value / total_value
            pdf.setFillColor(palette[index % len(palette)])
            pdf.wedge(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                angle,
                extent,
                fill=1,
                stroke=0,
            )

            label = (row.get("store") or "Unknown store").strip()
            if len(label) > 22:
                label = label[:20] + "..."
            percentage = (value / total_value) * 100

            pdf.setFillColor(palette[index % len(palette)])
            pdf.rect(legend_x, legend_y - 2, 7, 7, fill=1, stroke=0)
            pdf.setFillColor(dark)
            pdf.setFont("Helvetica", 7.5)
            pdf.drawString(
                legend_x + 11,
                legend_y,
                f"{label}  {percentage:.1f}%  {money(value)}",
            )
            legend_y -= 14
            angle += extent

    draw_header(height - 92)
    y = height - 98

    # Statement identity block.
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(margin, y, "Shopping Account Statement")
    y -= 18

    user_name = request.user.get_full_name().strip() or request.user.username
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(margin, y, f"Account holder: {user_name}")
    pdf.drawRightString(
        width - margin,
        y,
        f"Statement date: {now:%d %B %Y}",
    )
    y -= 15
    pdf.drawString(
        margin,
        y,
        f"Statement period: {cursor:%d %B %Y} - {now:%d %B %Y}",
    )
    pdf.drawRightString(
        width - margin,
        y,
        f"Period: {months} month{'s' if months != 1 else ''}",
    )
    y -= 28

    # Summary cards.
    card_width = (content_width - 18) / 3
    summary = [
        ("TOTAL SPENT", money(total), dark),
        ("BUDGET", money(period_budget), dark),
        ("AVAILABLE", money(remaining), green if remaining >= 0 else red),
    ]
    for index, (label, value, value_color) in enumerate(summary):
        x = margin + index * (card_width + 9)
        pdf.setFillColor(light)
        pdf.roundRect(x, y - 52, card_width, 52, 5, fill=1, stroke=0)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(x + 10, y - 16, label)
        pdf.setFillColor(value_color)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(x + 10, y - 37, value)
    y -= 76

    # Account activity summary.
    y = draw_section_title("Account activity", y)
    activity = [
        ("Purchases recorded", str(items)),
        ("Shopping-list items added", str(total_added)),
        ("Budget used", f"{(float(total) / float(period_budget) * 100):.1f}%" if period_budget else "0.0%"),
    ]
    for label, value in activity:
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, y, label)
        pdf.setFillColor(dark)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawRightString(width - margin, y, value)
        y -= 17
    y -= 8

    # Pie chart analysis.
    if y < 360:
        y = new_page()

    y = draw_section_title("Spending analysis", y)
    if stores:
        draw_pie(margin + 105, y - 78, 72, stores[:8])
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(margin, y - 172, "Pie chart: spending distribution by store.")
        y -= 200
    else:
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, y - 10, "No recorded purchases were found for this period.")
        y -= 35

    # Transaction statement table.
    if y < 250:
        y = new_page()

    y = draw_section_title("Transaction statement", y)

    headers = ["DATE", "DESCRIPTION", "STORE", "QTY", "AMOUNT"]
    xs = [margin, margin + 67, margin + 255, margin + 360, width - margin]
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 7)
    for label, x in zip(headers, xs):
        if label == "AMOUNT":
            pdf.drawRightString(x, y, label)
        else:
            pdf.drawString(x, y, label)
    y -= 8
    pdf.setStrokeColor(border)
    pdf.line(margin, y, width - margin, y)
    y -= 15

    transactions = purchases.order_by("-purchased_at")[:40]
    pdf.setFont("Helvetica", 7.5)
    for purchase in transactions:
        if y < 55:
            y = new_page()
            y = draw_section_title("Transaction statement (continued)", y)

        date_text = timezone.localtime(purchase.purchased_at).strftime("%d/%m/%Y")
        description = purchase.product_name[:30]
        store = (purchase.store or "Unknown")[:17]

        pdf.setFillColor(dark)
        pdf.drawString(xs[0], y, date_text)
        pdf.drawString(xs[1], y, description)
        pdf.drawString(xs[2], y, store)
        pdf.drawRightString(xs[3] + 18, y, str(purchase.quantity))
        pdf.drawRightString(xs[4], y, money(purchase.amount_spent))
        pdf.setStrokeColor(colors.HexColor("#EEEEEE"))
        pdf.line(margin, y - 5, width - margin, y - 5)
        y -= 17

    # Top products analysis.
    if y < 220:
        y = new_page()

    y = draw_section_title("Top purchased products", y)
    pdf.setFont("Helvetica-Bold", 7)
    pdf.setFillColor(muted)
    pdf.drawString(margin, y, "PRODUCT")
    pdf.drawString(margin + 285, y, "QTY")
    pdf.drawRightString(width - margin, y, "SPENT")
    y -= 16

    pdf.setFont("Helvetica", 7.5)
    for row in products:
        if y < 55:
            y = new_page()
            y = draw_section_title("Top purchased products (continued)", y)

        name = (row["product_name"] or "Product")[:42]
        pdf.setFillColor(dark)
        pdf.drawString(margin, y, name)
        pdf.drawString(margin + 285, y, str(row["items"] or 0))
        pdf.drawRightString(width - margin, y, money(row["total"]))
        y -= 16

    # Footer on final page.
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 7)
    pdf.drawString(
        margin,
        28,
        "SmartSpend statement • Generated from recorded shopping activity • No payment processing is performed.",
    )
    pdf.drawRightString(width - margin, 28, f"Page period: {months}M")
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
