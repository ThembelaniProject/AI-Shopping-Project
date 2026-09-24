from decimal import Decimal, InvalidOperation
import re

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

def _normalise_match_text(value):
    """Normalize text so retailer/product fields match user preferences reliably."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


def _preference_matches(preference, product_text, aliases=None):
    """Return the first matching preference and its display value."""
    aliases = aliases or {}

    for value in preference or []:
        normalized = _normalise_match_text(value)
        if not normalized:
            continue

        terms = aliases.get(normalized, [normalized])
        for term in terms:
            if _normalise_match_text(term) in product_text:
                return value
    return None


def recommendation_score(item, preferences=None, keyword=""):
    """
    Rank products using the user's saved preferences.

    Preference signals are deliberately stronger than generic product
    signals. The recommendation is a ranking, so products that do not
    match a preference can still appear, but matching products are moved
    to the top.
    """
    score = Decimal("0")
    matched_preferences = []

    name = _normalise_match_text(item.get("name"))
    description = _normalise_match_text(item.get("description"))
    category = _normalise_match_text(item.get("category"))
    brand = _normalise_match_text(item.get("brand"))
    colour = _normalise_match_text(item.get("colour") or item.get("color"))
    store = _normalise_match_text(
        item.get("store") or item.get("retailer") or item.get("store_name")
    )
    size = _normalise_match_text(item.get("size"))

    product_text = " ".join(
        part for part in [name, description, category, brand, colour, store, size]
        if part
    )

    preferred_colours = []
    preferred_stores = []
    preferred_styles = []
    preferred_hobbies = []

    if preferences:
        preferred_colours = preference_values(getattr(preferences, "colours", []))
        preferred_stores = preference_values(getattr(preferences, "stores", []))
        preferred_styles = preference_values(getattr(preferences, "styles", []))
        preferred_hobbies = preference_values(getattr(preferences, "hobbies", []))

    # Retailer names/aliases supported by the current system.
    store_aliases = {
        "checkers": ["checkers"],
        "pick n pay": ["pick n pay", "pnp", "picknpay"],
    }

    # Product feeds often do not contain an explicit "style" or "hobby".
    # Use meaningful category/name/description terms as a semantic fallback.
    style_aliases = {
        "casual": ["casual", "everyday", "basic", "relaxed"],
        "formal": ["formal", "office", "business", "dress", "suit", "smart"],
        "sporty": ["sport", "sports", "training", "running", "gym", "athletic"],
        "streetwear": ["streetwear", "street", "hoodie", "sneaker", "jogger"],
        "smart casual": ["smart casual", "casual shirt", "chino", "blazer", "polo"],
    }

    hobby_aliases = {
        "football": ["football", "soccer", "soccer ball", "football boot", "jersey"],
        "gaming": ["gaming", "gamer", "playstation", "xbox", "controller", "pc gaming"],
        "music": ["music", "headphone", "earphone", "speaker", "microphone", "guitar"],
        "fitness": ["fitness", "gym", "training", "workout", "running", "sports"],
        "travel": ["travel", "luggage", "suitcase", "backpack", "travel bag"],
        "photography": ["camera", "photography", "tripod", "lens", "photo"],
    }

    # Colour: explicit colour fields get the strongest match.
    matched = _preference_matches(
        preferred_colours,
        " ".join(part for part in [colour, name, description] if part),
    )
    if matched:
        score += Decimal("25")
        matched_preferences.append(f"Colour: {str(matched).title()}")

    # Store: match the actual normalized retailer, not a loose substring.
    matched_store = None
    for preferred in preferred_stores:
        preferred_key = _normalise_match_text(preferred)
        aliases = store_aliases.get(preferred_key, [preferred_key])
        if any(_normalise_match_text(alias) == store for alias in aliases):
            matched_store = preferred
            break

    if matched_store:
        score += Decimal("25")
        matched_preferences.append(f"Store: {str(matched_store).title()}")

    matched_style = _preference_matches(
        preferred_styles,
        product_text,
        style_aliases,
    )
    if matched_style:
        score += Decimal("20")
        matched_preferences.append(f"Style: {str(matched_style).title()}")

    matched_hobby = _preference_matches(
        preferred_hobbies,
        product_text,
        hobby_aliases,
    )
    if matched_hobby:
        score += Decimal("15")
        matched_preferences.append(f"Hobby: {str(matched_hobby).title()}")

    # Search term is a supporting signal, never stronger than a saved preference.
    search_term = _normalise_match_text(keyword)
    if search_term:
        if search_term in name:
            score += Decimal("5")
        elif search_term in category or search_term in description:
            score += Decimal("3")
        elif search_term in brand:
            score += Decimal("2")

    rating = to_decimal(item.get("rating", 0))
    score += min(max(rating, Decimal("0")), Decimal("5"))

    try:
        stock = int(item.get("stock", 0) or 0)
    except (ValueError, TypeError):
        stock = 0

    if stock > 0:
        score += Decimal("2")

    if item.get("on_sale"):
        score += Decimal("3")

    # Small affordability signal: when a budget is already applied, cheaper
    # products are naturally preferred without overriding preference matches.
    price = to_decimal(item.get("total_cost", item.get("price", 0)))
    if price > 0:
        score += Decimal("1")

    item["matched_preferences"] = matched_preferences
    item["preference_match_count"] = len(matched_preferences)

    return max(Decimal("0"), min(score, Decimal("100")))




# ==========================================================
# SEARCH PRODUCTS
# ==========================================================

@login_required
def search(request):

    # ======================================================
    # LOAD USER PREFERENCES
    # ======================================================

    try:

        preferences = Preference.objects.get(            user=request.user
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
    # SAVE LATEST SEARCH LOCATION
    # ======================================================

    # Product Search is the source of truth for the user's
    # current shopping location. Only valid coordinates are stored.
    if user_latitude and user_longitude:
        try:
            latitude_value = float(user_latitude)
            longitude_value = float(user_longitude)

            if (
                -90 <= latitude_value <= 90
                and -180 <= longitude_value <= 180
            ):
                request.session["user_latitude"] = str(latitude_value)
                request.session["user_longitude"] = str(longitude_value)

                # Do not let an older address override the new
                # coordinates captured during product search.
                request.session.pop("user_address", None)
                request.session.modified = True

        except (ValueError, TypeError):
            pass

    # The browser normally supplies precise coordinates. If the user
    # has entered a location but denied browser geolocation, do not
    # invent a distance; the retailer/store can still be displayed.
    # Coordinates are only used when they were actually supplied.

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
                "colour"
                or "color",
                ""
            )
        ).strip()

        # Keep colour from common retailer fields if the normalized
        # value is empty.
        if not product_colour:
            product_colour = str(
                product.get("color")
                or product.get("colourName")
                or product.get("colorName")
                or ""
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

            # Stable ID used by shopping-list and detail URLs.
            "external_id": str(
                product.get("external_id")
                or product.get("id")
                or product.get("product_id")
                or ""
            ).strip(),

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

        # Highest preference match count wins first, then the weighted
        # recommendation score. Price is only a final tie-breaker.
        products.sort(
            key=lambda product: (
                product.get(
                    "preference_match_count",
                    0
                ),
                product.get(
                    "recommendation_score",
                    Decimal("0")
                ),
                Decimal("1") if product.get("on_sale") else Decimal("0"),
                -product.get(
                    "total_cost",
                    Decimal("999999999")
                ),
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