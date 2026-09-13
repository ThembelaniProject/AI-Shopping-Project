from django.urls import path
from . import views

app_name = "shopping"

urlpatterns = [
    path(
        "dashboard/",
        views.dashboard,
        name="dashboard",
    ),

    path(
        "cart/",
        views.cart,
        name="cart",
    ),

    path(
        "cart/add/<str:product_id>/",
        views.add_to_cart,
        name="add_to_cart",
    ),

    path(
        "cart/update/<str:product_id>/",
        views.update_cart,
        name="update_cart",
    ),

    path(
        "cart/remove/<str:product_id>/",
        views.remove_from_cart,
        name="remove_from_cart",
    ),

    path(
        "cart/clear/",
        views.clear_cart,
        name="clear_cart",
    ),

    path(
        "checkout/",
        views.checkout,
        name="checkout",
    ),

    # ======================================================
    # PAYFAST
    # ======================================================

    path(
        "payment/payfast/<int:order_id>/",
        views.payfast_payment,
        name="payfast_payment",
    ),

    path(
        "payment/payfast/",
        views.payfast_payment,
        name="payfast_payment_legacy",
    ),

    path(
        "payment/payfast/return/<int:order_id>/",
        views.payfast_return,
        name="payfast_return",
    ),

    path(
        "payment/payfast/cancel/<int:order_id>/",
        views.payfast_cancel,
        name="payfast_cancel",
    ),

    path(
        "payment/payfast/itn/",
        views.payfast_itn,
        name="payfast_itn",
    ),

    # ======================================================
    # ORDERS
    # ======================================================

    path(
        "order-success/<int:order_id>/",
        views.order_success,
        name="order_success",
    ),

    path(
        "orders/",
        views.order_history,
        name="order_history",
    ),

    path(
        "orders/<int:order_id>/",
        views.order_detail,
        name="order_detail",
    ),

    path(
        "orders/<int:order_id>/cancel/",
        views.cancel_order,
        name="cancel_order",
    ),
]
