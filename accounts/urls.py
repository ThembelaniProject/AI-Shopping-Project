from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = "accounts"

urlpatterns = [

# ------------------------------------------------------
# LOGIN
# ------------------------------------------------------

path(
    "login/",
    views.login_view,
    name="login",
),

# ------------------------------------------------------
# LOGOUT
# ------------------------------------------------------

path(
    "logout/",
    auth_views.LogoutView.as_view(
        next_page="accounts:login"
    ),
    name="logout",
),

# ------------------------------------------------------
# REGISTER
# ------------------------------------------------------

path(
    "register/",
    views.register_view,
    name="register",
),

# ------------------------------------------------------
# MICROSOFT LOGIN
# ------------------------------------------------------

path(
    "microsoft/login/",
    views.microsoft_login,
    name="microsoft_login",
),

path(
    "microsoft/callback/",
    views.microsoft_callback,
    name="microsoft_callback",
),

# ------------------------------------------------------
# PROFILE
# ------------------------------------------------------

path(
    "profile/",
    views.profile,
    name="profile",
),

# ------------------------------------------------------
# LOCATION
# ------------------------------------------------------

path(
    "profile/update-location/",
    views.update_location,
    name="update_location",
),

# ------------------------------------------------------
# BUDGET
# ------------------------------------------------------

path(
    "profile/update-budget/",
    views.update_budget,
    name="update_budget",
),


]
