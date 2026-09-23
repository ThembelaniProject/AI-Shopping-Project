from django.urls import path

from . import views

app_name = "shopping"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("list/", views.shopping_list, name="shopping_list"),
    path("add-to-list/<str:product_id>/", views.add_to_shopping_list, name="add_to_shopping_list"),
    path("remove-from-list/<int:item_id>/", views.remove_from_shopping_list, name="remove_from_shopping_list"),
    path("purchase-from-list/<int:item_id>/", views.purchase_from_list, name="purchase_from_list"),
    path("purchase-history/", views.purchase_history, name="purchase_history"),
    path("mark-purchased/<str:product_id>/", views.mark_purchased, name="mark_purchased"),
]
