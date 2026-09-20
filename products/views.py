from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from preferences.models import Preference

from .services.store_api import (
    search_products,
    get_product,
    get_store_location,
    StoreAPIError,
    _extract_store_id,
    _cache_product,
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

    images = product.get("images", [])

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
                    "source",
                ]:

                    value = image.get(field)

                    if isinstance(value, str):

                        value = value.strip()

                        if value:
                            return value

    return ""


# ==========================================================
# DECIMAL HELPER
# ==========================================================

def to_decimal(value, default="0.00"):

    try:

        return Decimal(
            str(value)
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return Decimal(default)


# ==========================================================
# PREFERENCE LIST HELPER
# ==========================================================

def preference_values(value):

    if not value:
        return []

    return [
        item.strip().lower()
        for item in str(value).split(",")
        if item.strip()
    ]


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
    ).strip()

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
                limit=100,
            )

        except StoreAPIError as exc:

            api_error = str(exc)

    # ======================================================
    # NORMALIZE PRODUCT DATA
    # ======================================================

    for item in products:

        item.setdefault(
            "name",
            "Unnamed Product",
        )

        item.setdefault(
            "colour",
            "Not specified",
        )

        item.setdefault(
            "size",
            "Not specified",
        )

        item.setdefault(
            "store",
            "Checkers",
        )

        item.setdefault(
            "location",
            "Location not available",
        )

        item.setdefault(
            "description",
            "",
        )

        item.setdefault(
            "category",
            "Other",
        )

        item.setdefault(
            "brand",
            "Unknown",
        )

        item.setdefault(
            "url",
            "",
        )

        item.setdefault(
            "images",
            [],
        )

        item["image"] = get_product_image(
            item
        )

        # ==================================================
        # CURRENT PRICE
        # ==================================================

        item["price"] = to_decimal(
            item.get("price", 0)
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # REGULAR PRICE
        # ==================================================

        item["regular_price"] = to_decimal(
            item.get(
                "regular_price",
                item["price"],
            )
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # SALE PRICE
        # ==================================================

        sale_price = item.get(
            "sale_price"
        )

        if sale_price is not None:

            item["sale_price"] = to_decimal(
                sale_price
            ).quantize(
                Decimal("0.01")
            )

        else:

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
        # DISCOUNT
        # ==================================================

        item["discount_amount"] = to_decimal(
            item.get(
                "discount_amount",
                0,
            )
        ).quantize(
            Decimal("0.01")
        )

        item["discount_percentage"] = to_decimal(
            item.get(
                "discount_percentage",
                0,
            )
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # EXPIRY
        # ==================================================

        item.setdefault(
            "deal_expiry",
            "",
        )

        # ==================================================
        # SHIPPING
        # ==================================================

        item["shipping_cost"] = to_decimal(
            item.get(
                "shipping_cost",
                0,
            )
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # RATING
        # ==================================================

        item["rating"] = to_decimal(
            item.get(
                "rating",
                0,
            )
        ).quantize(
            Decimal("0.01")
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

        if item["stock"] < 0:
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
    # ======================================================

    if budget:

        try:

            max_budget = Decimal(
                budget
            )

            filtered_products = []

            for item in products:

                effective_price = (
                    item["sale_price"]
                    if (
                        item.get("on_sale")
                        and item.get("sale_price")
                        is not None
                    )
                    else item["price"]
                )

                if effective_price <= max_budget:

                    filtered_products.append(
                        item
                    )

            products = filtered_products

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
            if colour_lower in str(
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
            if size_lower in str(
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
            if store_lower in str(
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
            if location_lower in str(
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
    # MAX DISTANCE
    # ======================================================

    if max_distance:

        try:

            distance_limit = Decimal(
                max_distance
            )

            filtered_products = []

            for item in products:

                distance = item.get(
                    "distance"
                )

                if distance is None:
                    continue

                try:

                    distance = Decimal(
                        str(distance)
                    )

                except (
                    ValueError,
                    TypeError,
                    InvalidOperation,
                ):

                    continue

                if distance <= distance_limit:

                    filtered_products.append(
                        item
                    )

            products = filtered_products

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

        effective_price = (
            item["sale_price"]
            if (
                item.get("on_sale")
                and item.get("sale_price")
                is not None
            )
            else item["price"]
        )

        item["total_cost"] = (
            effective_price
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

        rating = to_decimal(
            item.get(
                "rating",
                0,
            )
        )

        score += (
            rating
            * Decimal("10")
        )

        # --------------------------------------------------
        # EFFECTIVE PRICE
        # --------------------------------------------------

        price = (
            item["sale_price"]
            if (
                item.get("on_sale")
                and item.get("sale_price")
                is not None
            )
            else item["price"]
        )

        if price > 0:

            score += (
                Decimal("1000")
                / price
            )

        # --------------------------------------------------
        # STOCK
        # --------------------------------------------------

        stock = item.get(
            "stock",
            0,
        )

        try:

            stock = int(stock)

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

            preferred_colours = (
                preference_values(
                    getattr(
                        preferences,
                        "colours",
                        "",
                    )
                )
            )

            for preferred_colour in preferred_colours:

                if preferred_colour in product_colour:

                    score += Decimal("25")
                    break

            preferred_stores = (
                preference_values(
                    getattr(
                        preferences,
                        "stores",
                        "",
                    )
                )
            )

            for preferred_store in preferred_stores:

                if preferred_store in product_store:

                    score += Decimal("20")
                    break

            preferred_styles = (
                preference_values(
                    getattr(
                        preferences,
                        "styles",
                        "",
                    )
                )
            )

            for preferred_style in preferred_styles:

                if (
                    preferred_style in name
                    or preferred_style in description
                    or preferred_style in category
                ):

                    score += Decimal("20")
                    break

            preferred_hobbies = (
                preference_values(
                    getattr(
                        preferences,
                        "hobbies",
                        "",
                    )
                )
            )

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
            key=lambda item: (
                item["sale_price"]
                if (
                    item.get("on_sale")
                    and item.get("sale_price")
                    is not None
                )
                else item["price"]
            )
        )

    elif sort == "price_desc":

        products.sort(
            key=lambda item: (
                item["sale_price"]
                if (
                    item.get("on_sale")
                    and item.get("sale_price")
                    is not None
                )
                else item["price"]
            ),
            reverse=True,
        )

    elif sort == "shipping_asc":

        products.sort(
            key=lambda item:
                item["shipping_cost"]
        )

    elif sort == "name_asc":

        products.sort(
            key=lambda item: str(
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

    product_id = str(
        product_id or ""
    ).strip()

    if not product_id:

        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error":
                    "No product ID was provided.",
            },
        )

    try:

        product = get_product(
            product_id
        )

        # ==================================================
        # STORE LOCATION
        # ==================================================

        store_id = _extract_store_id(
            product
        )

        if (
            store_id
            and product.get("location")
            in {
                None,
                "",
                "Location not available",
                "Location temporarily unavailable",
            }
        ):

            try:

                location = get_store_location(
                    store_id
                )

                if location:

                    product["location"] = (
                        location
                    )

                    # Keep Redis product cache
                    # synchronized with the resolved
                    # location.
                    _cache_product(
                        product
                    )

            except Exception as exc:

                print(
                    f"STORE LOCATION ERROR "
                    f"for {store_id}: {exc}"
                )

        # ==================================================
        # DEFAULTS
        # ==================================================

        product.setdefault(
            "name",
            "Unnamed Product",
        )

        product.setdefault(
            "description",
            "",
        )

        product.setdefault(
            "brand",
            "Unknown",
        )

        product.setdefault(
            "category",
            "Other",
        )

        product.setdefault(
            "colour",
            "Not specified",
        )

        product.setdefault(
            "size",
            "Not specified",
        )

        product.setdefault(
            "store",
            "Checkers",
        )

        product.setdefault(
            "location",
            "Location not available",
        )

        product.setdefault(
            "deal_expiry",
            "",
        )

        product.setdefault(
            "url",
            "",
        )

        product["image"] = get_product_image(
            product
        )

        # ==================================================
        # PRICE
        # ==================================================

        product["price"] = to_decimal(
            product.get(
                "price",
                0,
            )
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # REGULAR PRICE
        # ==================================================

        product["regular_price"] = to_decimal(
            product.get(
                "regular_price",
                product["price"],
            )
        ).quantize(
            Decimal("0.01")
        )

        # ==================================================
        # SALE PRICE
        # ==================================================

        if product.get(
            "sale_price"
        ) is not None:

            product["sale_price"] = (
                to_decimal(
                    product["sale_price"]
                ).quantize(
                    Decimal("0.01")
                )
            )

        else:

            product["sale_price"] = None

        # ==================================================
        # ON SALE
        # ==================================================

        product["on_sale"] = bool(
            product.get(
                "on_sale",
                False,
            )
        )

        # ==================================================
        # DISCOUNT
        # ==================================================

        product["discount_amount"] = (
            to_decimal(
                product.get(
                    "discount_amount",
                    0,
                )
            ).quantize(
                Decimal("0.01")
            )
        )

        product["discount_percentage"] = (
            to_decimal(
                product.get(
                    "discount_percentage",
                    0,
                )
            ).quantize(
                Decimal("0.01")
            )
        )

        # ==================================================
        # SHIPPING
        # ==================================================

        product["shipping_cost"] = (
            to_decimal(
                product.get(
                    "shipping_cost",
                    0,
                )
            ).quantize(
                Decimal("0.01")
            )
        )

        # ==================================================
        # STOCK
        # ==================================================

        try:

            product["stock"] = int(
                product.get(
                    "stock",
                    0,
                )
                or 0
            )

        except (
            ValueError,
            TypeError,
        ):

            product["stock"] = 0

        # ==================================================
        # TOTAL COST
        # ==================================================

        effective_price = (
            product["sale_price"]
            if (
                product.get("on_sale")
                and product.get("sale_price")
                is not None
            )
            else product["price"]
        )

        product["total_cost"] = (
            effective_price
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
