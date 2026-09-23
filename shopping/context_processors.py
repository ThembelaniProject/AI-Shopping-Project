"""Template context processors for the shopping application."""


def shopping_context(request):
    """Return shopping-wide template context.

    Cart/order context was removed because the application does not
    implement cart, checkout, order or payment processing.
    """
    return {}
