from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import (
get_object_or_404,
redirect,
render,
)

from accounts.models import UserProfile

from .models import Order, OrderItem

from products.services.store_api import (
get_product,
StoreAPIError,
)

CART_SESSION_KEY = "shopping_cart"


DEFAULT_SHOPPING_BUDGET = Decimal("1650.00")


DEFAULT_PRODUCT_STOCK = 200


def home(request):

    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    return render(
    request,
    "index.html",
)


@login_required
def dashboard(request):

    return render(
        request,
    "dashboard.html",
)

def _get_user_profile(request):

    profile, created = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "available_amount": DEFAULT_SHOPPING_BUDGET,
        },
    )

    return profile


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


def _get_product_stock(product):

    return DEFAULT_PRODUCT_STOCK


def _build_cart(request):

    cart = _get_cart(request)

    items = []

    subtotal = Decimal("0.00")
    shipping_total = Decimal("0.00")

    for product_id, quantity in cart.items():

        try:
            quantity = int(quantity)

        except (ValueError, TypeError):
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

        items.append(
            {
                "product": product,
                "product_id": actual_product_id,
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

    # ------------------------------------------------------
    # USER PROFILE / BUDGET
    # ------------------------------------------------------

    profile = _get_user_profile(request)

    budget = profile.available_amount

    # ------------------------------------------------------
    # PRODUCT
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # QUANTITY
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

    # Every product has 200 units.
    stock = _get_product_stock(product)

    if stock <= 0:

        return JsonResponse(
            {
                "success": False,
                "error": "This product is out of stock.",
            },
            status=400,
        )

    # ------------------------------------------------------
    # CART
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # NEW QUANTITY
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # PRODUCT PRICE
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # SHIPPING
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # CHECK RESULTING CART TOTAL
    # ------------------------------------------------------

    current_cart_data = _build_cart(request)

    current_total = current_cart_data["total"]

    additional_cost = (
        price * quantity
        + shipping
    )

    new_total = current_total + additional_cost

    # ------------------------------------------------------
    # BUDGET CHECK
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # SAVE
    # ------------------------------------------------------

    cart[product_key] = new_quantity

    _save_cart(
        request,
        cart,
    )

    # ------------------------------------------------------
    # UPDATED CART
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # QUANTITY
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # GET CART
    # ------------------------------------------------------

    cart = _get_cart(request)

    if product_key not in cart:

        return JsonResponse(
            {
                "success": False,
                "error": "Product is not in the cart.",
            },
            status=404,
        )

    # ------------------------------------------------------
    # REMOVE ITEM
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # GET PRODUCT
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

    # Every product has 200 units.
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

    # ------------------------------------------------------
    # GET PRICE
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # SHIPPING
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # BUDGET
    # ------------------------------------------------------

    profile = _get_user_profile(request)

    budget = profile.available_amount

    # ------------------------------------------------------
    # SAVE OLD QUANTITY
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # TEMPORARILY UPDATE CART
    # ------------------------------------------------------

    cart[product_key] = quantity

    _save_cart(
        request,
        cart,
    )

    cart_data = _build_cart(request)

    new_total = cart_data["total"]

    # ------------------------------------------------------
    # BUDGET EXCEEDED
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # SUCCESS
    # ------------------------------------------------------

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

    _save_cart(
        request,
        {},
    )

    return JsonResponse(
        {
            "success": True,
            "cart_count": 0,
        }
    )


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

    # ------------------------------------------------------
    # BUDGET CHECK
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # GET
    # ------------------------------------------------------

    if request.method == "GET":

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    # ------------------------------------------------------
    # CUSTOMER INFORMATION
    # ------------------------------------------------------

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
    ).strip()

    # ------------------------------------------------------
    # CARD NUMBER
    # ------------------------------------------------------

    card_number = request.POST.get(
        "card_number",
        "",
    ).strip()

    # ------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------

    if not full_name:

        messages.error(
            request,
            "Please enter your full name.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    if not email:

        messages.error(
            request,
            "Please enter your email address.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    if not phone:

        messages.error(
            request,
            "Please enter your phone number.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    if not address:

        messages.error(
            request,
            "Please enter your delivery address.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    if not city:

        messages.error(
            request,
            "Please enter your city.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
                "profile": profile,
            },
        )

    if not postal_code:

        messages.error(
            request,
            "Please enter your postal code.",
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
        "card",
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

    # ------------------------------------------------------
    # CARD VALIDATION
    # ------------------------------------------------------
    #
    # Card number is REQUIRED for card payment.
    # Card number is NOT required for cash on delivery.
    # ------------------------------------------------------

    if payment_method == "card":

        card_digits = "".join(
            character
            for character in card_number
            if character.isdigit()
        )

        if not card_digits:

            messages.error(
                request,
                "Please enter your card number.",
            )

            return render(
                request,
                "shopping/checkout.html",
                {
                    "cart": cart_data,
                    "profile": profile,
                },
            )

        if len(card_digits) < 13 or len(card_digits) > 19:

            messages.error(
                request,
                "Please enter a valid card number.",
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
    # FINAL CART VALIDATION
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # FINAL BUDGET CHECK
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # CREATE ORDER
    # ------------------------------------------------------

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

                subtotal=cart_data["subtotal"],

                shipping_total=cart_data[
                    "shipping_total"
                ],

                total=cart_data["total"],

                status="pending",
            )

            # --------------------------------------------------
            # ORDER ITEMS
            # --------------------------------------------------

            for item in cart_data["items"]:

                product = item["product"]

                product_name = product.get(
                    "title",
                    product.get(
                        "name",
                        "Product",
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

                    price = Decimal("0.00")

                OrderItem.objects.create(

                    order=order,

                    product_id=str(
                        product.get(
                            "external_id"
                        )
                        or product.get(
                            "id"
                        )
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
    # CLEAR CART
    # ------------------------------------------------------

    _save_cart(
        request,
        {},
    )

    # ------------------------------------------------------
    # RESULT
    # ------------------------------------------------------

    if payment_method == "cash":

        messages.success(
            request,
            f"Order #{order.id} placed successfully!",
        )

    else:

        messages.info(
            request,
            (
                f"Order #{order.id} created. "
                "Card payment still needs to be completed."
            ),
        )

    return redirect(
        "shopping:order_success",
        order_id=order.id,
    )


@login_required
def order_success(request, order_id):

    try:

        order = Order.objects.get(
            id=order_id,
            user=request.user,
        )

    except Order.DoesNotExist:

        messages.error(
            request,
            "Order not found.",
        )

        return redirect(
            "shopping:dashboard"
        )

    return render(
        request,
        "shopping/order_success.html",
        {
            "order": order,
        },
    )


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

        # --------------------------------------------------
        # QUANTITY
        # --------------------------------------------------

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

        # --------------------------------------------------
        # PRODUCT
        # --------------------------------------------------

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

        # --------------------------------------------------
        # STOCK
        # ------------------------------------------------------

        # Every product has 200 units.
        stock = _get_product_stock(product)

        product_name = product.get(
            "title",
            product.get(
                "name",
                f"Product #{product_id}",
            ),
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
                    f'{stock} available, but your cart '
                    f'contains {quantity}. '
                    f'Please update your cart.'
                ),
            )

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

            return (
                False,
                None,
                (
                    "A product in your cart "
                    "has an invalid price."
                ),
            )

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

        # --------------------------------------------------
        # ITEM TOTAL
        # --------------------------------------------------

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
                "quantity": quantity,
                "item_total": item_total,
                "shipping_cost": shipping,
                "stock": stock,
            }
        )

    # ------------------------------------------------------
    # TOTAL
    # ------------------------------------------------------

    total = subtotal + shipping_total

    # ------------------------------------------------------
    # BUDGET
    # ------------------------------------------------------

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


@login_required
def order_detail(request, order_id):

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



@login_required
def cancel_order(request, order_id):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
    )

    if request.method == "POST":

        if order.status not in [
            "cancelled",
            "completed",
        ]:

            order.status = "cancelled"

            order.save()

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