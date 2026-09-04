from django.urls import path
from . import views

app_name = "shopping"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
    "cart/",
    views.cart,
    name="cart",
),

path(
    "cart/add/<int:product_id>/",
    views.add_to_cart,
    name="add_to_cart",
),

path(
    "cart/update/<int:product_id>/",
    views.update_cart,
    name="update_cart",
),

path(
    "cart/remove/<int:product_id>/",
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





