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
        "purchase-history/",
        views.purchase_history,
        name="purchase_history",
    ),
    path(
        "mark-purchased/<str:product_id>/",
        views.mark_purchased,
        name="mark_purchased",
    ),
]
