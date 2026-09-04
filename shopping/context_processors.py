from shopping.views import CART_SESSION_KEY


def cart_count(request):

    cart = request.session.get(
        CART_SESSION_KEY,
        {}
    )

    count = 0

    for quantity in cart.values():

        try:
            count += int(quantity)

        except (
            ValueError,
            TypeError,
        ):
            continue

    return {
        "cart_count": count
    }
