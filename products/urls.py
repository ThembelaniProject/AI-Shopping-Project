from django.urls import path

from . import views


app_name = "products"


urlpatterns = [
    path("search/", views.search, name="search"),
    path(
        "<str:product_id>/",
        views.detail,
        name="detail",
    ),
]
