from django.urls import path

from . import views


app_name = "products"


urlpatterns = [
    # Product search page.
    path(
        "search/",
        views.search,
        name="search",
    ),

    # Backward-compatible detail URL.
    #
    # Older rendered pages may still contain:
    #     /products/search/<product_id>
    #
    # Keep this route so those links continue to work.
    path(
        "search/<str:product_id>/",
        views.detail,
        name="search_detail",
    ),

    # Canonical product detail URL.
    path(
        "<str:product_id>/",
        views.detail,
        name="detail",
    ),
]
