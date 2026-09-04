from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from decimal import Decimal
from django.shortcuts import render, get_object_or_404

from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction

from .models import Order, OrderItem

from products.services.store_api import (
get_product,
StoreAPIError,
)

CART_SESSION_KEY = "shopping_cart"

def home(request):
    if request.user.is_authenticated:
        return redirect("shopping:dashboard")

    return render(request, "Index.html")


@login_required
def dashboard(request):
    return render(request, "dashboard.html")



def _get_cart(request):

    return request.session.get(
        CART_SESSION_KEY,
        {},
    )


def _save_cart(request, cart):


    request.session[CART_SESSION_KEY] = cart

    request.session.modified = True


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

        price = Decimal(
            str(
                product.get(
                    "price",
                    0,
                )
            )
        )

        shipping = Decimal(
            str(
                product.get(
                    "shipping_cost",
                    0,
                )
            )
        )

        item_total = price * quantity

        subtotal += item_total

        # Shipping is currently supplied by
        # DummyJSON as R0.00.
        #
        # We keep this separate so a real
        # store API can later provide shipping.

        shipping_total += shipping

        items.append(
            {
                "product": product,
                "quantity": quantity,
                "item_total": item_total,
                "shipping_cost": shipping,
            }
        )

    total = subtotal + shipping_total

    return {
        "items": items,
        "subtotal": subtotal,
        "shipping_total": shipping_total,
        "total": total,
        "item_count": sum(item["quantity"] for item in items),
    }


@login_required
def cart(request):

    cart_data = _build_cart(request)

    return render(
        request,
        "shopping/cart.html",
        {
            "cart": cart_data,
        },
    )


@login_required
def add_to_cart(request, product_id):
 # type: ignore
    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "error": "POST request required.",
            },
            status=405,
        )

    try:

        product = get_product(
            product_id
        )

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

    stock = int(
        product.get(
            "stock",
            0,
        )
        or 0
    )

    if stock <= 0:

        return JsonResponse(
            {
                "success": False,
                "error": "This product is out of stock.",
            },
            status=400,
        )

    cart = _get_cart(request)

    product_key = str(
        product_id
    )

    current_quantity = int(
        cart.get(
            product_key,
            0,
        )
    )

    new_quantity = (
        current_quantity
        + quantity
    )

    if new_quantity > stock:

        new_quantity = stock

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

            "cart_count":
                cart_data["item_count"],
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

    product_key = str(
        product_id
    )

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

    else:

        try:

            product = get_product(
                product_id
            )

            stock = int(
                product.get(
                    "stock",
                    0,
                )
                or 0
            )

            quantity = min(
                quantity,
                stock,
            )

        except StoreAPIError:

            pass

        if quantity <= 0:

            cart.pop(
                product_key,
                None,
            )

        else:

            cart[product_key] = quantity

    _save_cart(
        request,
        cart,
    )

    cart_data = _build_cart(request)

    return JsonResponse(
        {
            "success": True,

            "cart_count":
                cart_data["item_count"],

            "subtotal":
                str(cart_data["subtotal"]),

            "shipping":
                str(cart_data["shipping_total"]),

            "total":
                str(cart_data["total"]),
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

    product_key = str(
        product_id
    )

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

            "cart_count":
                cart_data["item_count"],

            "subtotal":
                str(cart_data["subtotal"]),

            "shipping":
                str(cart_data["shipping_total"]),

            "total":
                str(cart_data["total"]),
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
@login_required
def checkout(request):

    # ---------------------------------
    # INITIAL CART CHECK
    # ---------------------------------

    cart_data = _build_cart(request)

    if not cart_data["items"]:
        messages.warning(
            request,
            "Your cart is empty.",
        )
        return redirect("shopping:cart")

    # ---------------------------------
    # DISPLAY CHECKOUT
    # ---------------------------------

    if request.method == "GET":
        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
            },
        )

    # ---------------------------------
    # CUSTOMER INFORMATION
    # ---------------------------------

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

    # ---------------------------------
    # VALIDATE CUSTOMER INFORMATION
    # ---------------------------------

    if not full_name:
        messages.error(
            request,
            "Please enter your full name.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
        )

    if not email:
        messages.error(
            request,
            "Please enter your email address.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
        )

    if not phone:
        messages.error(
            request,
            "Please enter your phone number.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
        )

    if not address:
        messages.error(
            request,
            "Please enter your delivery address.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
        )

    if not city:
        messages.error(
            request,
            "Please enter your city.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
        )

    if not postal_code:
        messages.error(
            request,
            "Please enter your postal code.",
        )
        return render(
            request,
            "shopping/checkout.html",
            {"cart": cart_data},
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
            {"cart": cart_data},
        )

    # ---------------------------------
    # FINAL STOCK + PRICE CHECK
    # ---------------------------------

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

    # ---------------------------------
    # CREATE ORDER
    # ---------------------------------

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

            # -----------------------------
            # CREATE ORDER ITEMS
            # -----------------------------

            for item in cart_data["items"]:

                product = item["product"]

                product_name = product.get(
                    "title",
                    product.get(
                        "name",
                        "Product",
                    ),
                )

                price = Decimal(
                    str(
                        product.get(
                            "price",
                            0,
                        )
                    )
                )

                OrderItem.objects.create(
                    order=order,
                    product_id=int(
                        product["id"]
                    ),
                    product_name=product_name,
                    price=price,
                    quantity=item["quantity"],
                    item_total=item["item_total"],
                )

    except Exception:
        messages.error(
            request,
            "We could not place your order. Please try again.",
        )

        return render(
            request,
            "shopping/checkout.html",
            {
                "cart": cart_data,
            },
        )

    # ---------------------------------
    # CLEAR CART
    # ---------------------------------

    _save_cart(
        request,
        {},
    )

    # ---------------------------------
    # RESULT
    # ---------------------------------

    if payment_method == "cash":

        messages.success(
            request,
            f"Order #{order.id} placed successfully!",
        )

    else:

        messages.info(
            request,
            f"Order #{order.id} created. "
            "Card payment still needs to be completed.",
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
        return redirect("shopping:dashboard")

    return render(
        request,
        "shopping/order_success.html",
        {
            "order": order,
        },
    )
    
def _validate_checkout_cart(request):
    """
    Re-check every cart item against the store API immediately
    before creating an order.

    Returns:
        (True, cart_data, None)
        or
        (False, cart_data, error_message)
    """

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

        # -----------------------------
        # Validate quantity
        # -----------------------------

        try:
            quantity = int(raw_quantity)
        except (ValueError, TypeError):
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

        # -----------------------------
        # Get latest product
        # -----------------------------

        try:
            product = get_product(product_id)

        except StoreAPIError:
            return (
                False,
                None,
                f"Product #{product_id} is no longer available.",
            )

        # -----------------------------
        # Check stock
        # -----------------------------

        try:
            stock = int(
                product.get(
                    "stock",
                    0,
                )
                or 0
            )
        except (ValueError, TypeError):
            stock = 0

        if stock <= 0:
            product_name = product.get(
                "title",
                product.get(
                    "name",
                    f"Product #{product_id}",
                ),
            )

            return (
                False,
                None,
                f'"{product_name}" is currently out of stock.',
            )

        if quantity > stock:
            product_name = product.get(
                "title",
                product.get(
                    "name",
                    f"Product #{product_id}",
                ),
            )

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

        # -----------------------------
        # Get latest price
        # -----------------------------

        try:
            price = Decimal(
                str(
                    product.get(
                        "price",
                        0,
                    )
                )
            )
        except (ValueError, TypeError):
            return (
                False,
                None,
                "A product in your cart has an invalid price.",
            )

        # -----------------------------
        # Get shipping
        # -----------------------------

        try:
            shipping = Decimal(
                str(
                    product.get(
                        "shipping_cost",
                        0,
                    )
                )
            )
        except (ValueError, TypeError):
            shipping = Decimal("0.00")

        if price < 0:
            return (
                False,
                None,
                "A product in your cart has an invalid price.",
            )

        if shipping < 0:
            shipping = Decimal("0.00")

        item_total = price * quantity

        subtotal += item_total
        shipping_total += shipping

        validated_items.append(
            {
                "product": product,
                "quantity": quantity,
                "item_total": item_total,
                "shipping_cost": shipping,
            }
        )

    total = subtotal + shipping_total

    cart_data = {
        "items": validated_items,
        "subtotal": subtotal,
        "shipping_total": shipping_total,
        "total": total,
        "item_count": sum(
            item["quantity"]
            for item in validated_items
        ),
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
        .filter(user=request.user)
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
        Order.objects.prefetch_related("items"),
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

        if order.status not in ["cancelled", "completed"]:
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
