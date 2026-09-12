from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from preferences.models import Preference

from .services.store_api import (
    search_products,
    get_product,
    StoreAPIError,
)


# ==========================================================
# IMAGE HELPER
# ==========================================================

def get_product_image(product):

    fields = [
        "image",
        "imageURL",
        "imageUrl",
        "imageProductCardURL",
        "imageProductCardUrl",
        "imagePDPURL",
        "imagePDPUrl",
        "thumbnail",
        "thumbnailURL",
        "thumbnailUrl",
        "productImage",
        "productImageUrl",
        "mainImage",
        "mainImageUrl",
    ]

    for field in fields:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

    images = product.get(
        "images",
        []
    )

    if isinstance(images, list):

        for image in images:

            if isinstance(image, str):

                image = image.strip()

                if image:
                    return image

            elif isinstance(image, dict):

                for field in [
                    "url",
                    "image",
                    "imageUrl",
                    "imageURL",
                    "src",
                ]:

                    value = image.get(field)

                    if isinstance(value, str):

                        value = value.strip()

                        if value:
                            return value

    return ""


# ==========================================================
# SEARCH
# ==========================================================

@login_required
def search(request):

    # ======================================================
    # USER PREFERENCES
    # ======================================================

    try:

        preferences = Preference.objects.get(
            user=request.user
        )

    except Preference.DoesNotExist:

        preferences = None

    # ======================================================
    # SEARCH PARAMETERS
    # ======================================================

    keyword = request.GET.get(
        "keyword",
        "",
    ).strip()

    budget = request.GET.get(
        "budget",
        "",
    ).strip()

    colour = request.GET.get(
        "colour",
        "",
    ).strip()

    size = request.GET.get(
        "size",
        "",
    ).strip()

    store = request.GET.get(
        "store",
        "",
    ).strip()

    location = request.GET.get(
        "location",
        "",
    ).strip()

    max_shipping = request.GET.get(
        "max_shipping",
        "",
    ).strip()

    max_distance = request.GET.get(
        "max_distance",
        "",
    ).strip()

    sort = request.GET.get(
        "sort",
        "price_asc",
    )

    user_latitude = request.GET.get(
        "user_latitude",
        "",
    ).strip()

    user_longitude = request.GET.get(
        "user_longitude",
        "",
    ).strip()

    products = []

    api_error = None

    # ======================================================
    # SEARCH API
    # ======================================================

    if keyword:

        try:

            products = search_products(
                keyword=keyword,
                limit=30,
            )

        except StoreAPIError as exc:

            api_error = str(exc)

    # ======================================================
    # NORMALISE PRODUCT DATA
    # ======================================================

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

        item["image"] = get_product_image(
            item
        )

        item.setdefault(
            "images",
            [],
        )

        item.setdefault(
            "url",
            "",
        )

        # ==================================================
        # CURRENT PRICE
        # ==================================================

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

            item["price"] = Decimal(
                "0.00"
            )

        # ==================================================
        # REGULAR PRICE
        # ==================================================

        try:

            item["regular_price"] = Decimal(
                str(
                    item.get(
                        "regular_price",
                        item["price"],
                    )
                    or item["price"]
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            item["regular_price"] = item[
                "price"
            ]

        # ==================================================
        # SALE PRICE
        # ==================================================

        sale_price = item.get(
            "sale_price"
        )

        if sale_price is not None:

            try:

                item["sale_price"] = Decimal(
                    str(sale_price)
                )

            except (
                ValueError,
                TypeError,
                InvalidOperation,
            ):

                item["sale_price"] = None

        # ==================================================
        # ON SALE
        # ==================================================

        item["on_sale"] = bool(
            item.get(
                "on_sale",
                False,
            )
        )

        # ==================================================
        # DISCOUNT AMOUNT
        # ==================================================

        try:

            item["discount_amount"] = Decimal(
                str(
                    item.get(
                        "discount_amount",
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

            item["discount_amount"] = Decimal(
                "0.00"
            )

        # ==================================================
        # DISCOUNT PERCENTAGE
        # ==================================================

        try:

            item["discount_percentage"] = Decimal(
                str(
                    item.get(
                        "discount_percentage",
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

            item["discount_percentage"] = Decimal(
                "0.00"
            )

        # ==================================================
        # DEAL EXPIRY
        # ==================================================

        item.setdefault(
            "deal_expiry",
            "",
        )

        # ==================================================
        # SHIPPING
        # ==================================================

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

            item["shipping_cost"] = Decimal(
                "0.00"
            )

        # ==================================================
        # RATING
        # ==================================================

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

            item["rating"] = Decimal(
                "0.00"
            )

        # ==================================================
        # STOCK
        # ==================================================

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

        # ==================================================
        # DISTANCE
        # ==================================================

        item.setdefault(
            "distance",
            None,
        )

    # ======================================================
    # BUDGET FILTER
    #
    # IMPORTANT:
    # This uses the sale price when a product is on sale.
    # ======================================================

    if budget:

        try:

            max_budget = Decimal(
                budget
            )

            products = [
                item
                for item in products
                if item["price"]
                <= max_budget
            ]

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            pass

    # ======================================================
    # COLOUR FILTER
    # ======================================================

    if colour:

        colour_lower = colour.lower()

        products = [
            item
            for item in products
            if colour_lower
            in str(
                item.get(
                    "colour",
                    "",
                )
            ).lower()
        ]

    # ======================================================
    # SIZE FILTER
    # ======================================================

    if size:

        size_lower = size.lower()

        products = [
            item
            for item in products
            if size_lower
            in str(
                item.get(
                    "size",
                    "",
                )
            ).lower()
        ]

    # ======================================================
    # STORE FILTER
    # ======================================================

    if store:

        store_lower = store.lower()

        products = [
            item
            for item in products
            if store_lower
            in str(
                item.get(
                    "store",
                    "",
                )
            ).lower()
        ]

    # ======================================================
    # LOCATION FILTER
    # ======================================================

    if location:

        location_lower = location.lower()

        products = [
            item
            for item in products
            if location_lower
            in str(
                item.get(
                    "location",
                    "",
                )
            ).lower()
        ]

    # ======================================================
    # SHIPPING FILTER
    # ======================================================

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

    # ======================================================
    # DISTANCE
    # ======================================================

    for item in products:

        item.setdefault(
            "distance",
            None,
        )

    # ======================================================
    # MAX DISTANCE
    # ======================================================

    if max_distance:

        try:

            distance_limit = Decimal(
                max_distance
            )

            products = [
                item
                for item in products
                if item.get(
                    "distance"
                ) is not None
                and Decimal(
                    str(
                        item["distance"]
                    )
                ) <= distance_limit
            ]

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            pass

    # ======================================================
    # TOTAL COST
    # ======================================================

    for item in products:

        item["total_cost"] = (
            item["price"]
            + item["shipping_cost"]
        )

    # ======================================================
    # RECOMMENDATION SCORE
    # ======================================================

    def recommendation_score(item):

        score = Decimal("0")

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

        # --------------------------------------------------
        # RATING
        # --------------------------------------------------

        rating = item.get(
            "rating",
            Decimal("0")
        )

        try:

            rating = Decimal(
                str(rating)
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            rating = Decimal("0")

        score += (
            rating
            * Decimal("10")
        )

        # --------------------------------------------------
        # PRICE
        #
        # Uses current/sale price.
        # --------------------------------------------------

        price = item.get(
            "price",
            Decimal("0")
        )

        try:

            price = Decimal(
                str(price)
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

        # --------------------------------------------------
        # STOCK
        # --------------------------------------------------

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

        # --------------------------------------------------
        # SEARCH RELEVANCE
        # --------------------------------------------------

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

        # --------------------------------------------------
        # USER PREFERENCES
        # --------------------------------------------------

        if preferences:

            preferred_colours = [
                value.strip().lower()
                for value
                in preferences.colours.split(",")
                if value.strip()
            ]

            for preferred_colour in preferred_colours:

                if preferred_colour in product_colour:

                    score += Decimal("25")
                    break

            preferred_stores = [
                value.strip().lower()
                for value
                in preferences.stores.split(",")
                if value.strip()
            ]

            for preferred_store in preferred_stores:

                if preferred_store in product_store:

                    score += Decimal("20")
                    break

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

    # ======================================================
    # SORT
    # ======================================================

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
            key=lambda item: (
                item["distance"]
                if item.get(
                    "distance"
                ) is not None
                else Decimal("999999")
            )
        )

    elif sort == "recommendation":

        products.sort(
            key=recommendation_score,
            reverse=True,
        )

    # ======================================================
    # RECOMMENDATION SCORE
    # ======================================================

    if sort == "recommendation":

        for item in products:

            item["recommendation_score"] = (
                recommendation_score(item)
            )

    # ======================================================
    # CONTEXT
    # ======================================================

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


# ==========================================================
# DETAIL
# ==========================================================

@login_required
def detail(request, product_id):

    try:

        product = get_product(
            product_id
        )

        product["image"] = get_product_image(
            product
        )

        # ==================================================
        # PRICE
        # ==================================================

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

            product["price"] = Decimal(
                "0.00"
            )

        # ==================================================
        # REGULAR PRICE
        # ==================================================

        try:

            product["regular_price"] = Decimal(
                str(
                    product.get(
                        "regular_price",
                        product["price"],
                    )
                    or product["price"]
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["regular_price"] = (
                product["price"]
            )

        # ==================================================
        # SALE PRICE
        # ==================================================

        if product.get(
            "sale_price"
        ) is not None:

            try:

                product["sale_price"] = Decimal(
                    str(
                        product["sale_price"]
                    )
                )

            except (
                ValueError,
                TypeError,
                InvalidOperation,
            ):

                product["sale_price"] = None

        # ==================================================
        # SHIPPING
        # ==================================================

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

            product["shipping_cost"] = Decimal(
                "0.00"
            )

        # ==================================================
        # TOTAL
        # ==================================================

        product["total_cost"] = (
            product["price"]
            + product["shipping_cost"]
        )

        # ==================================================
        # RETURN URL
        # ==================================================

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
