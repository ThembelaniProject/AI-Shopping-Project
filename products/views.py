from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from preferences.models import Preference

from .services.store_api import (
search_products,
get_product,
StoreAPIError,
)

@login_required
def search(request):
        # ==========================================
    # USER PREFERENCES
    # ==========================================

    try:
        preferences = Preference.objects.get(
            user=request.user
        )
    except Preference.DoesNotExist:
        preferences = None

    # ==========================================
    # SEARCH PARAMETERS
    # ==========================================

    keyword = request.GET.get(
        "keyword",
        ""
    ).strip()

    budget = request.GET.get(
        "budget",
        ""
    ).strip()

    colour = request.GET.get(
        "colour",
        ""
    ).strip()

    size = request.GET.get(
        "size",
        ""
    ).strip()

    store = request.GET.get(
        "store",
        ""
    ).strip()

    location = request.GET.get(
        "location",
        ""
    ).strip()

    max_shipping = request.GET.get(
        "max_shipping",
        ""
    ).strip()

    max_distance = request.GET.get(
        "max_distance",
        ""
    ).strip()

    sort = request.GET.get(
        "sort",
        "price_asc",
    )

    user_latitude = request.GET.get(
        "user_latitude",
        "",
    )

    user_longitude = request.GET.get(
        "user_longitude",
        "",
    )

    products = []
    api_error = None

    # ==========================================
    # SEARCH API
    # ==========================================

    if keyword:

        try:

            products = search_products(
                keyword=keyword,
                limit=30,
            )

        except StoreAPIError as exc:

            api_error = str(exc)

    # ==========================================
    # NORMALISE PRODUCT DATA
    # ==========================================

    for item in products:

        item.setdefault(
            "name",
            "Unnamed Product",
        )

        item.setdefault(
            "colour",
            "",
        )

        item.setdefault(
            "size",
            "",
        )

        item.setdefault(
            "store",
            "",
        )

        item.setdefault(
            "location",
            "",
        )

        item.setdefault(
            "description",
            "",
        )

        item.setdefault(
            "category",
            "",
        )

        item.setdefault(
            "brand",
            "",
        )

        item.setdefault(
            "image",
            "",
        )

        item.setdefault(
            "url",
            "",
        )

        # --------------------------------------
        # Price
        # --------------------------------------

        try:

            item["price"] = Decimal(
                str(
                    item.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            item["price"] = Decimal("0")

        # --------------------------------------
        # Shipping
        # --------------------------------------

        try:

            item["shipping_cost"] = Decimal(
                str(
                    item.get(
                        "shipping_cost",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            item["shipping_cost"] = Decimal("0")

        # --------------------------------------
        # Rating
        # --------------------------------------

        try:

            item["rating"] = Decimal(
                str(
                    item.get(
                        "rating",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            item["rating"] = Decimal("0")

        # --------------------------------------
        # Stock
        # --------------------------------------

        try:

            item["stock"] = int(
                item.get(
                    "stock",
                    0,
                )
                or 0
            )

        except (
            ValueError,
            TypeError,
        ):

            item["stock"] = 0

        # --------------------------------------
        # Distance
        # --------------------------------------

        item.setdefault(
            "distance",
            None,
        )

    # ==========================================
    # BUDGET FILTER
    # ==========================================

    if budget:

        try:

            max_budget = Decimal(budget)

            products = [
                item
                for item in products
                if item["price"] <= max_budget
            ]

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            pass

    # ==========================================
    # COLOUR FILTER
    # ==========================================

    if colour:

        colour_lower = colour.lower()

        products = [
            item
            for item in products
            if colour_lower
            in item.get(
                "colour",
                "",
            ).lower()
        ]

    # ==========================================
    # SIZE FILTER
    # ==========================================

    if size:

        size_lower = size.lower()

        products = [
            item
            for item in products
            if size_lower
            in item.get(
                "size",
                "",
            ).lower()
        ]

    # ==========================================
    # STORE FILTER
    # ==========================================

    if store:

        store_lower = store.lower()

        products = [
            item
            for item in products
            if store_lower
            in item.get(
                "store",
                "",
            ).lower()
        ]

    # ==========================================
    # LOCATION FILTER
    # ==========================================

    if location:

        location_lower = location.lower()

        products = [
            item
            for item in products
            if location_lower
            in item.get(
                "location",
                "",
            ).lower()
        ]

    # ==========================================
    # SHIPPING FILTER
    # ==========================================

    if max_shipping:

        try:

            shipping_limit = Decimal(
                max_shipping
            )

            products = [
                item
                for item in products
                if item["shipping_cost"]
                <= shipping_limit
            ]

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            pass

    # ==========================================
    # DISTANCE
    # ==========================================

    # DummyJSON does not currently provide
    # real store coordinates.

    for item in products:

        item.setdefault(
            "distance",
            None,
        )

    # ==========================================
    # MAX DISTANCE FILTER
    # ==========================================

    if max_distance:

        try:

            distance_limit = Decimal(
                max_distance
            )

            products = [
                item
                for item in products
                if item.get("distance") is not None
                and Decimal(
                    str(item["distance"])
                ) <= distance_limit
            ]

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            pass

    # ==========================================
    # TOTAL COST
    # ==========================================

    for item in products:

        item["total_cost"] = (
            item["price"]
            + item["shipping_cost"]
        )

    # ==========================================
    # RECOMMENDATION SCORE
    # ==========================================

    def recommendation_score(item):

        score = Decimal("0")

        # ======================================
        # PRODUCT DATA
        # ======================================

        name = str(
            item.get(
                "name",
                "",
            )
        ).lower()

        description = str(
            item.get(
                "description",
                "",
            )
        ).lower()

        category = str(
            item.get(
                "category",
                "",
            )
        ).lower()

        brand = str(
            item.get(
                "brand",
                "",
            )
        ).lower()

        product_colour = str(
            item.get(
                "colour",
                "",
            )
        ).lower()

        product_store = str(
            item.get(
                "store",
                "",
            )
        ).lower()

        # ======================================
        # RATING
        # ======================================

        try:

            rating = Decimal(
                str(
                    item.get(
                        "rating",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            rating = Decimal("0")

        score += rating * Decimal("10")

        # ======================================
        # PRICE
        # ======================================

        try:

            price = Decimal(
                str(
                    item.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            price = Decimal("0")

        if price > 0:

            score += (
                Decimal("1000")
                / price
            )

        # ======================================
        # STOCK
        # ======================================

        try:

            stock = int(
                item.get(
                    "stock",
                    0,
                )
                or 0
            )

        except (
            ValueError,
            TypeError,
        ):

            stock = 0

        if stock > 0:

            score += Decimal("5")

        else:

            score -= Decimal("20")

        # ======================================
        # SEARCH RELEVANCE
        # ======================================

        if keyword:

            search_term = keyword.lower()

            if search_term in name:

                score += Decimal("30")

            if search_term in category:

                score += Decimal("15")

            if search_term in brand:

                score += Decimal("10")

            if search_term in description:

                score += Decimal("5")

        # ======================================
        # USER PREFERENCES
        # ======================================

        if preferences:

            # ----------------------------------
            # COLOURS
            # ----------------------------------

            preferred_colours = [
                value.strip().lower()
                for value
                in preferences.colours.split(",")
                if value.strip()
            ]

            for preferred_colour in preferred_colours:

                if (
                    preferred_colour
                    in product_colour
                ):

                    score += Decimal("25")
                    break

            # ----------------------------------
            # STORES
            # ----------------------------------

            preferred_stores = [
                value.strip().lower()
                for value
                in preferences.stores.split(",")
                if value.strip()
            ]

            for preferred_store in preferred_stores:

                if (
                    preferred_store
                    in product_store
                ):

                    score += Decimal("20")
                    break

            # ----------------------------------
            # STYLES
            # ----------------------------------

            preferred_styles = [
                value.strip().lower()
                for value
                in preferences.styles.split(",")
                if value.strip()
            ]

            for preferred_style in preferred_styles:

                if (
                    preferred_style in name
                    or preferred_style in description
                    or preferred_style in category
                ):

                    score += Decimal("20")
                    break

            # ----------------------------------
            # HOBBIES
            # ----------------------------------

            preferred_hobbies = [
                value.strip().lower()
                for value
                in preferences.hobbies.split(",")
                if value.strip()
            ]

            for hobby in preferred_hobbies:

                if (
                    hobby in name
                    or hobby in description
                    or hobby in category
                ):

                    score += Decimal("10")
                    break

        return score

    # ==========================================
    # SORTING
    # ==========================================

    if sort == "price_asc":

        products.sort(
            key=lambda item:
            item["price"]
        )

    elif sort == "price_desc":

        products.sort(
            key=lambda item:
            item["price"],
            reverse=True,
        )

    elif sort == "shipping_asc":

        products.sort(
            key=lambda item:
            item["shipping_cost"]
        )

    elif sort == "name_asc":

        products.sort(
            key=lambda item:
            str(
                item.get(
                    "name",
                    "",
                )
            ).lower()
        )

    elif sort == "distance_asc":

        products.sort(
            key=lambda item:
            (
                item["distance"]
                if item.get("distance")
                is not None
                else Decimal("999999")
            )
        )

    elif sort == "recommendation":

        products.sort(
            key=recommendation_score,
            reverse=True,
        )

    # ==========================================
    # ADD RECOMMENDATION SCORE
    # ==========================================

    if sort == "recommendation":

        for item in products:

            item["recommendation_score"] = (
                recommendation_score(item)
            )

    # ==========================================
    # CONTEXT
    # ==========================================

    context = {

        "products": products,

        "keyword": keyword,

        "budget": budget,

        "colour": colour,

        "size": size,

        "store": store,

        "location": location,

        "max_shipping": max_shipping,

        "max_distance": max_distance,

        "sort": sort,

        "user_latitude": user_latitude,

        "user_longitude": user_longitude,

        "api_error": api_error,

        "preferences": preferences,
    }

    return render(
        request,
        "products/search.html",
        context,
    )

@login_required
def detail(request, product_id):

    try:

        product = get_product(
            product_id
        )

        # ======================================
        # NORMALISE PRICE
        # ======================================

        try:

            product["price"] = Decimal(
                str(
                    product.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["price"] = Decimal("0")

        # ======================================
        # NORMALISE SHIPPING
        # ======================================

        try:

            product["shipping_cost"] = Decimal(
                str(
                    product.get(
                        "shipping_cost",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["shipping_cost"] = Decimal("0")

        # ======================================
        # TOTAL COST
        # ======================================

        product["total_cost"] = (
            product["price"]
            + product["shipping_cost"]
        )

        # ======================================
        # RETURN URL
        # ======================================

        return_url = request.GET.get(
            "return_url",
            "",
        )

        return render(
            request,
            "products/detail.html",
            {
                "product": product,
                "return_url": return_url,
            },
        )

    except StoreAPIError as exc:

        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error": str(exc),
            },
        )
        