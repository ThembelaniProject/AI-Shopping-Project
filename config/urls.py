from django.contrib import admin
from django.urls import include, path
from shopping.views import home


urlpatterns = [
    path("admin/", admin.site.urls),

    # Home page
    path("", home, name="home"),

    # Authentication
    path("accounts/", include("accounts.urls")),

    # Products
    path("products/", include("products.urls")),

    # Preferences
    path("preferences/", include("preferences.urls")),

    # Shopping
    path("shopping/", include("shopping.urls")),
]