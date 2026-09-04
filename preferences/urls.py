from django.urls import path

from . import views

app_name = "preferences"

urlpatterns = [
path(
"",
views.preferences,
name="preferences",
),

path(
    "edit/",
    views.edit_preferences,
    name="edit",
),

path(
    "delete/",
    views.delete_preferences,
    name="delete",
),


]