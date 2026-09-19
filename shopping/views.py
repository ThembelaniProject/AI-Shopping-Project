from decimal import Decimal, InvalidOperation
from hashlib import md5
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from accounts.models import UserProfile

from .models import Order, OrderItem

from products.services.store_api import (
    get_product,
    StoreAPIError,
)


# ==========================================================
# SETTINGS
# ==========================================================

CART_SESSION_KEY = "shopping_cart"

PAYFAST_ORDER_SESSION_KEY = "payfast_order_id"

DEFAULT_SHOPPING_BUDGET = Decimal("1650.00")

DEFAULT_PRODUCT_STOCK = 200


# ==========================================================
# HOME
# ==========================================================

def home(request):

    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    return render(
        request,
        "index.html",
    )


# ==========================================================
# DASHBOARD
# ==========================================================

@login_required
def dashboard(request):

    return render(
        request,
        "dashboard.html",
    )


# ==========================================================
# USER PROFILE
# ==========================================================

def _get_user_profile(request):

    profile, created = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "available_amount": DEFAULT_SHOPPING_BUDGET,
        },
    )

    return profile


# ==========================================================
# CART HELPERS
# ==========================================================

def _get_cart(request):

    return dict(
        request.session.get(
            CART_SESSION_KEY,
            {},
        )
    )


def _save_cart(request, cart):

    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True


def _clear_cart(request):

    request.session.pop(
        CART_SESSION_KEY,
        None,
    )

    request.session.modified = True


def _get_product_stock(product):

    return DEFAULT_PRODUCT_STOCK


# ==========================================================
# BUILD CART
# ==========================================================

def _build_cart(request):

    cart = _get_cart(request)

    items = []

    subtotal = Decimal("0.00")
    shipping_total = Decimal("0.00")

    for product_id, quantity in cart.items():

        try:
            quantity = int(quantity)

        except (
            ValueError,
            TypeError,
        ):
            continue

        if quantity <= 0:
            continue

        try:
            product = get_product(product_id)

        except StoreAPIError:
            continue

        # --------------------------------------------------
        # PRICE
        # --------------------------------------------------

        try:

            price = Decimal(
                str(
                    product.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            price = Decimal("0.00")

        # --------------------------------------------------
        # SHIPPING
        # --------------------------------------------------

        try:

            shipping = Decimal(
                str(
                    product.get(
                        "shipping_cost",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            shipping = Decimal("0.00")

        if price < 0:
            price = Decimal("0.00")

        if shipping < 0:
            shipping = Decimal("0.00")

        # --------------------------------------------------
        # ITEM TOTAL
        # --------------------------------------------------

        item_total = price * quantity

        subtotal += item_total

        shipping_total += shipping

        # --------------------------------------------------
        # PRODUCT ID
        # --------------------------------------------------

        actual_product_id = str(
            product.get("external_id")
            or product.get("id")
            or product_id
        )

        product_name = (
            product.get("title")
            or product.get("name")
            or f"Product #{product_id}"
        )

        items.append(
            {
                "product": product,
                "product_id": actual_product_id,
                "cart_product_id": str(product_id),
                "product_name": product_name,
                "quantity": quantity,
                "item_total": item_total,
                "shipping_cost": shipping,
                "stock": DEFAULT_PRODUCT_STOCK,
            }
        )

    # ------------------------------------------------------
    # TOTAL
    # ------------------------------------------------------

    total = subtotal + shipping_total

    # ------------------------------------------------------
    # USER BUDGET
    # ------------------------------------------------------

    budget = None

    if request.user.is_authenticated:

        profile = _get_user_profile(request)

        budget = profile.available_amount

    # ------------------------------------------------------
    # BUDGET STATUS
    # ------------------------------------------------------

    budget_exceeded = False
    budget_reached = False
    budget_remaining = None

    if budget is not None:

        budget_remaining = budget - total

        if total > budget:

            budget_exceeded = True

        elif total == budget:

            budget_reached = True

    return {
        "items": items,
        "subtotal": subtotal,
        "shipping_total": shipping_total,
        "total": total,
        "item_count": sum(
            item["quantity"]
            for item in items
        ),
        "budget": budget,
        "budget_remaining": budget_remaining,
        "budget_exceeded": budget_exceeded,
        "budget_reached": budget_reached,
    }


# ==========================================================
# CART
# ==========================================================

@login_required
def cart(request):

    cart_data = _build_cart(request)

    return render(
        request,
        "shopping/cart.html",
        {
            "cart": cart_data,
            "profile": _get_user_profile(request),
        },
    )


# ==========================================================
# ADD TO CART
# ==========================================================

@login_required
def add_to_cart(request, product_id):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    profile = _get_user_profile(request)

    budget = profile.available_amount

    try:

        product = get_product(product_id)

    except StoreAPIError as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=404,
        )

    try:

        quantity = int(
            request.POST.get(
                "quantity",
                1,
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        quantity = 1

    if quantity < 1:
        quantity = 1

    stock = _get_product_stock(product)

    if stock <= 0:

        return JsonResponse(
            {
                "success": False,
                "error": "This product is out of stock.",
            },
            status=400,
        )

    cart = _get_cart(request)

    product_key = str(product_id)

    try:

        current_quantity = int(
            cart.get(
                product_key,
                0,
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        current_quantity = 0

    new_quantity = current_quantity + quantity

    if new_quantity > stock:

        return JsonResponse(
            {
                "success": False,
                "error": (
                    f"Only {stock} of this product "
                    f"are available."
                ),
            },
            status=400,
        )

    try:

        price = Decimal(
            str(
                product.get(
                    "price",
                    0,
                )
                or 0
            )
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "This product has an invalid price.",
            },
            status=400,
        )

    try:

        shipping = Decimal(
            str(
                product.get(
                    "shipping_cost",
                    0,
                )
                or 0
            )
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        shipping = Decimal("0.00")

    if price < 0:

        return JsonResponse(
            {
                "success": False,
                "error": "This product has an invalid price.",
            },
            status=400,
        )

    if shipping < 0:
        shipping = Decimal("0.00")

    current_cart_data = _build_cart(request)

    current_total = current_cart_data["total"]

    additional_cost = (
        price * quantity
        + shipping
    )

    new_total = current_total + additional_cost

    if new_total > budget:

        remaining = budget - current_total

        if remaining < 0:
            remaining = Decimal("0.00")

        return JsonResponse(
            {
                "success": False,
                "error": (
                    f"You have reached your shopping "
                    f"limit of R{budget:.2f}. "
                    f"You only have R{remaining:.2f} "
                    f"remaining."
                ),
                "budget": str(budget),
                "cart_total": str(current_total),
                "remaining": str(remaining),
            },
            status=400,
        )

    cart[product_key] = new_quantity

    _save_cart(
        request,
        cart,
    )

    cart_data = _build_cart(request)

    return JsonResponse(
        {
            "success": True,
            "message": "Product added to cart.",
            "cart_count": cart_data["item_count"],
            "subtotal": str(
                cart_data["subtotal"]
            ),
            "shipping": str(
                cart_data["shipping_total"]
            ),
            "total": str(
                cart_data["total"]
            ),
            "budget": str(budget),
            "remaining": str(
                cart_data["budget_remaining"]
            ),
        }
    )


# ==========================================================
# UPDATE CART
# ==========================================================

@login_required
def update_cart(request, product_id):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    try:

        quantity = int(
            request.POST.get(
                "quantity",
                1,
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid quantity.",
            },
            status=400,
        )

    product_key = str(product_id)

    cart = _get_cart(request)

    if product_key not in cart:

        return JsonResponse(
            {
                "success": False,
                "error": "Product is not in the cart.",
            },
            status=404,
        )

    if quantity <= 0:

        del cart[product_key]

        _save_cart(
            request,
            cart,
        )

        cart_data = _build_cart(request)

        return JsonResponse(
            {
                "success": True,
                "quantity": 0,
                "cart_count": cart_data["item_count"],
                "subtotal": str(
                    cart_data["subtotal"]
                ),
                "shipping": str(
                    cart_data["shipping_total"]
                ),
                "total": str(
                    cart_data["total"]
                ),
                "remaining": str(
                    cart_data["budget_remaining"]
                ),
            }
        )

    try:

        product = get_product(product_key)

    except StoreAPIError as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=404,
        )

    stock = _get_product_stock(product)

    if quantity > stock:

        return JsonResponse(
            {
                "success": False,
                "error": (
                    f"Only {stock} of this product "
                    f"are available."
                ),
            },
            status=400,
        )

    try:

        price = Decimal(
            str(
                product.get(
                    "price",
                    0,
                )
                or 0
            )
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return JsonResponse(
            {
                "success": False,
                "error": "This product has an invalid price.",
            },
            status=400,
        )

    if price < 0:

        return JsonResponse(
            {
                "success": False,
                "error": "This product has an invalid price.",
            },
            status=400,
        )

    try:

        shipping = Decimal(
            str(
                product.get(
                    "shipping_cost",
                    0,
                )
                or 0
            )
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        shipping = Decimal("0.00")

    if shipping < 0:
        shipping = Decimal("0.00")

    profile = _get_user_profile(request)

    budget = profile.available_amount

    try:

        old_quantity = int(
            cart.get(
                product_key,
                1,
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        old_quantity = 1

    cart[product_key] = quantity

    _save_cart(
        request,
        cart,
    )

    cart_data = _build_cart(request)

    new_total = cart_data["total"]

    if new_total > budget:

        cart[product_key] = old_quantity

        _save_cart(
            request,
            cart,
        )

        return JsonResponse(
            {
                "success": False,
                "error": (
                    f"This quantity would exceed "
                    f"your shopping budget of "
                    f"R{budget:.2f}."
                ),
                "budget": str(budget),
                "cart_total": str(new_total),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "quantity": quantity,
            "item_total": str(
                price * quantity
            ),
            "cart_count": cart_data["item_count"],
            "subtotal": str(
                cart_data["subtotal"]
            ),
            "shipping": str(
                cart_data["shipping_total"]
            ),
            "total": str(
                cart_data["total"]
            ),
            "budget": str(budget),
            "remaining": str(
                cart_data["budget_remaining"]
            ),
        }
    )


# ==========================================================
# REMOVE FROM CART
# ==========================================================

@login_required
def remove_from_cart(request, product_id):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    product_key = str(product_id)

    cart = _get_cart(request)

    cart.pop(
        product_key,
        None,
    )

    _save_cart(
        request,
        cart,
    )

    cart_data = _build_cart(request)

    return JsonResponse(
        {
            "success": True,
            "cart_count": cart_data["item_count"],
            "subtotal": str(
                cart_data["subtotal"]
            ),
            "shipping": str(
                cart_data["shipping_total"]
            ),
            "total": str(
                cart_data["total"]
            ),
        }
    )


# ==========================================================
# CLEAR CART
# ==========================================================

@login_required
def clear_cart(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    _clear_cart(request)

    return JsonResponse(
        {
            "success": True,
            "cart_count": 0,
        }
    )


# ==========================================================
# VALIDATE CHECKOUT CART
# ==========================================================

def _validate_checkout_cart(request):

    cart = _get_cart(request)

    if not cart:

        return (
            False,
            None,
            "Your cart is empty.",
        )

    validated_items = []

    subtotal = Decimal("0.00")

    shipping_total = Decimal("0.00")

    for product_id, raw_quantity in cart.items():

        try:

            quantity = int(raw_quantity)

        except (
            ValueError,
            TypeError,
        ):

            return (
                False,
                None,
                "Your cart contains an invalid quantity.",
            )

        if quantity <= 0:

            return (
                False,
                None,
                "Your cart contains an invalid quantity.",
            )

        try:

            product = get_product(product_id)

        except StoreAPIError:

            return (
                False,
                None,
                (
                    f"Product #{product_id} "
                    "is no longer available."
                ),
            )

        stock = _get_product_stock(product)

        product_name = (
            product.get("title")
            or product.get("name")
            or f"Product #{product_id}"
        )

        if stock <= 0:

            return (
                False,
                None,
                f'"{product_name}" is currently out of stock.',
            )

        if quantity > stock:

            return (
                False,
                None,
                (
                    f'"{product_name}" only has '
                    f"{stock} available, but your cart "
                    f"contains {quantity}. "
                    f"Please update your cart."
                ),
            )

        try:

            price = Decimal(
                str(
                    product.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            return (
                False,
                None,
                (
                    "A product in your cart "
                    "has an invalid price."
                ),
            )

        try:

            shipping = Decimal(
                str(
                    product.get(
                        "shipping_cost",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            shipping = Decimal("0.00")

        if price < 0:

            return (
                False,
                None,
                (
                    "A product in your cart "
                    "has an invalid price."
                ),
            )

        if shipping < 0:
            shipping = Decimal("0.00")

        item_total = price * quantity

        subtotal += item_total

        shipping_total += shipping

        validated_items.append(
            {
                "product": product,
                "product_id": str(
                    product.get("external_id")
                    or product.get("id")
                    or product_id
                ),
                "product_name": product_name,
                "quantity": quantity,
                "item_total": item_total,
                "shipping_cost": shipping,
                "stock": stock,
            }
        )

    total = subtotal + shipping_total

    profile = _get_user_profile(request)

    budget = profile.available_amount

    if total > budget:

        return (
            False,
            None,
            (
                f"Your cart total of "
                f"R{total:.2f} exceeds your "
                f"shopping limit of "
                f"R{budget:.2f}."
            ),
        )

    cart_data = {
        "items": validated_items,
        "subtotal": subtotal,
        "shipping_total": shipping_total,
        "total": total,
        "item_count": sum(
            item["quantity"]
            for item in validated_items
        ),
        "budget": budget,
        "budget_remaining": budget - total,
        "budget_exceeded": total > budget,
        "budget_reached": total == budget,
    }

    return (
        True,
        cart_data,
        None,
    )


# ==========================================================
# CHECKOUT
# ==========================================================

@login_required
def checkout(request):

    cart_data = _build_cart(request)

    if not cart_data["items"]:

        messages.warning(
            request,
            "Your cart is empty.",
        )

        return redirect(
            "shopping:cart"
        )

    profile = _get_user_profile(request)

    if cart_data["total"] > profile.available_amount:

        messages.error(
            request,
            (
                f"Your cart total of "
                f"R{cart_data['total']:.2f} "
                f"exceeds your shopping limit of "
                f"R{profile.available_amount:.2f}."
            ),
        )

        return redirect(
            "shopping:cart"
        )

    if request.method == "GET":

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    full_name = request.POST.get(
        "full_name",
        "",
    ).strip()

    email = request.POST.get(
        "email",
        "",
    ).strip()

    phone = request.POST.get(
        "phone",
        "",
    ).strip()

    address = request.POST.get(
        "address",
        "",
    ).strip()

    city = request.POST.get(
        "city",
        "",
    ).strip()

    postal_code = request.POST.get(
        "postal_code",
        "",
    ).strip()

    payment_method = request.POST.get(
        "payment_method",
        "",
    ).strip().lower()

    required_fields = [
        (
            full_name,
            "Please enter your full name.",
        ),
        (
            email,
            "Please enter your email address.",
        ),
        (
            phone,
            "Please enter your phone number.",
        ),
        (
            address,
            "Please enter your delivery address.",
        ),
        (
            city,
            "Please enter your city.",
        ),
        (
            postal_code,
            "Please enter your postal code.",
        ),
    ]

    for value, error_message in required_fields:

        if not value:

            messages.error(
                request,
                error_message,
            )

            return render(
                request,
                "shopping/checkout.html",
                {
                    "cart": cart_data,
                    "profile": profile,
                },
            )

    if payment_method not in [
        "payfast",
        "cash",
    ]:

        messages.error(
            request,
            "Please select a payment method.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    (
        cart_is_valid,
        cart_data,
        cart_error,
    ) = _validate_checkout_cart(request)

    if not cart_is_valid:

        messages.error(
            request,
            cart_error,
        )

        return redirect(
            "shopping:cart"
        )

    profile = _get_user_profile(request)

    if cart_data["total"] > profile.available_amount:

        messages.error(
            request,
            (
                f"Your cart total of "
                f"R{cart_data['total']:.2f} "
                f"exceeds your shopping limit of "
                f"R{profile.available_amount:.2f}."
            ),
        )

        return redirect(
            "shopping:cart"
        )

    order_total = cart_data["total"].quantize(
        Decimal("0.01")
    )

    order_subtotal = cart_data["subtotal"].quantize(
        Decimal("0.01")
    )

    order_shipping = cart_data[
        "shipping_total"
    ].quantize(
        Decimal("0.01")
    )

    try:

        with transaction.atomic():

            order = Order.objects.create(

                user=request.user,

                full_name=full_name,

                email=email,

                phone=phone,

                address=address,

                city=city,

                postal_code=postal_code,

                payment_method=payment_method,

                subtotal=order_subtotal,

                shipping_total=order_shipping,

                total=order_total,

                status="pending",

                payment_status=(
                    "pending"
                    if payment_method == "payfast"
                    else "paid"
                ),
            )

            for item in cart_data["items"]:

                product = item["product"]

                product_name = (
                    product.get("title")
                    or product.get("name")
                    or "Product"
                )

                try:

                    price = Decimal(
                        str(
                            product.get(
                                "price",
                                0,
                            )
                            or 0
                        )
                    ).quantize(
                        Decimal("0.01")
                    )

                except (
                    ValueError,
                    TypeError,
                    InvalidOperation,
                ):

                    raise ValueError(
                        "Invalid product price."
                    )

                OrderItem.objects.create(

                    order=order,

                    product_id=str(
                        product.get(
                            "external_id"
                        )
                        or product.get(
                            "id"
                        )
                        or item["product_id"]
                    ),

                    product_name=product_name,

                    price=price,

                    quantity=item["quantity"],

                    item_total=item["item_total"],
                )

    except Exception as exc:

        print(
            "CHECKOUT ERROR:",
            exc,
        )

        messages.error(
            request,
            "We could not place your order. Please try again.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    # ------------------------------------------------------
    # CASH
    # ------------------------------------------------------

    if payment_method == "cash":

        _clear_cart(request)

        messages.success(
            request,
            f"Order #{order.id} placed successfully!",
        )

        return redirect(
            "shopping:order_success",
            order_id=order.id,
        )

    # ------------------------------------------------------
    # PAYFAST
    # ------------------------------------------------------

    request.session[
        PAYFAST_ORDER_SESSION_KEY
    ] = order.id

    request.session.modified = True

    return redirect(
        "shopping:payfast_payment",
        order_id=order.id,
    )


# ==========================================================
# PAYFAST HELPERS
# ==========================================================

def _payfast_is_sandbox():

    return bool(
        getattr(
            settings,
            "PAYFAST_SANDBOX",
            True,
        )
    )


def _get_payfast_url():

    configured_url = getattr(
        settings,
        "PAYFAST_URL",
        None,
    )

    if configured_url:
        return configured_url

    if _payfast_is_sandbox():

        return (
            "https://sandbox.payfast.co.za/eng/process"
        )

    return (
        "https://www.payfast.co.za/eng/process"
    )


def _get_payfast_merchant_id():

    return str(
        getattr(
            settings,
            "PAYFAST_MERCHANT_ID",
            "",
        )
        or ""
    ).strip()


def _get_payfast_merchant_key():

    return str(
        getattr(
            settings,
            "PAYFAST_MERCHANT_KEY",
            "",
        )
        or ""
    ).strip()


def _get_payfast_passphrase():

    return str(
        getattr(
            settings,
            "PAYFAST_PASSPHRASE",
            "",
        )
        or ""
    ).strip()


def _absolute_url(request, route_name, **kwargs):

    return request.build_absolute_uri(
        reverse(
            route_name,
            kwargs=kwargs,
        )
    )


# ==========================================================
# PAYFAST SIGNATURE
# ==========================================================

def _payfast_signature(data):

    signature_data = {
        key: value
        for key, value in data.items()
        if key != "signature"
    }

    parameter_string = urlencode(
        signature_data
    )

    parameter_string = parameter_string.strip()

    passphrase = _get_payfast_passphrase()

    if passphrase:

        parameter_string += (
            "&passphrase="
            + passphrase
        )

    return md5(
        parameter_string.encode(
            "utf-8"
        )
    ).hexdigest().lower()


# ==========================================================
# PAYFAST REDIRECT
# ==========================================================

def _render_payfast_redirect(
    request,
    payment_url,
    payment_data,
):

    hidden_fields = []

    for name, value in payment_data.items():

        escaped_name = (
            str(name)
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        escaped_value = (
            str(value)
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        hidden_fields.append(
            (
                f'<input type="hidden" '
                f'name="{escaped_name}" '
                f'value="{escaped_value}">'
            )
        )

    fields_html = "\n".join(
        hidden_fields
    )

    escaped_action = (
        payment_url
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>

    <meta charset="utf-8">

    <title>Redirecting to PayFast...</title>

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <style>

        body {{
            background: #111;
            color: #fff;
            font-family: Arial, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }}

        .box {{
            text-align: center;
            padding: 40px;
        }}

        .spinner {{
            width: 42px;
            height: 42px;
            border: 4px solid #444;
            border-top-color: #28a745;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }}

        @keyframes spin {{
            to {{
                transform: rotate(360deg);
            }}
        }}

        button {{
            background: #28a745;
            border: 0;
            color: white;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
        }}

    </style>

</head>

<body>

    <div class="box">

        <div class="spinner"></div>

        <h2>
            Redirecting to PayFast...
        </h2>

        <p>
            Please wait while we securely
            redirect you to PayFast.
        </p>

        <form
            id="payfast_form"
            method="POST"
            action="{escaped_action}"
        >

            {fields_html}

            <button type="submit">
                Continue to PayFast
            </button>

        </form>

    </div>

    <script>

        document
            .getElementById("payfast_form")
            .submit();

    </script>

</body>
</html>
"""

    return HttpResponse(html)


# ==========================================================
# PAYFAST PAYMENT STATUS
# ==========================================================

@login_required
def payfast_payment_status(request, order_id):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if order.payment_status == "paid":

        _clear_cart(request)

        request.session.pop(
            PAYFAST_ORDER_SESSION_KEY,
            None,
        )

        request.session.modified = True

        return JsonResponse(
            {
                "success": True,
                "paid": True,
                "status": order.payment_status,
            }
        )

    if order.payment_status in [
        "failed",
        "cancelled",
    ]:

        return JsonResponse(
            {
                "success": True,
                "paid": False,
                "status": order.payment_status,
            }
        )

    return JsonResponse(
        {
            "success": True,
            "paid": False,
            "status": order.payment_status,
        }
    )


# ==========================================================
# PAYFAST PAYMENT
# ==========================================================

@login_required
def payfast_payment(
    request,
    order_id=None,
):

    if order_id is None:

        order_id = request.session.get(
            PAYFAST_ORDER_SESSION_KEY
        )

    if not order_id:

        messages.error(
            request,
            (
                "No PayFast order was found. "
                "Please start checkout again."
            ),
        )

        return redirect(
            "shopping:checkout"
        )

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if order.payment_method != "payfast":

        messages.error(
            request,
            "This order is not configured for PayFast.",
        )

        return redirect(
            "shopping:order_detail",
            order_id=order.id,
        )

    if order.payment_status == "paid":

        messages.info(
            request,
            "This order has already been paid.",
        )

        return redirect(
            "shopping:order_success",
            order_id=order.id,
        )

    merchant_id = _get_payfast_merchant_id()

    merchant_key = _get_payfast_merchant_key()

    if not merchant_id or not merchant_key:

        messages.error(
            request,
            (
                "PayFast is not configured correctly. "
                "Please set PAYFAST_MERCHANT_ID and "
                "PAYFAST_MERCHANT_KEY in your environment."
            ),
        )

        return redirect(
            "shopping:checkout"
        )

    name_parts = order.full_name.split(
        " ",
        1,
    )

    name_first = name_parts[0]

    name_last = (
        name_parts[1]
        if len(name_parts) > 1
        else ""
    )

    return_url = _absolute_url(
        request,
        "shopping:payfast_return",
        order_id=order.id,
    )

    cancel_url = _absolute_url(
        request,
        "shopping:payfast_cancel",
        order_id=order.id,
    )

    notify_url = _absolute_url(
        request,
        "shopping:payfast_itn",
    )

    order_amount = order.total.quantize(
        Decimal("0.01")
    )

    payment_data = {

        "merchant_id": merchant_id,

        "merchant_key": merchant_key,

        "return_url": return_url,

        "cancel_url": cancel_url,

        "notify_url": notify_url,

        "name_first": name_first,

        "name_last": name_last,

        "email_address": order.email,

        "m_payment_id": str(order.id),

        "amount": f"{order_amount:.2f}",

        "item_name": (
            f"AI Shopping Order #{order.id}"
        ),

        "item_description": (
            f"Payment for order #{order.id}"
        ),
    }

    payment_data["signature"] = (
        _payfast_signature(
            payment_data
        )
    )

    request.session[
        PAYFAST_ORDER_SESSION_KEY
    ] = order.id

    request.session.modified = True

    return _render_payfast_redirect(
        request,
        _get_payfast_url(),
        payment_data,
    )


# ==========================================================
# PAYFAST RETURN
# ==========================================================

@login_required
def payfast_return(
    request,
    order_id,
):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if order.payment_status == "paid":

        _clear_cart(request)

        request.session.pop(
            PAYFAST_ORDER_SESSION_KEY,
            None,
        )

        request.session.modified = True

        messages.success(
            request,
            (
                f"Payment received successfully "
                f"for Order #{order.id}."
            ),
        )

        return redirect(
            "shopping:order_success",
            order_id=order.id,
        )

    if order.payment_status == "failed":

        messages.error(
            request,
            (
                f"Payment for Order #{order.id} "
                "failed."
            ),
        )

        return redirect(
            "shopping:order_detail",
            order_id=order.id,
        )

    if order.payment_status == "cancelled":

        messages.warning(
            request,
            (
                f"Payment for Order #{order.id} "
                "was cancelled."
            ),
        )

        return redirect(
            "shopping:cart"
        )

    return render(
        request,
        "shopping/payment_processing.html",
        {
            "order": order,
        },
    )


# ==========================================================
# PAYFAST CANCEL
# ==========================================================

@login_required
def payfast_cancel(
    request,
    order_id,
):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if order.payment_status == "pending":

        order.payment_status = "cancelled"

        order.status = "cancelled"

        order.save(
            update_fields=[
                "payment_status",
                "status",
            ]
        )

    request.session.pop(
        PAYFAST_ORDER_SESSION_KEY,
        None,
    )

    request.session.modified = True

    messages.warning(
        request,
        (
            f"Payment for Order #{order.id} "
            "was cancelled. Your cart has been kept."
        ),
    )

    return redirect(
        "shopping:cart"
    )


# ==========================================================
# PAYFAST ITN
# ==========================================================

@csrf_exempt
def payfast_itn(request):

    if request.method != "POST":

        return HttpResponse(
            "Method Not Allowed",
            status=405,
        )

    post_data = request.POST.copy()

    received_signature = (
        post_data.get(
            "signature",
            "",
        )
        or ""
    ).strip()

    if not received_signature:

        return HttpResponse(
            "Missing signature",
            status=400,
        )

    signature_data = {
        key: value
        for key, value in post_data.items()
        if key != "signature"
    }

    calculated_signature = (
        _payfast_signature(
            signature_data
        )
    )

    if calculated_signature.lower() != (
        received_signature.lower()
    ):

        return HttpResponse(
            "Invalid signature",
            status=400,
        )

    order_id = (
        post_data.get(
            "m_payment_id"
        )
        or post_data.get(
            "custom_str1"
        )
    )

    if not order_id:

        return HttpResponse(
            "Missing order ID",
            status=400,
        )

    try:

        order_id = int(order_id)

    except (
        ValueError,
        TypeError,
    ):

        return HttpResponse(
            "Invalid order ID",
            status=400,
        )

    try:

        order = Order.objects.get(
            id=order_id,
        )

    except Order.DoesNotExist:

        return HttpResponse(
            "Order not found",
            status=404,
        )

    merchant_id = (
        post_data.get(
            "merchant_id",
            "",
        )
        or ""
    ).strip()

    configured_merchant_id = (
        _get_payfast_merchant_id()
    )

    if merchant_id != configured_merchant_id:

        return HttpResponse(
            "Invalid merchant",
            status=400,
        )

    payment_status = (
        post_data.get(
            "payment_status",
            "",
        )
        or ""
    ).strip().upper()

    if payment_status != "COMPLETE":

        if payment_status in [
            "CANCELLED",
            "CANCELED",
        ]:

            order.payment_status = "cancelled"

            order.status = "cancelled"

            order.save(
                update_fields=[
                    "payment_status",
                    "status",
                ]
            )

        elif payment_status == "FAILED":

            order.payment_status = "failed"

            order.save(
                update_fields=[
                    "payment_status",
                ]
            )

        return HttpResponse(
            "Payment not complete",
            status=200,
        )

    try:

        received_amount = Decimal(
            str(
                post_data.get(
                    "amount_gross",
                    post_data.get(
                        "amount",
                        "0",
                    ),
                )
            )
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return HttpResponse(
            "Invalid payment amount",
            status=400,
        )

    expected_amount = order.total.quantize(
        Decimal("0.01")
    )

    received_amount = received_amount.quantize(
        Decimal("0.01")
    )

    if received_amount != expected_amount:

        return HttpResponse(
            "Payment amount mismatch",
            status=400,
        )

    with transaction.atomic():

        order = (
            Order.objects
            .select_for_update()
            .select_related("user")
            .get(
                id=order.id,
            )
        )

        if order.payment_status == "paid":

            return HttpResponse(
                "OK",
                status=200,
            )

        if order.status in [
            "confirmed",
            "shipped",
            "delivered",
        ]:

            return HttpResponse(
                "OK",
                status=200,
            )

        try:

            profile = (
                UserProfile.objects
                .select_for_update()
                .get(
                    user=order.user,
                )
            )

        except UserProfile.DoesNotExist:

            profile = UserProfile.objects.create(
                user=order.user,
                available_amount=DEFAULT_SHOPPING_BUDGET,
            )

        amount_paid = order.total.quantize(
            Decimal("0.01")
        )

        current_balance = (
            profile.available_amount.quantize(
                Decimal("0.01")
            )
        )

        if current_balance < amount_paid:

            order.payment_status = "failed"

            order.save(
                update_fields=[
                    "payment_status",
                ]
            )

            return HttpResponse(
                "Insufficient user balance",
                status=400,
            )

        profile.available_amount = (
            current_balance - amount_paid
        )

        profile.save(
            update_fields=[
                "available_amount",
            ]
        )

        order.payment_status = "paid"

        order.status = "confirmed"

        order.save(
            update_fields=[
                "payment_status",
                "status",
            ]
        )

    return HttpResponse(
        "OK",
        status=200,
    )


# ==========================================================
# ORDER SUCCESS
# ==========================================================

@login_required
def order_success(
    request,
    order_id,
):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if order.payment_status == "paid":

        _clear_cart(request)

        request.session.pop(
            PAYFAST_ORDER_SESSION_KEY,
            None,
        )

        request.session.modified = True

    return render(
        request,
        "shopping/order_success.html",
        {
            "order": order,
        },
    )


# ==========================================================
# ORDER HISTORY
# ==========================================================

@login_required
def order_history(request):

    orders = (
        Order.objects
        .filter(
            user=request.user
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    return render(
        request,
        "shopping/order_history.html",
        {
            "orders": orders,
        },
    )


# ==========================================================
# ORDER DETAIL
# ==========================================================

@login_required
def order_detail(
    request,
    order_id,
):

    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items"
        ),
        id=order_id,
        user=request.user,
    )

    return render(
        request,
        "shopping/order_detail.html",
        {
            "order": order,
        },
    )


# ==========================================================
# CANCEL ORDER
# ==========================================================

@login_required
def cancel_order(
    request,
    order_id,
):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if request.method == "POST":

        if order.status not in [
            "cancelled",
            "confirmed",
            "shipped",
            "delivered",
        ]:

            order.status = "cancelled"

            if order.payment_status == "pending":

                order.payment_status = "cancelled"

                order.save(
                    update_fields=[
                        "status",
                        "payment_status",
                    ]
                )

            else:

                order.save(
                    update_fields=[
                        "status",
                    ]
                )

        return redirect(
            "shopping:order_detail",
            order_id=order.id,
        )

    return render(
        request,
        "shopping/cancel_order.html",
        {
            "order": order,
        },
    )


# ==========================================================
# MONTHLY STATEMENTS
# ==========================================================

@login_required
def monthly_statements(request):

    # ------------------------------------------------------
    # USER PROFILE
    # ------------------------------------------------------

    profile = _get_user_profile(request)

    # ------------------------------------------------------
    # GET USER ORDERS
    # ------------------------------------------------------

    orders = list(
        Order.objects
        .filter(
            user=request.user
        )
        .order_by(
            "created_at",
            "id",
        )
    )

    # ------------------------------------------------------
    # BUILD MONTHLY STATEMENTS
    # ------------------------------------------------------

    statements = {}

    for order in orders:

        month_key = order.created_at.strftime(
            "%Y-%m"
        )

        if month_key not in statements:

            statements[month_key] = {
                "month": month_key,

                "label": order.created_at.strftime(
                    "%B %Y"
                ),

                "orders": [],

                "paid_orders": [],

                "pending_orders": [],

                "cancelled_orders": [],

                "failed_orders": [],

                "subtotal": Decimal("0.00"),

                "shipping": Decimal("0.00"),

                "total": Decimal("0.00"),
            }

        statement = statements[month_key]

        # --------------------------------------------------
        # ALL ORDERS
        # --------------------------------------------------

        statement["orders"].append(order)

        # --------------------------------------------------
        # PAID
        # --------------------------------------------------

        if order.payment_status == "paid":

            statement["paid_orders"].append(
                order
            )

            statement["subtotal"] += (
                order.subtotal
                or Decimal("0.00")
            )

            statement["shipping"] += (
                order.shipping_total
                or Decimal("0.00")
            )

            statement["total"] += (
                order.total
                or Decimal("0.00")
            )

        # --------------------------------------------------
        # PENDING
        # --------------------------------------------------

        elif order.payment_status == "pending":

            statement["pending_orders"].append(
                order
            )

        # --------------------------------------------------
        # CANCELLED
        # --------------------------------------------------

        elif order.payment_status == "cancelled":

            statement["cancelled_orders"].append(
                order
            )

        # --------------------------------------------------
        # FAILED
        # --------------------------------------------------

        elif order.payment_status == "failed":

            statement["failed_orders"].append(
                order
            )

    # ------------------------------------------------------
    # CONVERT TO LIST
    # ------------------------------------------------------

    statements = list(
        statements.values()
    )

    # ------------------------------------------------------
    # SORT MONTHS
    # ------------------------------------------------------

    statements.sort(
        key=lambda statement: statement["month"],
        reverse=True,
    )

    # ------------------------------------------------------
    # SELECT MONTH
    # ------------------------------------------------------

    selected_month = request.GET.get(
        "month"
    )

    selected_statement = None

    if selected_month:

        for statement in statements:

            if statement["month"] == selected_month:

                selected_statement = statement

                break

    # ------------------------------------------------------
    # DEFAULT TO MOST RECENT MONTH
    # ------------------------------------------------------

    elif statements:

        selected_statement = statements[0]

        selected_month = (
            selected_statement["month"]
        )

    # ------------------------------------------------------
    # CALCULATE ACCOUNT BALANCES
    #
    # IMPORTANT:
    #
    # Only PAID orders affect the balance.
    #
    # Pending/cancelled/failed orders are displayed
    # but do not reduce the account balance.
    # ------------------------------------------------------

    # The current profile balance represents the balance
    # AFTER all successfully paid orders.
    #
    # Therefore we calculate historical balances backwards
    # from the current available amount.

    current_balance = (
        profile.available_amount
    )

    # ------------------------------------------------------
    # PROCESS ALL PAID ORDERS FROM NEWEST TO OLDEST
    # ------------------------------------------------------

    paid_orders = [
        order
        for order in orders
        if order.payment_status == "paid"
    ]

    paid_orders.sort(
        key=lambda order: (
            order.created_at,
            order.id,
        ),
        reverse=True,
    )

    # Attach running balances.
    #
    # For a paid order:
    #
    # balance after transaction =
    # current balance
    #
    # balance before transaction =
    # balance after + order total
    # ------------------------------------------------------

    running_balance = current_balance

    for order in paid_orders:

        order.running_balance = (
            running_balance
        )

        order.balance_before = (
            running_balance
            + (
                order.total
                or Decimal("0.00")
            )
        )

        running_balance = (
            order.balance_before
        )

    # ------------------------------------------------------
    # CALCULATE MONTH OPENING/CLOSING BALANCES
    # ------------------------------------------------------

    for statement in statements:

        month_key = statement["month"]

        month_paid_orders = [
            order
            for order in paid_orders
            if order.created_at.strftime(
                "%Y-%m"
            ) == month_key
        ]

        # --------------------------------------------------
        # CLOSING BALANCE
        #
        # Start from the current available amount and
        # reverse all paid transactions AFTER this month.
        # --------------------------------------------------

        closing_balance = (
            profile.available_amount
        )

        for order in paid_orders:

            order_month = order.created_at.strftime(
                "%Y-%m"
            )

            if order_month > month_key:

                closing_balance += (
                    order.total
                    or Decimal("0.00")
                )

        # --------------------------------------------------
        # OPENING BALANCE
        #
        # Closing balance + paid spending in this month
        # --------------------------------------------------

        opening_balance = (
            closing_balance
            + statement["total"]
        )

        statement["opening_balance"] = (
            opening_balance.quantize(
                Decimal("0.01")
            )
        )

        statement["closing_balance"] = (
            closing_balance.quantize(
                Decimal("0.01")
            )
        )

        statement["month_paid_orders"] = (
            month_paid_orders
        )

    # ------------------------------------------------------
    # TOTAL SPENDING
    # ------------------------------------------------------

    total_spending = sum(
        statement["total"]
        for statement in statements
    )

    total_spending = total_spending.quantize(
        Decimal("0.01")
    )

    # ------------------------------------------------------
    # CONTEXT
    # ------------------------------------------------------

    context = {

        "profile": profile,

        "statements": statements,

        "selected_month": selected_month,

        "selected_statement": selected_statement,

        "total_spending": total_spending,
    }

    # ------------------------------------------------------
    # RENDER
    # ------------------------------------------------------

    return render(
        request,
        "shopping/monthly_statements.html",
        context,
    )
