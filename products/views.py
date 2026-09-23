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
    """
    Safely get a product image from different possible
    API response formats.
    """

    images = product.get("images")

    if isinstance(images, list) and images:
        first_image = images[0]

        if isinstance(first_image, dict):
            return (
                first_image.get("url")
                or first_image.get("src")
                or first_image.get("image")
            )

        if isinstance(first_image, str):
            return first_image

    return (
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or ""
    )


# ==========================================================
# DECIMAL HELPER
# ==========================================================

def to_decimal(value, default=Decimal("0")):
    """
    Convert a value safely to Decimal.
    """

    if value is None:
        return default

    if isinstance(value, Decimal):
        return value

    try:
        value = str(value).replace(",", "").replace("R", "").strip()

        if not value:
            return default

        return Decimal(value)

    except (InvalidOperation, ValueError, TypeError):
        return default


# ==========================================================
# PREFERENCE HELPER
# ==========================================================

def preference_values(value):
    """
    Convert preferences into a clean lowercase list.

    Supports:

        ["Black", "Blue"]

    and:

        "Black,Blue"

    and:

        "Black, Blue"
    """

    if not value:
        return []

    # Preferences stored as a Python list/tuple
    if isinstance(value, (list, tuple)):
        return [
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        ]

    # Preferences stored as a comma-separated string
    return [
        item.strip().lower()
        for item in str(value).split(",")
        if item.strip()
    ]


# ==========================================================
# AI RECOMMENDATION SCORE
# ==========================================================

def recommendation_score(item, preferences=None, keyword=""):
    """
    Calculate a personalized recommendation score.

    The score is based primarily on the user's saved
    preferences:

        Colour  = 25 points
        Store   = 25 points
        Style   = 20 points
        Hobby   = 15 points

    Additional signals:

        Keyword match = up to 10 points
        Rating        = up to 5 points
        In stock      = 2 points
        On sale       = 3 points

    Maximum score = 100.
    """

    score = Decimal("0")

    matched_preferences = []

    # ------------------------------------------------------
    # PRODUCT INFORMATION
    # ------------------------------------------------------

    name = str(
        item.get("name", "")
    ).lower()

    description = str(
        item.get("description", "")
    ).lower()

    category = str(
        item.get("category", "")
    ).lower()

    brand = str(
        item.get("brand", "")
    ).lower()

    product_colour = str(
        item.get("colour", "")
    ).lower()

    product_store = str(
        item.get("store", "")
    ).lower()

    product_size = str(
        item.get("size", "")
    ).lower()

    # Everything searchable about the product
    product_text = " ".join(
        [
            name,
            description,
            category,
            brand,
            product_colour,
            product_store,
            product_size,
        ]
    )

    # ------------------------------------------------------
    # USER PREFERENCES
    # ------------------------------------------------------

    if preferences:

        preferred_colours = preference_values(
            getattr(
                preferences,
                "colours",
                []
            )
        )

        preferred_stores = preference_values(
            getattr(
                preferences,
                "stores",
                []
            )
        )

        preferred_styles = preference_values(
            getattr(
                preferences,
                "styles",
                []
            )
        )

        preferred_hobbies = preference_values(
            getattr(
                preferences,
                "hobbies",
                []
            )
        )

        # --------------------------------------------------
        # COLOUR MATCH
        # --------------------------------------------------

        for preferred_colour in preferred_colours:

            if preferred_colour in product_colour:

                score += Decimal("25")

                matched_preferences.append(
                    f"Colour: {preferred_colour.title()}"
                )

                break

        # --------------------------------------------------
        # STORE MATCH
        # --------------------------------------------------

        for preferred_store in preferred_stores:

            if (
                preferred_store in product_store
                or product_store in preferred_store
            ):

                score += Decimal("25")

                matched_preferences.append(
                    f"Store: {preferred_store.title()}"
                )

                break

        # --------------------------------------------------
        # STYLE MATCH
        # --------------------------------------------------

        for preferred_style in preferred_styles:

            if preferred_style in product_text:

                score += Decimal("20")

                matched_preferences.append(
                    f"Style: {preferred_style.title()}"
                )

                break

        # --------------------------------------------------
        # HOBBY MATCH
        # --------------------------------------------------

        for hobby in preferred_hobbies:

            if hobby in product_text:

                score += Decimal("15")

                matched_preferences.append(
                    f"Hobby: {hobby.title()}"
                )

                break

    # ------------------------------------------------------
    # SEARCH KEYWORD MATCH
    # ------------------------------------------------------

    if keyword:

        search_term = str(
            keyword
        ).strip().lower()

        if search_term:

            if search_term in name:

                score += Decimal("5")

            elif search_term in category:

                score += Decimal("3")

            elif search_term in brand:

                score += Decimal("2")

    # ------------------------------------------------------
    # PRODUCT RATING
    # ------------------------------------------------------

    rating = to_decimal(
        item.get("rating", 0)
    )

    # Limit rating contribution to 5 points
    if rating > Decimal("5"):
        rating = Decimal("5")

    if rating < Decimal("0"):
        rating = Decimal("0")

    score += rating

    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

    try:

        stock = int(
            item.get("stock", 0) or 0
        )

    except (ValueError, TypeError):

        stock = 0

    if stock > 0:

        score += Decimal("2")

    # ------------------------------------------------------
    # SALE
    # ------------------------------------------------------

    if item.get("on_sale"):

        score += Decimal("3")

    # ------------------------------------------------------
    # SAVE MATCH INFORMATION
    # ------------------------------------------------------

    item["matched_preferences"] = matched_preferences

    # ------------------------------------------------------
    # KEEP SCORE BETWEEN 0 AND 100
    # ------------------------------------------------------

    score = max(
        Decimal("0"),
        min(
            score,
            Decimal("100")
        )
    )

    return score


# ==========================================================
# SEARCH PRODUCTS
# ==========================================================

@login_required
def search(request):

    # ======================================================
    # LOAD USER PREFERENCES
    # ======================================================

    try:

        preferences = Preference.objects.get(
            user=request.user
        )

    except Preference.DoesNotExist:

        preferences = None

    # ======================================================
    # GET SEARCH PARAMETERS
    # ======================================================

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
        "price_asc"
    ).strip()

    user_latitude = request.GET.get(
        "user_latitude",
        ""
    ).strip()

    user_longitude = request.GET.get(
        "user_longitude",
        ""
    ).strip()

    # ======================================================
    # START WITH EMPTY PRODUCTS
    # ======================================================

    products = []

    error = None

    # ======================================================
    # SEARCH RETAILER API
    # ======================================================

    if keyword:

        try:

            products = search_products(
                keyword=keyword,
                limit=100,
                latitude=(
                    float(user_latitude)
                    if user_latitude
                    else None
                ),
                longitude=(
                    float(user_longitude)
                    if user_longitude
                    else None
                ),
                radius_km=(
                    float(max_distance)
                    if max_distance
                    else None
                ),
            )

        except StoreAPIError as exc:

            error = str(exc)

            products = []

        except Exception as exc:

            error = (
                "Unable to retrieve products. "
                f"{str(exc)}"
            )

            products = []

    # ======================================================
    # NORMALIZE PRODUCTS
    # ======================================================

    normalized_products = []

    for product in products:

        if not isinstance(product, dict):

            continue

        # --------------------------------------------------
        # BASIC INFORMATION
        # --------------------------------------------------

        product_name = str(
            product.get(
                "name",
                ""
            )
        ).strip()

        product_colour = str(
            product.get(
                "colour",
                ""
            )
        ).strip()

        product_size = str(
            product.get(
                "size",
                ""
            )
        ).strip()

        product_store = str(
            product.get(
                "store",
                ""
            )
        ).strip()

        store_location_data = product.get("location") or {}

        if not isinstance(store_location_data, dict):
            store_location_data = {}

        product_location = str(
            store_location_data.get("address")
            or store_location_data.get("name")
            or store_location_data.get("city")
            or product.get("location", "")
        ).strip()

        store_name = str(
            store_location_data.get("name")
            or product.get("store")
            or ""
        ).strip()

        store_address = str(
            store_location_data.get("address")
            or ""
        ).strip()

        description = str(
            product.get(
                "description",
                ""
            )
        ).strip()

        category = str(
            product.get(
                "category",
                ""
            )
        ).strip()

        brand = str(
            product.get(
                "brand",
                ""
            )
        ).strip()

        url = str(
            product.get(
                "url",
                ""
            )
        ).strip()

        # --------------------------------------------------
        # IMAGE
        # --------------------------------------------------

        image = get_product_image(
            product
        )

        # --------------------------------------------------
        # PRICE
        # --------------------------------------------------

        price = to_decimal(
            product.get(
                "price",
                0
            )
        )

        regular_price = to_decimal(
            product.get(
                "regular_price",
                price
            )
        )

        sale_price_value = product.get(
            "sale_price"
        )

        if sale_price_value is not None:

            sale_price = to_decimal(
                sale_price_value
            )

        else:

            sale_price = None

        # --------------------------------------------------
        # ON SALE
        # --------------------------------------------------

        on_sale = bool(
            product.get(
                "on_sale",
                False
            )
        )

        # If sale price is lower than regular price,
        # automatically mark it as on sale.

        if (
            sale_price is not None
            and sale_price > 0
            and regular_price > 0
            and sale_price < regular_price
        ):

            on_sale = True

        # --------------------------------------------------
        # FINAL PRICE
        # --------------------------------------------------

        if (
            on_sale
            and sale_price is not None
            and sale_price > 0
        ):

            final_price = sale_price

        else:

            final_price = price

        # --------------------------------------------------
        # DISCOUNT
        # --------------------------------------------------

        discount_amount = to_decimal(
            product.get(
                "discount_amount",
                0
            )
        )

        discount_percentage = to_decimal(
            product.get(
                "discount_percentage",
                0
            )
        )

        if (
            discount_amount <= 0
            and regular_price > final_price
        ):

            discount_amount = (
                regular_price - final_price
            )

        if (
            discount_percentage <= 0
            and regular_price > 0
            and final_price < regular_price
        ):

            discount_percentage = (
                (
                    regular_price - final_price
                )
                / regular_price
            ) * Decimal("100")

        # --------------------------------------------------
        # SHIPPING
        # --------------------------------------------------

        shipping_cost = to_decimal(
            product.get(
                "shipping_cost",
                0
            )
        )

        # --------------------------------------------------
        # RATING
        # --------------------------------------------------

        rating = to_decimal(
            product.get(
                "rating",
                0
            )
        )

        # --------------------------------------------------
        # STOCK
        # --------------------------------------------------

        stock = product.get(
            "stock",
            0
        )

        try:

            stock = int(
                stock
            )

        except (ValueError, TypeError):

            stock = 0

        # --------------------------------------------------
        # DISTANCE
        # --------------------------------------------------

        raw_distance = product.get(
            "distance_km",
            product.get("distance")
        )

        distance = (
            to_decimal(raw_distance)
            if raw_distance is not None
            else None
        )

        # --------------------------------------------------
        # TOTAL COST
        # --------------------------------------------------

        total_cost = (
            final_price
            + shipping_cost
        )

        # --------------------------------------------------
        # BUILD NORMALIZED PRODUCT
        # --------------------------------------------------

        normalized_product = {

            **product,

            "name": product_name,

            "colour": product_colour,

            "size": product_size,

            "store": store_name or product_store,

            "location": product_location,

            "store_name": store_name or product_store,

            "store_address": store_address,

            "store_location": store_location_data,

            "description": description,

            "category": category,

            "brand": brand,

            "url": url,

            "image": image,

            "price": final_price,

            "regular_price": regular_price,

            "sale_price": sale_price,

            "on_sale": on_sale,

            "discount_amount": discount_amount,

            "discount_percentage": discount_percentage,

            "shipping_cost": shipping_cost,

            "rating": rating,

            "stock": stock,

            "distance": distance,

            "distance_km": distance,

            "total_cost": total_cost,

            "recommendation_score": Decimal("0"),

            "matched_preferences": [],

        }

        normalized_products.append(
            normalized_product
        )

    # Replace original list
    products = normalized_products

    # ======================================================
    # BUDGET FILTER
    # ======================================================

    budget_value = None

    if budget:

        try:

            budget_value = Decimal(
                budget
            )

        except InvalidOperation:

            budget_value = None

    if budget_value is not None:

        products = [
            product
            for product in products
            if product["total_cost"] <= budget_value
        ]

    # ======================================================
    # COLOUR FILTER
    # ======================================================

    if colour:

        colour_lower = colour.lower()

        products = [
            product
            for product in products
            if colour_lower in str(
                product.get(
                    "colour",
                    ""
                )
            ).lower()
        ]

    # ======================================================
    # SIZE FILTER
    # ======================================================

    if size:

        size_lower = size.lower()

        products = [
            product
            for product in products
            if size_lower in str(
                product.get(
                    "size",
                    ""
                )
            ).lower()
        ]

    # ======================================================
    # STORE FILTER
    # ======================================================

    if store:

        store_lower = store.lower()

        products = [
            product
            for product in products
            if store_lower in str(
                product.get(
                    "store",
                    ""
                )
            ).lower()
        ]

    # ======================================================
    # LOCATION FILTER
    # ======================================================

    if location:

        location_lower = location.lower()

        products = [
            product
            for product in products
            if location_lower in str(
                product.get(
                    "location",
                    ""
                )
            ).lower()
        ]

    # ======================================================
    # SHIPPING FILTER
    # ======================================================

    max_shipping_value = None

    if max_shipping:

        try:

            max_shipping_value = Decimal(
                max_shipping
            )

        except InvalidOperation:

            max_shipping_value = None

    if max_shipping_value is not None:

        products = [
            product
            for product in products
            if product["shipping_cost"]
            <= max_shipping_value
        ]

    # ======================================================
    # DISTANCE FILTER
    # ======================================================

    max_distance_value = None

    if max_distance:

        try:

            max_distance_value = Decimal(
                max_distance
            )

        except InvalidOperation:

            max_distance_value = None

    if max_distance_value is not None:

        products = [
            product
            for product in products
            if (
                product.get("distance") is not None
                and product["distance"] <= max_distance_value
            )
        ]

    # ======================================================
    # SORTING
    # ======================================================

    if sort == "price_asc":

        products.sort(
            key=lambda product: product.get(
                "price",
                Decimal("0")
            )
        )

    elif sort == "price_desc":

        products.sort(
            key=lambda product: product.get(
                "price",
                Decimal("0")
            ),
            reverse=True,
        )

    elif sort == "shipping_asc":

        products.sort(
            key=lambda product: product.get(
                "shipping_cost",
                Decimal("0")
            )
        )

    elif sort == "name_asc":

        products.sort(
            key=lambda product: str(
                product.get(
                    "name",
                    ""
                )
            ).lower()
        )

    elif sort == "distance_asc":

        products.sort(
            key=lambda product: (
                product.get("distance")
                if product.get("distance") is not None
                else Decimal("999999")
            )
        )

    # ======================================================
    # AI RECOMMENDATION
    # ======================================================

    elif sort == "recommendation":

        # --------------------------------------------------
        # Calculate score ONCE for every product
        # --------------------------------------------------

        for product in products:

            product["recommendation_score"] = (
                recommendation_score(
                    product,
                    preferences=preferences,
                    keyword=keyword,
                )
            )

        # --------------------------------------------------
        # Sort highest AI score first
        # --------------------------------------------------

        products.sort(
            key=lambda product: product.get(
                "recommendation_score",
                Decimal("0")
            ),
            reverse=True,
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

        "preferences": preferences,

        "error": error,

        "product_count": len(
            products
        ),
    }

    # ======================================================
    # RENDER
    # ======================================================

    return render(
        request,
        "products/search.html",
        context
    )


# ==========================================================
# PRODUCT DETAIL
# ==========================================================

@login_required
def detail(request, product_id):

    try:

        # ==================================================
        # GET PRODUCT
        # ==================================================

        product = get_product(
            product_id
        )

        if not product:

            return render(
                request,
                "products/detail.html",
                {
                    "product": None,
                    "error": "Product not found.",
                }
            )

        # ==================================================
        # STORE ID
        # ==================================================

        store_id = _extract_store_id(
            product
        )

        # ==================================================
        # STORE LOCATION
        # ==================================================

        store_location = None

        if store_id:

            try:

                store_location = (
                    get_store_location(
                        store_id
                    )
                )

            except Exception:

                store_location = None

        # ==================================================
        # NORMALIZE PRODUCT
        # ==================================================

        product_name = str(
            product.get(
                "name",
                ""
            )
        ).strip()

        product_image = get_product_image(
            product
        )

        # ==================================================
        # PRICE
        # ==================================================

        price = to_decimal(
            product.get(
                "price",
                0
            )
        )

        regular_price = to_decimal(
            product.get(
                "regular_price",
                price
            )
        )

        sale_price_value = product.get(
            "sale_price"
        )

        if sale_price_value is not None:

            sale_price = to_decimal(
                sale_price_value
            )

        else:

            sale_price = None

        # ==================================================
        # SALE
        # ==================================================

        on_sale = bool(
            product.get(
                "on_sale",
                False
            )
        )

        if (
            sale_price is not None
            and sale_price > 0
            and regular_price > 0
            and sale_price < regular_price
        ):

            on_sale = True

        # ==================================================
        # FINAL PRICE
        # ==================================================

        if (
            on_sale
            and sale_price is not None
            and sale_price > 0
        ):

            final_price = sale_price

        else:

            final_price = price

        # ==================================================
        # DISCOUNT
        # ==================================================

        discount_amount = to_decimal(
            product.get(
                "discount_amount",
                0
            )
        )

        discount_percentage = to_decimal(
            product.get(
                "discount_percentage",
                0
            )
        )

        if (
            discount_amount <= 0
            and regular_price > final_price
        ):

            discount_amount = (
                regular_price - final_price
            )

        if (
            discount_percentage <= 0
            and regular_price > 0
            and final_price < regular_price
        ):

            discount_percentage = (
                (
                    regular_price - final_price
                )
                / regular_price
            ) * Decimal("100")

        # ==================================================
        # SHIPPING
        # ==================================================

        shipping_cost = to_decimal(
            product.get(
                "shipping_cost",
                0
            )
        )

        # ==================================================
        # STOCK
        # ==================================================

        stock = product.get(
            "stock",
            0
        )

        try:

            stock = int(
                stock
            )

        except (ValueError, TypeError):

            stock = 0

        # ==================================================
        # TOTAL
        # ==================================================

        total_cost = (
            final_price
            + shipping_cost
        )

        # ==================================================
        # UPDATE PRODUCT
        # ==================================================

        product["name"] = product_name

        product["image"] = product_image

        product["price"] = final_price

        product["regular_price"] = regular_price

        product["sale_price"] = sale_price

        product["on_sale"] = on_sale

        product["discount_amount"] = (
            discount_amount
        )

        product["discount_percentage"] = (
            discount_percentage
        )

        product["shipping_cost"] = (
            shipping_cost
        )

        product["stock"] = stock

        product["total_cost"] = (
            total_cost
        )

        product["store_location"] = (
            store_location
        )

        # ==================================================
        # CACHE PRODUCT
        # ==================================================

        try:

            _cache_product(
                product
            )

        except Exception:

            pass

        # ==================================================
        # CONTEXT
        # ==================================================

        context = {

            "product": product,

            "product_id": product_id,

            "store_location": store_location,

        }

        # ==================================================
        # RENDER
        # ==================================================

        return render(
            request,
            "products/detail.html",
            context
        )

    except StoreAPIError as exc:

        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "error": str(exc),
            }
        )

    except Exception as exc:

        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "error": (
                    "Unable to load product. "
                    f"{str(exc)}"
                ),
            }
        )