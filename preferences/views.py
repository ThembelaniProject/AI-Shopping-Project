from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Preference

@login_required
def preferences(request):
    preference = Preference.objects.filter(
    user=request.user
    ).first()

    return render(
        request,
        "preferences/preferences.html",
        {
            "preference": preference,
        },
)


@login_required
def edit_preferences(request):
    preference, created = Preference.objects.get_or_create(
    user=request.user
    )

    if request.method == "POST":

        preference.styles = request.POST.get(
            "styles",
            "",
        ).strip()

        preference.colours = request.POST.get(
            "colours",
            "",
        ).strip()

        preference.stores = request.POST.get(
            "stores",
            "",
        ).strip()

        preference.hobbies = request.POST.get(
            "hobbies",
            "",
        ).strip()

        preference.save()

        messages.success(
            request,
            "Your preferences have been updated successfully.",
        )

        return redirect(
            "preferences:preferences"
        )

    return render(
        request,
        "preferences/edit_preferences.html",
        {
            "preference": preference,
        },
    )


@login_required
def delete_preferences(request):

    preference = get_object_or_404(
        Preference,
        user=request.user,
    )

    if request.method == "POST":

        preference.delete()

        messages.success(
            request,
            "Your preferences have been deleted successfully.",
        )

        return redirect(
            "preferences:preferences"
        )

    return render(
        request,
        "preferences/delete_preferences.html",
        {
            "preference": preference,
        },
    )