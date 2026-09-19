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
path(
    "profile/edit/",
    views.edit_profile,
    name="edit_profile"
),


]
