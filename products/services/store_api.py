
from django.shortcuts import render

import requests
import re

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache


# ==========================================================
# CHECKERS / PARSE API
# ==========================================================

CHECKERS_SEARCH_URL = (
    "https://api.parse.bot/scraper/"
    "a7a3a4ba-dfb7-4476-9712-8753b2fb3140/"
    "search_products"
)

CHECKERS_STORE_URL = (
    "https://api.parse.bot/scraper/"
    "a7a3a4ba-dfb7-4476-9712-8753b2fb3140/"
    "get_store"
)

CACHE_TIMEOUT = 60 * 30  # 30 minutes


# ==========================================================
# API ERROR
# ==========================================================

class StoreAPIError(Exception):
    """Raised when the Checkers API fails."""
    pass


# ==========================================================
# DECIMAL HELPER
# ==========================================================

def _to_decimal(value, default="0.00"):
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal(default)


# ==========================================================
# BOOLEAN HELPER
# ==========================================================

def _to_bool(value):

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in [
            "true",
            "yes",
            "1",
            "on",
            "available",
        ]

    return False

# ==========================================================
# GET STORE LOCATION
# ==========================================================
def get_store_location(store_id):
    """
    Resolve a Checkers storeId to a store/location.
    """

    store_id = str(store_id or "").strip()

    if not store_id:
        print("GET STORE: No store ID")
        return "Location not available"

    cache_key = f"checkers_store_{store_id}"

    # ======================================================
    # CACHE
    # ======================================================

    cached = cache.get(cache_key)

    if cached is not None:
        print(
            f"GET STORE CACHE HIT: {store_id} -> {cached}"
        )
        return cached

    api_key = getattr(
        settings,
        "PARSE_API_KEY",
        "",
    )

    if not api_key:
        print("GET STORE: PARSE_API_KEY missing")
        return "Location not available"

    print("\n========================================")
    print("GET STORE REQUEST")
    print("URL:", CHECKERS_STORE_URL)
    print("STORE ID:", store_id)
    print("========================================")

    try:

        response = requests.post(
            CHECKERS_STORE_URL,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "storeId": store_id,
            },
            timeout=30,
        )

        print("GET STORE STATUS:", response.status_code)
        print("GET STORE RAW RESPONSE:")
        print(response.text)

        if response.status_code == 429:

            print(
                f"GET STORE RATE LIMITED: {store_id}"
            )

            cache.set(
                cache_key,
                "Location temporarily unavailable",
                60,
            )

            return "Location temporarily unavailable"

        response.raise_for_status()

    except requests.RequestException as exc:

        print(
            f"GET STORE REQUEST FAILED "
            f"for {store_id}: {exc}"
        )

        return "Location not available"

    # ======================================================
    # JSON
    # ======================================================

    try:

        data = response.json()

    except ValueError:

        print(
            "GET STORE returned invalid JSON"
        )

        return "Location not available"

    print("\n========================================")
    print("GET STORE JSON")
    print(data)
    print("========================================")

    # ======================================================
    # FIND STORE OBJECT
    # ======================================================

    store = None

    if isinstance(data, dict):

        if isinstance(data.get("store"), dict):

            store = data["store"]

        elif isinstance(data.get("data"), dict):

            nested = data["data"]

            if isinstance(
                nested.get("store"),
                dict,
            ):
                store = nested["store"]

            else:
                store = nested

        elif isinstance(data.get("result"), dict):

            store = data["result"]

        else:

            store = data

    elif isinstance(data, list):

        if data and isinstance(data[0], dict):

            store = data[0]

    print("\n========================================")
    print("EXTRACTED STORE OBJECT")
    print(store)
    print("========================================")

    if not isinstance(store, dict):

        print(
            "GET STORE: Could not find store object"
        )

        return "Location not available"

    # ======================================================
    # CLEAN
    # ======================================================

    def clean(value):

        if value is None:
            return ""

        if isinstance(
            value,
            (str, int, float),
        ):
            return str(value).strip()

        return ""

    # ======================================================
    # DIRECT ADDRESS
    # ======================================================

    address_fields = [
        "displayName",
        "display_name",
        "formattedAddress",
        "formatted_address",
        "fullAddress",
        "full_address",
        "addressString",
        "address_string",
        "addressText",
        "address_text",
    ]

    for field in address_fields:

        value = clean(
            store.get(field)
        )

        if value:

            print(
                f"GET STORE LOCATION FOUND "
                f"FROM {field}: {value}"
            )

            cache.set(
                cache_key,
                value,
                CACHE_TIMEOUT,
            )

            return value

    # ======================================================
    # BUILD ADDRESS
    # ======================================================

    parts = []

    fields = [
        "storeName",
        "store_name",
        "branchName",
        "branch_name",
        "name",
        "addressLine",
        "addressLine1",
        "addressLine2",
        "street",
        "streetAddress",
        "suburb",
        "town",
        "city",
        "province",
        "postalCode",
        "postal_code",
        "postcode",
    ]

    for field in fields:

        value = clean(
            store.get(field)
        )

        if value and value not in parts:

            parts.append(value)

    # ======================================================
    # NESTED ADDRESS
    # ======================================================

    address = store.get("address")

    if isinstance(address, dict):

        for field in [
            "addressLine1",
            "addressLine2",
            "street",
            "streetAddress",
            "suburb",
            "town",
            "city",
            "province",
            "postalCode",
            "postal_code",
            "postcode",
        ]:

            value = clean(
                address.get(field)
            )

            if value and value not in parts:

                parts.append(value)

    # ======================================================
    # RESULT
    # ======================================================

    if not parts:

        print(
            "GET STORE: Store response contains "
            "no recognized address fields."
        )

        print(
            "AVAILABLE STORE KEYS:",
            list(store.keys()),
        )

        return "Location not available"

    location = ", ".join(parts)

    print(
        f"GET STORE LOCATION FOUND: {location}"
    )

    cache.set(
        cache_key,
        location,
        CACHE_TIMEOUT,
    )

    return location


# ==========================================================
# PRODUCT ID
# ==========================================================

def _extract_product_id(product):
    """
    Get the real external Checkers product identifier.

    IDs can be strings, for example:

        64889a3e392f9d86b62b06c5

    Never convert Checkers IDs to int.
    """

    fields = [
        "productId",
        "product_id",
        "sku",
        "code",
        "id",
    ]

    for field in fields:

        value = product.get(field)

        if value is None:
            continue

        value = str(value).strip()

        if value:
            return value

    return ""


# ==========================================================
# IMAGE HELPER
# ==========================================================

def _extract_image(product):

    image_fields = [
        "image",
        "imageURL",
        "imageUrl",
        "image_url",
        "imageProductCardURL",
        "imageProductCardUrl",
        "imagePDPURL",
        "imagePDPUrl",
        "thumbnail",
        "thumbnailUrl",
        "thumbnailURL",
        "picture",
        "pictureUrl",
        "productImage",
        "productImageUrl",
        "mainImage",
        "mainImageUrl",
    ]

    for field in image_fields:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

    # ------------------------------------------------------
    # Images list
    # ------------------------------------------------------

    images = product.get("images")

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

    # ------------------------------------------------------
    # Nested image object
    # ------------------------------------------------------

    image_object = product.get("image")

    if isinstance(image_object, dict):

        for field in [
            "url",
            "imageUrl",
            "imageURL",
            "src",
        ]:

            value = image_object.get(field)

            if isinstance(value, str):

                value = value.strip()

                if value:
                    return value

    return ""


# ==========================================================
# IMAGE LIST HELPER
# ==========================================================

def _extract_images(product):

    images = []

    main_image = _extract_image(product)

    if main_image:
        images.append(main_image)

    raw_images = product.get("images")

    if isinstance(raw_images, list):

        for image in raw_images:

            url = ""

            if isinstance(image, str):

                url = image.strip()

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
                            url = value
                            break

            if url and url not in images:
                images.append(url)

    for field in [
        "imageURL",
        "imageUrl",
        "imageProductCardURL",
        "imageProductCardUrl",
        "imagePDPURL",
        "imagePDPUrl",
        "thumbnail",
        "thumbnailUrl",
        "thumbnailURL",
        "productImage",
        "productImageUrl",
        "mainImage",
        "mainImageUrl",
    ]:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value and value not in images:
                images.append(value)

    return images


# ==========================================================
# PRICE EXTRACTION
# ==========================================================

def _extract_price(value):

    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    try:

        text = str(value).strip()

        if not text:
            return None

        text = (
            text
            .replace("R", "")
            .replace("r", "")
            .replace(",", "")
            .strip()
        )

        return Decimal(text)

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        return None


# ==========================================================
# CHECKERS PRICE
# ==========================================================

def _extract_checkers_price(product, *fields):

    for field in fields:

        value = product.get(field)

        if value is None:
            continue

        price = _extract_price(value)

        if price is None:
            continue

        if "WithoutDecimal" in field:
            price = price / Decimal("100")

        return price

    return None


# ==========================================================
# SALE PRICE
# ==========================================================

def _extract_sale_price(product):
    """
    Extract the current/sale price from a Checkers product.
    Handles normal prices and prices stored without decimals.
    """

    sale_fields = [
        "salePrice",
        "sale_price",
        "promotionPrice",
        "promotion_price",
        "promoPrice",
        "promo_price",
        "discountPrice",
        "discount_price",
        "specialPrice",
        "special_price",
        "offerPrice",
        "offer_price",
        "sellingPrice",
        "selling_price",
        "currentPrice",
        "current_price",
        "priceAfterDiscount",
        "price_after_discount",
        "priceWithoutDecimal",
        "price",
    ]

    for field in sale_fields:
        if field not in product:
            continue

        value = product.get(field)

        if value is None:
            continue

        # Support nested price objects
        if isinstance(value, dict):
            value = (
                value.get("value")
                or value.get("amount")
                or value.get("price")
            )

        price = _extract_price(value)

        if price is None:
            continue

        if "WithoutDecimal" in field:
            price = price / Decimal("100")

        return price.quantize(Decimal("0.01"))

    return None


# ==========================================================
# REGULAR PRICE
# ==========================================================

def _extract_regular_price(product):

    regular_fields = [
        "regularPrice",
        "regular_price",
        "originalPrice",
        "original_price",
        "wasPrice",
        "was_price",
        "listPrice",
        "list_price",
        "rrp",
        "RRP",
        "recommendedRetailPrice",
        "recommended_retail_price",
        "priceBeforeDiscount",
        "price_before_discount",
        "fullPrice",
        "full_price",
        "normalPrice",
        "normal_price",
        "priceWithoutDiscount",
        "price_without_discount",
    ]

    for field in regular_fields:
        if field not in product:
            continue

        value = product.get(field)

        if isinstance(value, dict):
            value = (
                value.get("value")
                or value.get("amount")
                or value.get("price")
            )

        price = _extract_price(value)

        if price is None:
            continue

        if "WithoutDecimal" in field:
            price = price / Decimal("100")

        return price.quantize(Decimal("0.01"))

    return None


# ==========================================================
# PROMOTION
# ==========================================================

def _extract_promotion(product):
    """
    Extract promotion information from a Checkers product.
    Returns a readable promotion string.
    """

    promotion_fields = [
        "promotion",
        "promotionName",
        "promotion_name",
        "promotionDescription",
        "promotion_description",
        "promo",
        "promoName",
        "promo_name",
        "promoDescription",
        "promo_description",
        "offer",
        "offerName",
        "offer_name",
        "deal",
        "dealName",
        "deal_name",
    ]

    for field in promotion_fields:
        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):
            for nested_field in [
                "name",
                "title",
                "description",
                "label",
                "displayName",
                "display_name",
            ]:
                nested_value = value.get(nested_field)

                if nested_value is not None:
                    nested_value = str(nested_value).strip()

                    if nested_value:
                        return nested_value

    return ""


# ==========================================================
# SALE FLAG
# ==========================================================

def _extract_on_sale(
    product,
    regular_price=None,
    sale_price=None,
):

    promotion_fields = [
        "isOnPromotion",
        "is_on_promotion",
        "onPromotion",
        "on_promotion",
        "onSale",
        "isOnSale",
        "isPromotion",
        "is_promotion",
        "promotional",
        "discounted",
        "hasPromotion",
        "has_promotion",
    ]

    for field in promotion_fields:

        if field not in product:
            continue

        value = product.get(field)

        if isinstance(value, dict):
            return True

        if _to_bool(value):
            return True

    # A lower sale price automatically means the product is on sale.
    if (
        regular_price is not None
        and sale_price is not None
        and regular_price > sale_price
    ):
        return True

    # A promotion object/string also means promotion exists.
    promotion = _extract_promotion(product)

    if promotion:
        return True

    return False


# ==========================================================
# DISCOUNT
# ==========================================================

def _extract_discount_amount(
    regular_price,
    sale_price,
    product,
):

    if (
        regular_price is not None
        and sale_price is not None
        and regular_price > sale_price
    ):
        return (
            regular_price - sale_price
        ).quantize(Decimal("0.01"))

    discount_fields = [
        "discountAmount",
        "discount_amount",
        "saving",
        "savings",
        "saveAmount",
        "save_amount",
        "promotionDiscount",
        "promotion_discount",
        "discount",
    ]

    for field in discount_fields:

        value = product.get(field)

        if isinstance(value, dict):
            value = (
                value.get("value")
                or value.get("amount")
            )

        discount = _extract_price(value)

        if discount is not None:

            if "WithoutDecimal" in field:
                discount = discount / Decimal("100")

            return discount.quantize(
                Decimal("0.01")
            )

    return Decimal("0.00")

# ==========================================================
# COLOUR HELPER
# ==========================================================

def _extract_colour(product):

    # ------------------------------------------------------
    # DIRECT COLOUR FIELDS
    # ------------------------------------------------------

    for field in [
        "colour",
        "color",
        "colourName",
        "colorName",
        "colour_name",
        "color_name",
        "productColour",
        "productColor",
        "variantColour",
        "variantColor",
    ]:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):

            for nested_field in [
                "name",
                "value",
                "label",
                "displayName",
            ]:

                nested_value = value.get(
                    nested_field
                )

                if isinstance(nested_value, str):

                    nested_value = nested_value.strip()

                    if nested_value:
                        return nested_value

    # ------------------------------------------------------
    # ATTRIBUTES
    # ------------------------------------------------------

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).lower()

            if (
                "colour" in attribute_name
                or "color" in attribute_name
            ):

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                )

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

    elif isinstance(attributes, dict):

        for key, value in attributes.items():

            key_lower = str(key).lower()

            if (
                "colour" in key_lower
                or "color" in key_lower
            ):

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

                elif isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                    )

                    if isinstance(value, str):

                        value = value.strip()

                        if value:
                            return value

    return "Not specified"


# ==========================================================
# CATEGORY HELPER
# ==========================================================
def _extract_category(product):

    # ======================================================
    # 1. DIRECT CATEGORY FIELDS
    # ======================================================

    for field in [
        "category",
        "categoryName",
        "category_name",
        "productCategory",
        "product_category",
        "department",
        "departmentName",
        "department_name",
        "productType",
        "product_type",
        "type",
    ]:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):

            for nested_field in [
                "name",
                "value",
                "label",
                "displayName",
                "title",
            ]:

                nested_value = value.get(
                    nested_field
                )

                if nested_value is not None:

                    nested_value = str(
                        nested_value
                    ).strip()

                    if nested_value:
                        return nested_value

    # ======================================================
    # 2. CATEGORIES LIST
    # ======================================================

    categories = product.get("categories")

    if isinstance(categories, list):

        category_values = []

        for category in categories:

            if isinstance(category, str):

                value = category.strip()

                if value:
                    category_values.append(value)

            elif isinstance(category, dict):

                for field in [
                    "name",
                    "value",
                    "label",
                    "displayName",
                    "title",
                ]:

                    value = category.get(field)

                    if value is not None:

                        value = str(value).strip()

                        if value:
                            category_values.append(value)
                            break

        if category_values:

            # Return the most specific/last category.
            return category_values[-1]

    # ======================================================
    # 3. CATEGORY ATTRIBUTES
    # ======================================================

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).strip().lower()

            if (
                "category" in attribute_name
                or "department" in attribute_name
                or "product type" in attribute_name
                or "producttype" in attribute_name
            ):

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                    or attribute.get("title")
                )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    elif isinstance(attributes, dict):

        for key, value in attributes.items():

            key_lower = str(key).strip().lower()

            if (
                "category" in key_lower
                or "department" in key_lower
                or "product type" in key_lower
                or "producttype" in key_lower
            ):

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

                elif isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                        or value.get("title")
                    )

                    if value is not None:

                        value = str(value).strip()

                        if value:
                            return value

    # ======================================================
    # 4. FALLBACK: PRODUCT NAME
    # ======================================================

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or ""
    )

    name = str(name).strip()

    if name:

        name_lower = name.lower()

        # --------------------------------------------------
        # Grocery / food categories
        # --------------------------------------------------

        category_keywords = {

            "milk": "Milk",

            "cheese": "Cheese",

            "yoghurt": "Yoghurt",
            "yogurt": "Yoghurt",

            "butter": "Butter",

            "cream": "Dairy",

            "margarine": "Margarine",

            "juice": "Juice",
            "fruit juice": "Juice",

            "water": "Water",

            "bread": "Bread",

            "rolls": "Bread",

            "loaf": "Bread",

            "cereal": "Cereal",
            "cereals": "Cereal",

            "coffee": "Coffee",

            "tea": "Tea",

            "sugar": "Sugar",

            "rice": "Rice",

            "pasta": "Pasta",

            "flour": "Flour",

            "oil": "Cooking Oil",

            "sauce": "Sauces",

            "ketchup": "Sauces",

            "mayonnaise": "Sauces",

            "biscuit": "Biscuits",

            "biscuits": "Biscuits",

            "cookie": "Biscuits",
            "cookies": "Biscuits",

            "chocolate": "Chocolate",

            "sweet": "Sweets",
            "sweets": "Sweets",

            "chips": "Snacks",
            "crisps": "Snacks",

            "snack": "Snacks",
            "snacks": "Snacks",

            "meat": "Meat",

            "beef": "Meat",
            "chicken": "Meat",
            "pork": "Meat",

            "fish": "Fish",

            "sausage": "Meat",

            "egg": "Eggs",
            "eggs": "Eggs",

            "vegetable": "Vegetables",
            "vegetables": "Vegetables",

            "fruit": "Fruit",
            "fruits": "Fruit",

            "frozen": "Frozen Food",

            "pizza": "Frozen Food",

            "ice cream": "Ice Cream",

            "pet food": "Pet Food",

            "cat food": "Pet Food",
            "dog food": "Pet Food",

            "baby": "Baby",

            "diaper": "Baby",
            "diapers": "Baby",

            "detergent": "Cleaning",

            "washing powder": "Cleaning",

            "dishwashing": "Cleaning",

            "toilet paper": "Household",

            "paper towel": "Household",

            "cleaner": "Cleaning",

            "shampoo": "Personal Care",

            "conditioner": "Personal Care",

            "soap": "Personal Care",

            "toothpaste": "Personal Care",

            "deodorant": "Personal Care",

            "lotion": "Personal Care",
        }

        # Check longer phrases first.
        for keyword, category in sorted(
            category_keywords.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):

            if keyword in name_lower:

                return category

    # ======================================================
    # 5. NOTHING FOUND
    # ======================================================

    return "Other"


    # ------------------------------------------------------
    # DIRECT CATEGORY FIELDS
    # ------------------------------------------------------

    for field in [
        "category",
        "categoryName",
        "category_name",
        "productCategory",
        "product_category",
        "department",
        "departmentName",
        "department_name",
        "productType",
        "product_type",
        "type",
    ]:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):

            for nested_field in [
                "name",
                "value",
                "label",
                "displayName",
                "title",
            ]:

                nested_value = value.get(
                    nested_field
                )

                if isinstance(nested_value, str):

                    nested_value = nested_value.strip()

                    if nested_value:
                        return nested_value

    # ------------------------------------------------------
    # CATEGORIES LIST
    # ------------------------------------------------------

    categories = product.get("categories")

    if isinstance(categories, list):

        for category in categories:

            if isinstance(category, str):

                category = category.strip()

                if category:
                    return category

            elif isinstance(category, dict):

                for field in [
                    "name",
                    "value",
                    "label",
                    "displayName",
                    "title",
                ]:

                    value = category.get(field)

                    if isinstance(value, str):

                        value = value.strip()

                        if value:
                            return value

    # ------------------------------------------------------
    # ATTRIBUTES
    # ------------------------------------------------------

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).lower()

            if (
                "category" in attribute_name
                or "department" in attribute_name
                or "product type" in attribute_name
                or "producttype" in attribute_name
            ):

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                    or attribute.get("title")
                )

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

    elif isinstance(attributes, dict):

        for key, value in attributes.items():

            key_lower = str(key).lower()

            if (
                "category" in key_lower
                or "department" in key_lower
            ):

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

                elif isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                        or value.get("title")
                    )

                    if isinstance(value, str):

                        value = value.strip()

                        if value:
                            return value

    return "Other"

# ==========================================================
# SIZE HELPER
# ==========================================================


    # ------------------------------------------------------
    # DIRECT SIZE FIELDS
    # ------------------------------------------------------

    for field in [
        "size",
        "sizeName",
        "size_name",
        "productSize",
        "product_size",
        "variantSize",
        "variant_size",
        "sizeValue",
        "size_value",
    ]:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif isinstance(value, (int, float)):

            return str(value)

        elif isinstance(value, dict):

            for nested_field in [
                "name",
                "value",
                "label",
                "displayName",
                "title",
            ]:

                nested_value = value.get(
                    nested_field
                )

                if nested_value is not None:

                    nested_value = str(
                        nested_value
                    ).strip()

                    if nested_value:
                        return nested_value

    # ------------------------------------------------------
    # SIZES LIST
    # ------------------------------------------------------

    sizes = product.get("sizes")

    if isinstance(sizes, list):

        for size in sizes:

            if isinstance(size, str):

                size = size.strip()

                if size:
                    return size

            elif isinstance(size, dict):

                for field in [
                    "name",
                    "value",
                    "label",
                    "displayName",
                    "title",
                ]:

                    value = size.get(field)

                    if value is not None:

                        value = str(value).strip()

                        if value:
                            return value

    # ------------------------------------------------------
    # ATTRIBUTES
    # ------------------------------------------------------

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).lower()

            if "size" in attribute_name:

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                    or attribute.get("title")
                )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    elif isinstance(attributes, dict):

        for key, value in attributes.items():

            key_lower = str(key).lower()

            if "size" in key_lower:

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

                elif isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                        or value.get("title")
                    )

                    if value is not None:

                        value = str(value).strip()

                        if value:
                            return value

    # ------------------------------------------------------
    # VARIANTS
    # ------------------------------------------------------

    variants = product.get("variants")

    if isinstance(variants, list):

        for variant in variants:

            if not isinstance(variant, dict):
                continue

            for field in [
                "size",
                "sizeName",
                "sizeValue",
                "variantSize",
            ]:

                value = variant.get(field)

                if value is not None:

                    if isinstance(value, dict):

                        value = (
                            value.get("value")
                            or value.get("name")
                            or value.get("label")
                            or value.get("displayName")
                        )

                    if value is not None:

                        value = str(value).strip()

                        if value:
                            return value

    return "Not specified"


# ==========================================================
# SIZE HELPER
# ==========================================================

def _extract_size(product):

    # ======================================================
    # 1. DIRECT SIZE FIELDS
    # ======================================================

    for field in [
        "size",
        "sizeName",
        "size_name",
        "sizeValue",
        "size_value",
        "productSize",
        "product_size",
        "variantSize",
        "variant_size",
    ]:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, dict):

            value = (
                value.get("value")
                or value.get("name")
                or value.get("label")
                or value.get("displayName")
            )

        if value is not None:

            value = str(value).strip()

            if value:
                return value

    # ======================================================
    # 2. SIZE ATTRIBUTE
    # ======================================================

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).strip().lower()

            if attribute_name in [
                "size",
                "product size",
                "size name",
                "size value",
            ]:

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    # ======================================================
    # 3. VARIANTS
    # ======================================================

    variants = product.get("variants")

    if isinstance(variants, list):

        for variant in variants:

            if not isinstance(variant, dict):
                continue

            for field in [
                "size",
                "sizeName",
                "sizeValue",
                "variantSize",
            ]:

                value = variant.get(field)

                if value is None:
                    continue

                if isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                    )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    # ======================================================
    # 4. FALLBACK — SIZE FROM PRODUCT NAME
    # ======================================================

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or ""
    )

    name = str(name).strip()

    if name:

        # Supports:
        #
        # 500ml
        # 1L
        # 2L
        # 750g
        # 1kg
        # 6 x 1L
        # 6x1L
        # 12 x 500ml
        # 24x330ml
        #
        # The final size is normally the product/package size.

        pattern = re.compile(
            r"""
            (?<![A-Za-z0-9])
            (?:
                \d+
                \s*[xX×]\s*
            )?
            \d+(?:[.,]\d+)?
            \s*
            (?:ml|l|g|kg|cl)
            \b
            """,
            re.IGNORECASE | re.VERBOSE,
        )

        matches = pattern.findall(name)

        if matches:

            return matches[-1].strip()

    # ======================================================
    # 5. NOTHING FOUND
    # ======================================================

    return "Not specified"


    # ------------------------------------------------------
    # 1. DIRECT SIZE FIELDS
    # ------------------------------------------------------

    for field in [
        "size",
        "sizeName",
        "size_name",
        "sizeValue",
        "size_value",
        "productSize",
        "product_size",
        "variantSize",
        "variant_size",
    ]:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, dict):

            value = (
                value.get("value")
                or value.get("name")
                or value.get("label")
                or value.get("displayName")
            )

        if value is not None:

            value = str(value).strip()

            if value:
                return value

    # ------------------------------------------------------
    # 2. SIZE ATTRIBUTE
    # ------------------------------------------------------

    attributes = product.get("attributes")

    if isinstance(attributes, list):

        for attribute in attributes:

            if not isinstance(attribute, dict):
                continue

            attribute_name = str(
                attribute.get(
                    "name",
                    attribute.get(
                        "key",
                        attribute.get(
                            "attribute",
                            "",
                        ),
                    ),
                )
            ).strip().lower()

            # Only accept actual size attributes.
            if attribute_name in [
                "size",
                "product size",
                "clothing size",
                "shoe size",
                "apparel size",
                "size name",
                "size value",
            ]:

                value = (
                    attribute.get("value")
                    or attribute.get("label")
                    or attribute.get("displayValue")
                    or attribute.get("displayName")
                )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    # ------------------------------------------------------
    # 3. SIZE OBJECT
    # ------------------------------------------------------

    size_object = product.get("size")

    if isinstance(size_object, dict):

        for field in [
            "value",
            "name",
            "label",
            "displayName",
        ]:

            value = size_object.get(field)

            if value is not None:

                value = str(value).strip()

                if value:
                    return value

    # ------------------------------------------------------
    # 4. VARIANTS
    # ------------------------------------------------------

    variants = product.get("variants")

    if isinstance(variants, list):

        for variant in variants:

            if not isinstance(variant, dict):
                continue

            for field in [
                "size",
                "sizeName",
                "sizeValue",
                "variantSize",
            ]:

                value = variant.get(field)

                if value is None:
                    continue

                if isinstance(value, dict):

                    value = (
                        value.get("value")
                        or value.get("name")
                        or value.get("label")
                        or value.get("displayName")
                    )

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

    # ------------------------------------------------------
    # 5. NOTHING FOUND
    # ------------------------------------------------------

    return "Not specified"



# ==========================================================
# STORE LOCATION HELPER
# ==========================================================
def _extract_store_location(product):
    """Extract the Checkers store/location associated with a product."""

    def clean(value):
        if value is None:
            return ""

        if isinstance(value, (str, int, float)):
            return str(value).strip()

        return ""

    def build_location(data):
        if not isinstance(data, dict):
            return ""

        for field in [
            "displayName",
            "display_name",
            "formattedAddress",
            "formatted_address",
            "fullAddress",
            "full_address",
        ]:
            value = clean(data.get(field))
            if value:
                return value

        parts = []

        for field in [
            "storeName",
            "store_name",
            "branchName",
            "branch_name",
            "name",
            "address",
            "addressLine",
            "addressLine1",
            "addressLine2",
            "street",
            "streetAddress",
            "suburb",
            "town",
            "city",
            "province",
            "postalCode",
            "postal_code",
            "postcode",
        ]:
            value = clean(data.get(field))

            if value and value not in parts:
                parts.append(value)

        return ", ".join(parts)

    # ======================================================
    # STORE ID
    # ======================================================

    store_id = (
        product.get("storeId")
        or product.get("store_id")
        or product.get("branchId")
        or product.get("branch_id")
    )

    # If storeId itself is an object
    if isinstance(store_id, dict):
        location = build_location(store_id)

        if location:
            return location

    # ======================================================
    # DIRECT STORE LOCATION
    # ======================================================

    for field in [
        "storeLocation",
        "store_location",
        "branchLocation",
        "branch_location",
        "storeAddress",
        "store_address",
        "physicalAddress",
        "physical_address",
        "location",
        "address",
    ]:
        value = product.get(field)

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):
            location = build_location(value)

            if location:
                return location

    # ======================================================
    # STORE / BRANCH OBJECT
    # ======================================================

    for field in [
        "store",
        "branch",
        "fulfilmentStore",
        "fulfillmentStore",
        "fulfilment_store",
        "fulfillment_store",
        "retailer",
        "seller",
        "merchant",
    ]:
        store = product.get(field)

        if isinstance(store, str):
            store = store.strip()

            if store:
                return store

        elif isinstance(store, dict):
            location = build_location(store)

            if location:
                return location

    return "Location not available"

# ==========================================================
# DEAL EXPIRY
# ==========================================================

def _extract_deal_expiry(product):

    expiry_fields = [
        "dealExpires",
        "dealExpiry",
        "dealExpiration",
        "dealExpirationDate",
        "dealExpiryDate",
        "promotionEndDate",
        "promotionEnd",
        "promotionEndDateTime",
        "promoEndDate",
        "promoEnd",
        "offerEndDate",
        "offerEnd",
        "validUntil",
        "validTo",
        "endDate",
        "end_date",
        "expiresAt",
        "expirationDate",
    ]

    for field in expiry_fields:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif value:

            return value

    promotion = product.get("promotion")

    if isinstance(promotion, dict):

        for field in [
            "endDate",
            "end_date",
            "expiryDate",
            "expiry",
            "expiresAt",
            "validUntil",
            "validTo",
        ]:

            value = promotion.get(field)

            if value:

                if isinstance(value, str):
                    value = value.strip()

                if value:
                    return value

    return ""


# ==========================================================
# CACHE PRODUCT
# ==========================================================

def _cache_product(product):

    product_id = product.get("external_id")

    if not product_id:
        return

    cache.set(
        f"checkers_product_{product_id}",
        product,
        CACHE_TIMEOUT,
    )


# ==========================================================
# GET PRODUCT
# ==========================================================

def get_product(product_id):
    """
    Get a single normalized product from cache.

    search_products() caches every product returned
    by the Checkers API.
    """

    product_id = str(product_id).strip()

    if not product_id:
        raise StoreAPIError(
            "No product ID was provided."
        )

    cache_key = (
        f"checkers_product_{product_id}"
    )

    product = cache.get(cache_key)

    if product is None:
        raise StoreAPIError(
            f"Product '{product_id}' could not be found."
        )

    return product


# ==========================================================
# SEARCH PRODUCTS
# ==========================================================
def search_products(keyword="", limit=100):

    keyword = (keyword or "").strip()

    if not keyword:
        return []

    api_key = getattr(
        settings,
        "PARSE_API_KEY",
        "",
    )

    if not api_key:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured in settings.py."
        )

    try:

        response = requests.post(
            CHECKERS_SEARCH_URL,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "query": keyword,
                "page": 0,
                "limit": limit,
            },
            timeout=30,
        )

        response.raise_for_status()

    except requests.Timeout as exc:

        raise StoreAPIError(
            "The Checkers API request timed out."
        ) from exc

    except requests.HTTPError as exc:

        raise StoreAPIError(
            f"Checkers API returned HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        ) from exc

    except requests.RequestException as exc:

        raise StoreAPIError(
            f"Unable to connect to Checkers API: {exc}"
        ) from exc

    try:

        data = response.json()

    except ValueError as exc:

        raise StoreAPIError(
            "Checkers API did not return valid JSON: "
            f"{response.text[:500]}"
        ) from exc

    print("\n========================================")
    print("CHECKERS API RESPONSE")
    print("========================================")
    print(data)
    print("========================================\n")

    # ======================================================
    # FIND PRODUCTS
    # ======================================================

    raw_products = []

    if isinstance(data, dict):

        if isinstance(data.get("products"), list):

            raw_products = data["products"]

        elif isinstance(data.get("data"), list):

            raw_products = data["data"]

        elif isinstance(data.get("results"), list):

            raw_products = data["results"]

        elif isinstance(data.get("items"), list):

            raw_products = data["items"]

        elif isinstance(data.get("data"), dict):

            nested = data["data"]

            if isinstance(
                nested.get("products"),
                list,
            ):

                raw_products = nested["products"]

            elif isinstance(
                nested.get("results"),
                list,
            ):

                raw_products = nested["results"]

            elif isinstance(
                nested.get("items"),
                list,
            ):

                raw_products = nested["items"]

    elif isinstance(data, list):

        raw_products = data

    if not raw_products:
        return []

    # ======================================================
    # NORMALIZE
    # ======================================================

    products = []

    for raw_product in raw_products:

        if not isinstance(raw_product, dict):
            continue

        try:

            normalized = normalize_product(
                raw_product,resolve_store=False,
            )

            _cache_product(normalized)

            products.append(normalized)

        except Exception as exc:

            print(
                "Could not normalize Checkers product:",
                exc,
            )

            continue

    return products



def normalize_product(product, resolve_store=True):

    # ======================================================
    # PRODUCT ID
    # ======================================================

    product_id = _extract_product_id(product)

    raw_id = product.get("id")
    raw_product_id = product.get("productId")
    raw_product_id_underscore = product.get("product_id")
    raw_sku = product.get("sku")
    raw_code = product.get("code")

    # ======================================================
    # NAME
    # ======================================================

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or "Unknown Checkers Product"
    )

    # ======================================================
    # DESCRIPTION
    # ======================================================

    description = (
        product.get("description")
        or product.get("shortDescription")
        or product.get("longDescription")
        or ""
    )

    # ======================================================
    # PRICES
    # ======================================================

    sale_price = _extract_sale_price(product)
    regular_price = _extract_regular_price(product)

    # Generic fallback price
    generic_price = _extract_checkers_price(
        product,
        "priceWithoutDecimal",
        "price",
        "sellingPrice",
    )

    if sale_price is None:
        sale_price = generic_price

    if regular_price is None:
        regular_price = generic_price

    if sale_price is None:
        sale_price = Decimal("0.00")

    if regular_price is None:
        regular_price = sale_price

    # ======================================================
    # PROMOTION
    # ======================================================

    promotion = _extract_promotion(product)

    on_sale = _extract_on_sale(
        product,
        regular_price=regular_price,
        sale_price=sale_price,
    )

    # If there is a promotion but no explicit sale flag
    if promotion:
        on_sale = True

    # Never allow regular price to be lower than sale price
    if on_sale and regular_price < sale_price:
        regular_price = sale_price

    # ======================================================
    # DISCOUNT
    # ======================================================

    discount_amount = _extract_discount_amount(
        regular_price,
        sale_price,
        product,
    )

    if (
        regular_price > 0
        and sale_price < regular_price
    ):
        discount_percentage = (
            (regular_price - sale_price)
            / regular_price
            * Decimal("100")
        ).quantize(Decimal("0.01"))
    else:
        discount_percentage = Decimal("0.00")

    # ======================================================
    # EXPIRY
    # ======================================================

    deal_expiry = _extract_deal_expiry(product)

    # ======================================================
    # BRAND
    # ======================================================

    brand = (
        product.get("brand")
        or product.get("brandName")
        or "Unknown"
    )

    # ======================================================
    # CATEGORY
    # ======================================================

    category = _extract_category(product)

    # ======================================================
    # COLOUR
    # ======================================================

    colour = _extract_colour(product)

    # ======================================================
    # SIZE
    # ======================================================

    size = _extract_size(product)

    # ======================================================
    # STORE ID
    # ======================================================

    store_id = (
        product.get("storeId")
        or product.get("store_id")
        or product.get("branchId")
        or product.get("branch_id")
    )

    # Check nested store object
    store_object = product.get("store")

    if (
        not store_id
        and isinstance(store_object, dict)
    ):
        store_id = (
            store_object.get("storeId")
            or store_object.get("store_id")
            or store_object.get("branchId")
            or store_object.get("branch_id")
        )

    # ======================================================
    # STORE LOCATION
    # ======================================================

    store_location = _extract_store_location(product)

    if (
        resolve_store
        and store_location == "Location not available"
        and store_id
    ):
        store_location = get_store_location(store_id)

    # ======================================================
    # STOCK
    # ======================================================

    stock_fields = [
        "stock",
        "stockQuantity",
        "stock_quantity",
        "quantity",
        "availableQuantity",
        "available_quantity",
        "inventory",
        "inventoryQuantity",
        "inventory_quantity",
        "stockOnHand",
    ]

    stock = None

    for field in stock_fields:

        value = product.get(field)

        if value is None:
            continue

        try:
            parsed_stock = int(value)

            if parsed_stock >= 0:
                stock = parsed_stock
                break

        except (ValueError, TypeError):
            continue

    if stock is None:

        stock_available = product.get(
            "isStockAvailable",
            product.get(
                "inStock",
                product.get(
                    "available",
                    False,
                ),
            ),
        )

        stock = (
            1
            if _to_bool(stock_available)
            else 0
        )

    # ======================================================
    # IMAGES
    # ======================================================

    image = _extract_image(product)
    images = _extract_images(product)

    # ======================================================
    # URL
    # ======================================================

    url = (
        product.get("url")
        or product.get("productUrl")
        or product.get("productURL")
        or product.get("link")
        or ""
    )

    # ======================================================
    # SHIPPING
    # ======================================================

    shipping_cost = Decimal("0.00")

    # ======================================================
    # CURRENT PRICE
    # ======================================================

    current_price = sale_price

    # ======================================================
    # NORMALIZED PRODUCT
    # ======================================================

    normalized = {
        "id": product_id,
        "external_id": product_id,

        "raw_id": raw_id,
        "raw_product_id": raw_product_id,
        "raw_product_id_underscore":
            raw_product_id_underscore,
        "raw_sku": raw_sku,
        "raw_code": raw_code,

        "source": "checkers",

        "name": name,
        "title": name,
        "description": description,

        "brand": brand,
        "category": category,
        "colour": colour,
        "size": size,

        # ------------------------------
        # PRICE
        # ------------------------------

        "price": current_price,

        "regular_price": regular_price,

        "sale_price": (
            current_price
            if on_sale
            else None
        ),

        # ------------------------------
        # PROMOTION
        # ------------------------------

        "on_sale": on_sale,

        "promotion": promotion,

        "discount_amount": discount_amount,

        "discount_percentage":
            discount_percentage,

        "deal_expiry": deal_expiry,

        # ------------------------------
        # COST
        # ------------------------------

        "shipping_cost": shipping_cost,

        "total_cost": (
            current_price
            + shipping_cost
        ),

        # ------------------------------
        # STOCK
        # ------------------------------

        "stock": stock,

        "rating": Decimal("0.00"),

        # ------------------------------
        # STORE
        # ------------------------------

        "store": "Checkers",

        "location": store_location,

        # ------------------------------
        # IMAGES
        # ------------------------------

        "image": image,

        "thumbnail": image,

        "images": images,

        # ------------------------------
        # URL
        # ------------------------------

        "url": url,
    }

    return normalized





# ==========================================================
# GET PRODUCT
# ==========================================================

# ==========================================================
# DETAIL
# ==========================================================
def detail(request, product_id):
    product_id = str(product_id).strip()

    if not product_id:
        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error": "No product ID was provided.",
            },
        )

    try:
        product = get_product(product_id)

    except StoreAPIError as exc:
        return render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error": str(exc),
            },
        )

    print("========================================")
    print("PRODUCT DETAIL")
    print("Product ID:", product_id)
    print("Product:", product.get("name"))
    print("Store:", product.get("store"))
    print("Location:", product.get("location"))
    print("========================================")

    return render(
        request,
        "products/detail.html",
        {
            "product": product,
        },
    )
    