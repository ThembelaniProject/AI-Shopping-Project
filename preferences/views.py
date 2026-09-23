from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages

from .models import Preference

@login_required
def preferences(request):
    preference = Preference.objects.filter(user=request.user).first()


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


    styles_options = [
        "Casual",
        "Formal",
        "Sporty",
        "Streetwear",
        "Smart Casual",
    ]

    colours_options = [
        "Black",
        "White",
        "Blue",
        "Red",
        "Green",
        "Grey",
        "Brown",
        "Pink",
    ]

    stores_options = [
        "Mr Price",
        "Woolworths",
        "H&M",
        "Zara",
        "Cotton On",
        "Truworths",
    ]

    hobbies_options = [
        "Football",
        "Gaming",
        "Music",
        "Fitness",
        "Travel",
        "Photography",
    ]

    if request.method == "POST":

        selected_styles = request.POST.getlist("styles")
        selected_colours = request.POST.getlist("colours")
        selected_stores = request.POST.getlist("stores")
        selected_hobbies = request.POST.getlist("hobbies")

        preference.styles = selected_styles
        preference.colours = selected_colours
        preference.stores = selected_stores
        preference.hobbies = selected_hobbies

        preference.save()

        # Check if user has accepted Terms & Privacy Policy
        profile = getattr(request.user, "profile", None)
        if profile and not profile.terms_accepted:
            messages.success(
                request,
                "Your preferences have been saved successfully. Please review and accept the Terms & Conditions and Privacy Policy to continue."
            )
            return redirect("accounts:accept_terms")

        messages.success(
            request,
            "Your preferences have been saved successfully."
        )

        return redirect("preferences:preferences")

    selected_styles = preference.styles or []
    selected_colours = preference.colours or []
    selected_stores = preference.stores or []
    selected_hobbies = preference.hobbies or []

    return render(
        request,
        "preferences/edit.html",
        {
            "preference": preference,
            "styles_options": styles_options,
            "colours_options": colours_options,
            "stores_options": stores_options,
            "hobbies_options": hobbies_options,
            "selected_styles": selected_styles,
            "selected_colours": selected_colours,
            "selected_stores": selected_stores,
            "selected_hobbies": selected_hobbies,
        },
    )


@login_required
def delete_preferences(request):
    preference = Preference.objects.filter(user=request.user).first()

  
    if request.method == "POST":
        if preference:
            preference.delete()

        messages.success(
            request,
            "Your preferences have been deleted."
        )

        return redirect("preferences:preferences")

    return render(
        request,
        "preferences/delete.html",
        {
            "preference": preference,
        },
    )

