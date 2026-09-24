"""Template context processors for the shopping application."""

from django.db.models import Sum

from .models import ShoppingListItem


def shopping_context(request):
    """Expose the current user's shopping-list item count to the navbar."""
    if not request.user.is_authenticated:
        return {"shopping_list_count": 0}

    count = (
        ShoppingListItem.objects
        .filter(user=request.user)
        .aggregate(total=Sum("quantity"))
        .get("total")
        or 0
    )

    return {"shopping_list_count": count}
