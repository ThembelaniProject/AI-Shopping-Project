import json
import os
import re
from decimal import Decimal, InvalidOperation

import redis
import requests

from django.conf import settings


# ==========================================================
# REDIS CLIENT
# ==========================================================

REDIS_URL = os.environ.get("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("REDIS_URL is not configured.")

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


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


# ==========================================================
# CACHE SETTINGS
# ==========================================================

CACHE_TIMEOUT = 60 * 60 * 24
EMPTY_CACHE_TIMEOUT = 60
STORE_ERROR_CACHE_TIMEOUT = 60


# ==========================================================
# API ERROR
# ==========================================================

class StoreAPIError(Exception):
    """Raised when the Checkers API cannot be used successfully."""

    pass


# ==========================================================
# REDIS HELPERS
# ==========================================================

def _redis_json_default(value):
    """Convert Decimal values to strings for JSON storage."""

    if isinstance(value, Decimal):
        return str(value)

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def _redis_get_json(key):
    """Get and decode JSON from Redis."""

    try:
        value = redis_client.get(key)
    except redis.RedisError as exc:
        print(f"REDIS GET ERROR [{key}]: {exc}")
        return None

    if value is None:
        return None

    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        print(f"REDIS JSON DECODE ERROR [{key}]: {exc}")
        return None



def _redis_set_json(key, value, timeout):
    """Store a Python value as JSON in Redis."""

    try:
        redis_client.setex(
            key,
            int(timeout),
            json.dumps(
                value,
                default=_redis_json_default,
            ),
        )
        return True

    except redis.RedisError as exc:
        print(f"REDIS SET ERROR [{key}]: {exc}")
        return False


# ==========================================================
# BASIC HELPERS
# ==========================================================

def _clean_string(value):
    """Safely convert a simple value to a stripped string."""

    if value is None:
        return ""

    if isinstance(value, (str, int, float)):
        return str(value).strip()

    return ""


def _to_bool(value):
    """Convert common API boolean representations to bool."""

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "1",
            "on",
            "available",
            "in stock",
            "instock",
        }

    return False


def _to_decimal(value, default="0.00"):
    """Convert a value to Decimal."""

    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal(default)


# ==========================================================
# PRICE HELPERS
# ==========================================================

def _extract_price(value):
    """
    Convert common price formats into Decimal.

    Supports values such as:

        49.99
        "49.99"
        "R49.99"
        "R 49,99"
        {"value": 49.99}
        {"amount": 49.99}
        {"price": 49.99}
    """

    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    # ------------------------------------------------------
    # NESTED PRICE OBJECT
    # ------------------------------------------------------

    if isinstance(value, dict):

        possible_fields = [
            "value",
            "amount",
            "price",
            "salePrice",
            "regularPrice",
            "currentPrice",
            "sellingPrice",
        ]

        nested_value = None

        for field in possible_fields:

            if field in value and value[field] is not None:
                nested_value = value[field]
                break

        if nested_value is None:
            return None

        return _extract_price(nested_value)

    # ------------------------------------------------------
    # STRING / NUMBER
    # ------------------------------------------------------

    try:

        text = str(value).strip()

        if not text:
            return None

        # Remove currency names/symbols.
        text = re.sub(
        r"(?i)\bZAR\b",
        "",
        text,
        )

        text = re.sub(
            r"(?i)\bR\s*",
            "",
            text,
        )

        text = text.replace(" ", "")


        # Handle South African-style decimal notation.
        if "," in text and "." not in text:
            text = text.replace(",", ".")

        elif "," in text and "." in text:
            text = text.replace(",", "")

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            text,
        )

        if not match:
            return None

        return Decimal(match.group(0))

    except (ValueError, TypeError, InvalidOperation):
        return None


def _extract_price_from_fields(product, fields):
    """Extract the first usable price from a list of fields."""

    if not isinstance(product, dict):
        return None

    for field in fields:

        if field not in product:
            continue

        value = _extract_price(product.get(field))

        if value is None:
            continue
        if "withoutdecimal" in field.lower():
            if value == value.to_integral_value():
                value /= Decimal("100")


        return value.quantize(Decimal("0.01"))

    return None


def _extract_checkers_price(product, *fields):
    """Extract price from specified Checkers fields."""

    return _extract_price_from_fields(
        product,
        fields,
    )


# ==========================================================
# PRODUCT ID
# ==========================================================

def _extract_product_id(product):
    """Extract the most useful product identifier."""

    if not isinstance(product, dict):
        return ""

    fields = [
        "external_id",
        "externalId",
        "productId",
        "product_id",
        "id",
        "sku",
        "code",
    ]

    for field in fields:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, dict):

            for nested_field in [
                "id",
                "productId",
                "product_id",
                "externalId",
                "external_id",
                "value",
            ]:

                nested_value = value.get(nested_field)

                if nested_value is not None:

                    nested_value = str(
                        nested_value
                    ).strip()

                    if nested_value:
                        return nested_value

        else:

            value = str(value).strip()

            if value:
                return value

    return ""


# ==========================================================
# IMAGE HELPERS
# ==========================================================

def _image_value(value):
    """Extract an image URL from a value."""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):

        for field in [
            "url",
            "image",
            "imageUrl",
            "imageURL",
            "src",
            "source",
        ]:

            nested = value.get(field)

            if isinstance(nested, str):

                nested = nested.strip()

                if nested:
                    return nested

    return ""


def _extract_image(product):
    """Extract the primary product image."""

    if not isinstance(product, dict):
        return ""

    image_fields = [
        "image",
        "imageUrl",
        "imageURL",
        "image_url",
        "thumbnail",
        "thumbnailUrl",
        "thumbnailURL",
        "thumbnail_url",
        "mainImage",
        "main_image",
        "primaryImage",
        "primary_image",
        "photo",
        "photoUrl",
        "photoURL",
        "src",
    ]

    for field in image_fields:

        image = _image_value(
            product.get(field)
        )

        if image:
            return image

    images = product.get("images")

    if isinstance(images, list):

        for image in images:

            image_url = _image_value(image)

            if image_url:
                return image_url

    media = product.get("media")

    if isinstance(media, list):

        for item in media:

            if not isinstance(item, dict):
                continue

            media_type = str(
                item.get(
                    "type",
                    item.get("mediaType", ""),
                )
            ).lower()

            if media_type and "image" not in media_type:
                continue

            image_url = _image_value(item)

            if image_url:
                return image_url

    return ""


def _extract_images(product):
    """Extract all available product images without duplicates."""

    if not isinstance(product, dict):
        return []

    images = []

    def add_image(value):
        if value and value not in images:
            images.append(value)

    add_image(
        _extract_image(product)
    )

    raw_images = product.get("images")

    if isinstance(raw_images, list):

        for image in raw_images:
            add_image(
                _image_value(image)
            )

    media = product.get("media")

    if isinstance(media, list):

        for item in media:

            if not isinstance(item, dict):
                continue

            media_type = str(
                item.get(
                    "type",
                    item.get("mediaType", ""),
                )
            ).lower()

            if media_type and "image" not in media_type:
                continue

            add_image(
                _image_value(item)
            )

    return images


# ==========================================================
# SALE / REGULAR PRICE
# ==========================================================

def _extract_sale_price(product):
    """Find the current/sale price."""

    return _extract_price_from_fields(
        product,
        [
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
        ],
    )


def _extract_regular_price(product):
    """Find the original/regular price."""

    return _extract_price_from_fields(
        product,
        [
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
            "regularPriceWithoutDecimal",
            "originalPriceWithoutDecimal",
        ],
    )
# ==========================================================
# rating
# ==========================================================
def _extract_rating(product):
    if not isinstance(product, dict):
        return Decimal("0.00")

    for field in [
        "rating",
        "averageRating",
        "average_rating",
        "reviewRating",
        "review_rating",
    ]:
        value = _to_decimal(
            product.get(field),
            default="0.00",
        )

        if value >= Decimal("0.00"):
            return value.quantize(
                Decimal("0.01")
            )

    return Decimal("0.00")

# ==========================================================
# PROMOTION
# ==========================================================

def _extract_promotion(product):
    """Extract promotion/deal name or description."""

    if not isinstance(product, dict):
        return ""

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

                nested_value = value.get(
                    nested_field
                )

                if nested_value is not None:

                    nested_value = str(
                        nested_value
                    ).strip()

                    if nested_value:
                        return nested_value

    return ""


def _extract_on_sale(
    product,
    regular_price=None,
    sale_price=None,
):
    """Determine whether a product is on promotion."""

    if not isinstance(product, dict):
        return False

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

    if (
        regular_price is not None
        and sale_price is not None
        and regular_price > sale_price
    ):
        return True

    if _extract_promotion(product):
        return True

    return False

def _extract_discount_amount(
    regular_price,
    sale_price,
    product,
):
    """Calculate discount amount."""

    if (
        regular_price is not None
        and sale_price is not None
        and regular_price > sale_price
    ):
        return (
            regular_price - sale_price
        ).quantize(
            Decimal("0.01")
        )

    return Decimal("0.00")

# ==========================================================
# COLOUR
# ==========================================================

def _extract_colour(product):
    """Extract product colour."""

    if not isinstance(product, dict):
        return "Not specified"

    direct_fields = [
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
    ]

    for field in direct_fields:

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
                "display_name",
            ]:

                nested_value = value.get(
                    nested_field
                )

                if isinstance(nested_value, str):

                    nested_value = (
                        nested_value.strip()
                    )

                    if nested_value:
                        return nested_value

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

            if (
                "colour" in str(key).lower()
                or "color" in str(key).lower()
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

    variants = product.get("variants")

    if isinstance(variants, list):

        for variant in variants:

            if not isinstance(variant, dict):
                continue

            for field in [
                "colour",
                "color",
                "colourName",
                "colorName",
                "variantColour",
                "variantColor",
            ]:

                value = variant.get(field)

                if isinstance(value, str):

                    value = value.strip()

                    if value:
                        return value

    return "Not specified"


# ==========================================================
# CATEGORY
# ==========================================================

def _extract_category(product):
    """Extract product category."""

    if not isinstance(product, dict):
        return "Other"

    direct_fields = [
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
    ]

    for field in direct_fields:

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
            return category_values[-1]

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

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or ""
    )

    name_lower = str(name).strip().lower()

    category_keywords = {
        "ice cream": "Ice Cream",
        "pet food": "Pet Food",
        "cat food": "Pet Food",
        "dog food": "Pet Food",
        "toilet paper": "Household",
        "paper towel": "Household",
        "washing powder": "Cleaning",
        "dishwashing": "Cleaning",
        "toothpaste": "Personal Care",
        "conditioner": "Personal Care",
        "deodorant": "Personal Care",
        "shampoo": "Personal Care",
        "lotion": "Personal Care",
        "margarine": "Margarine",
        "yoghurt": "Yoghurt",
        "yogurt": "Yoghurt",
        "chocolate": "Chocolate",
        "biscuits": "Biscuits",
        "biscuit": "Biscuits",
        "cookies": "Biscuits",
        "cookie": "Biscuits",
        "cereal": "Cereal",
        "coffee": "Coffee",
        "tea": "Tea",
        "milk": "Milk",
        "cheese": "Cheese",
        "butter": "Butter",
        "juice": "Juice",
        "water": "Water",
        "bread": "Bread",
        "rolls": "Bread",
        "loaf": "Bread",
        "sugar": "Sugar",
        "rice": "Rice",
        "pasta": "Pasta",
        "flour": "Flour",
        "ketchup": "Sauces",
        "mayonnaise": "Sauces",
        "sauce": "Sauces",
        "chips": "Snacks",
        "crisps": "Snacks",
        "snacks": "Snacks",
        "snack": "Snacks",
        "chicken": "Meat",
        "beef": "Meat",
        "pork": "Meat",
        "sausage": "Meat",
        "fish": "Fish",
        "eggs": "Eggs",
        "egg": "Eggs",
        "vegetables": "Vegetables",
        "vegetable": "Vegetables",
        "fruits": "Fruit",
        "fruit": "Fruit",
        "frozen": "Frozen Food",
        "pizza": "Frozen Food",
        "diapers": "Baby",
        "diaper": "Baby",
        "baby": "Baby",
        "detergent": "Cleaning",
        "cleaner": "Cleaning",
        "soap": "Personal Care",
    }

    for keyword, category in sorted(
        category_keywords.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):

        if keyword in name_lower:
            return category

    return "Other"


# ==========================================================
# SIZE
# ==========================================================

def _extract_size(product):
    """Extract product size."""

    if not isinstance(product, dict):
        return "Not specified"

    direct_fields = [
        "size",
        "sizeName",
        "size_name",
        "sizeValue",
        "size_value",
        "productSize",
        "product_size",
        "variantSize",
        "variant_size",
    ]

    for field in direct_fields:

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

            if "size" in attribute_name:

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

    elif isinstance(attributes, dict):

        for key, value in attributes.items():

            if "size" not in str(key).lower():
                continue

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

                if value is not None:

                    value = str(value).strip()

                    if value:
                        return value

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

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or ""
    )

    name = str(name).strip()

    if name:

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

    return "Not specified"


# ==========================================================
# STORE ID
# ==========================================================

def _extract_store_id(product):
    """Extract Checkers store/branch ID."""

    if not isinstance(product, dict):
        return ""

    for field in [
        "storeId",
        "store_id",
        "branchId",
        "branch_id",
        "fulfilmentStoreId",
        "fulfillmentStoreId",
        "fulfilment_store_id",
        "fulfillment_store_id",
    ]:

        value = product.get(field)

        if value is None:
            continue

        if isinstance(value, dict):

            for nested_field in [
                "storeId",
                "store_id",
                "branchId",
                "branch_id",
                "id",
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

        else:

            value = str(value).strip()

            if value:
                return value

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

        if not isinstance(store, dict):
            continue

        for nested_field in [
            "storeId",
            "store_id",
            "branchId",
            "branch_id",
            "id",
        ]:

            value = store.get(
                nested_field
            )

            if value is not None:

                value = str(value).strip()

                if value:
                    return value

    return ""


# ==========================================================
# STORE LOCATION
# ==========================================================
def _build_location(data):
    """Build a human-readable store location from Checkers store data."""

    if not isinstance(data, dict):
        return ""

    # ------------------------------------------------------
    # 1. DIRECT FORMATTED ADDRESS
    # ------------------------------------------------------

    direct_fields = [
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
        "addressLine",
        "address_line",
    ]

    for field in direct_fields:
        value = data.get(field)

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

    # ------------------------------------------------------
    # 2. BUILD ADDRESS FROM INDIVIDUAL FIELDS
    # ------------------------------------------------------

    parts = []

    address_fields = [
        "storeName",
        "store_name",
        "branchName",
        "branch_name",
        "name",
        "street",
        "streetAddress",
        "street_address",
        "addressLine1",
        "address_line_1",
        "addressLine2",
        "address_line_2",
        "suburb",
        "town",
        "city",
        "province",
        "state",
        "postalCode",
        "postal_code",
        "postcode",
        "zipCode",
        "zip_code",
    ]

    for field in address_fields:
        value = data.get(field)

        if value is None:
            continue

        if isinstance(value, (str, int, float)):
            value = str(value).strip()

            if value and value not in parts:
                parts.append(value)

    if parts:
        return ", ".join(parts)

    # ------------------------------------------------------
    # 3. NESTED ADDRESS OBJECT
    # ------------------------------------------------------

    for field in [
        "address",
        "storeAddress",
        "store_address",
        "location",
        "storeLocation",
        "store_location",
        "branch",
        "store",
    ]:

        nested = data.get(field)

        if isinstance(nested, dict):

            location = _build_location(nested)

            if location:
                return location

    # ------------------------------------------------------
    # 4. NESTED LOCATION OBJECTS
    # ------------------------------------------------------

    for field in [
        "contact",
        "details",
        "storeDetails",
        "store_details",
        "metadata",
    ]:

        nested = data.get(field)

        if isinstance(nested, dict):

            location = _build_location(nested)

            if location:
                return location

    return ""


def _extract_store_location(product):
    """Try to find store location directly in product data."""

    if not isinstance(product, dict):
        return "Location not available"

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
    ]:

        value = product.get(field)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

        elif isinstance(value, dict):

            location = _build_location(value)

            if location:
                return location

    address = product.get("address")

    if isinstance(address, str):

        address = address.strip()

        if address:
            return address

    elif isinstance(address, dict):

        location = _build_location(address)

        if location:
            return location

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

            location = _build_location(store)

            if location:
                return location

    return "Location not available"


# ==========================================================
# GET STORE LOCATION
# ==========================================================

def get_store_location(store_id):
    """Resolve Checkers store ID into a human-readable location."""

    store_id = str(store_id or "").strip()

    if not store_id:
        return "Location not available"

    cache_key = f"checkers_store_{store_id}"

    # ------------------------------------------------------
    # REDIS CACHE
    # ------------------------------------------------------

    try:

        cached = redis_client.get(cache_key)

    except redis.RedisError as exc:

        print(
            f"GET STORE REDIS ERROR "
            f"{store_id}: {exc}"
        )

        cached = None

    if cached:

        print(
            f"GET STORE CACHE HIT: "
            f"{store_id} -> {cached}"
        )

        return cached

    # ------------------------------------------------------
    # API KEY
    # ------------------------------------------------------

    api_key = getattr(
        settings,
        "PARSE_API_KEY",
        "",
    )

    if not api_key:

        print(
            "GET STORE: PARSE_API_KEY missing"
        )

        return "Location not available"

    print(
        "\n========================================"
    )
    print(
        "GET STORE CACHE MISS"
    )
    print(
        "STORE ID:",
        store_id,
    )
    print(
        "CALLING CHECKERS STORE API"
    )
    print(
        "========================================"
    )

    # ------------------------------------------------------
    # REQUEST
    # ------------------------------------------------------

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

        print(
            "GET STORE STATUS:",
            response.status_code,
        )

        if response.status_code == 429:

            print(
                f"GET STORE RATE LIMITED: "
                f"{store_id}"
            )

            return "Location temporarily unavailable"

        response.raise_for_status()

    except requests.Timeout as exc:

        print(
            f"GET STORE TIMEOUT "
            f"for {store_id}: {exc}"
        )

        return "Location not available"

    except requests.HTTPError as exc:

        print(
            f"GET STORE HTTP ERROR "
            f"for {store_id}: {exc}"
        )

        return "Location not available"

    except requests.RequestException as exc:

        print(
            f"GET STORE REQUEST FAILED "
            f"for {store_id}: {exc}"
        )

        return "Location not available"

    # ------------------------------------------------------
    # JSON
    # ------------------------------------------------------

    try:
        data = response.json()

    except ValueError:

        print(
            "GET STORE returned invalid JSON"
        )

        return "Location not available"

    print("\n========== CHECKERS STORE API RESPONSE ==========")
    print(json.dumps(data, indent=2, default=str))
    print("==================================================\n")


    # ------------------------------------------------------
    # FIND STORE OBJECT
    # ------------------------------------------------------

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

    if not isinstance(store, dict):

        print(
            "GET STORE: "
            "Could not find store object"
        )

        return "Location not available"

    # ------------------------------------------------------
    # LOCATION
    # ------------------------------------------------------

    location = _build_location(store)

    if not location:
        print(
            "GET STORE: No recognized address fields."
        )

        print(
            "AVAILABLE STORE KEYS:",
            list(store.keys()),
        )

        print(
            "FULL STORE OBJECT:",
            json.dumps(
                store,
                indent=2,
                default=str,
            ),
        )

        return "Location not available"

    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    try:

        redis_client.setex(
            cache_key,
            CACHE_TIMEOUT,
            location,
        )

    except redis.RedisError as exc:

        print(
            f"GET STORE CACHE ERROR "
            f"{store_id}: {exc}"
        )

    print(
        f"GET STORE LOCATION CACHED: "
        f"{location}"
    )

    return location


# ==========================================================
# DEAL EXPIRY
# ==========================================================

def _extract_deal_expiry(product):
    """Extract promotion/deal expiry date."""

    if not isinstance(product, dict):
        return ""

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
    """Save normalized product to Redis."""

    if not isinstance(product, dict):
        return

    product_id = str(
        product.get("external_id")
        or product.get("id")
        or ""
    ).strip()

    if not product_id:
        return

    _redis_set_json(
        f"checkers_product_{product_id}",
        product,
        CACHE_TIMEOUT,
    )

    print(
        f"PRODUCT SAVED TO REDIS: "
        f"{product_id}"
    )


# ==========================================================
# GET PRODUCT
# ==========================================================

def get_product(product_id):
    """Retrieve a product from Redis."""

    product_id = str(
        product_id or ""
    ).strip()

    if not product_id:

        raise StoreAPIError(
            "No product ID was provided."
        )

    cache_key = (
        f"checkers_product_{product_id}"
    )

    product = _redis_get_json(cache_key)

    if product is None:

        print(
            f"PRODUCT CACHE MISS: "
            f"{product_id}"
        )

        raise StoreAPIError(
            f"Product '{product_id}' "
            "could not be found in Redis cache. "
            "Search for the product again."
        )

    print(
        f"PRODUCT CACHE HIT: "
        f"{product_id}"
    )

    return product


# ==========================================================
# SEARCH PRODUCTS
# ==========================================================

def search_products(
    keyword="",
    limit=100,
):
    """Search Checkers products."""

    keyword = (keyword or "").strip()

    if not keyword:
        return []

    # ------------------------------------------------------
    # LIMIT
    # ------------------------------------------------------

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 100

    limit = max(
        1,
        min(limit, 100),
    )

    # ------------------------------------------------------
    # CACHE KEY
    # ------------------------------------------------------

    cache_key = (
        f"checkers_search:"
        f"{keyword.lower()}:"
        f"{limit}"
    )

    # ------------------------------------------------------
    # REDIS
    # ------------------------------------------------------

    cached_products = _redis_get_json(
        cache_key
    )

    if cached_products is not None:

        print(
            "\n========================================"
        )
        print(
            "CHECKERS SEARCH REDIS HIT"
        )
        print(
            "KEY:",
            cache_key,
        )
        print(
            "QUERY:",
            keyword,
        )
        print(
            "PRODUCTS:",
            len(cached_products),
        )
        print(
            "API CALL: NO"
        )
        print(
            "========================================\n"
        )

        return cached_products

    print(
        "\n========================================"
    )
    print(
        "CHECKERS SEARCH REDIS MISS"
    )
    print(
        "KEY:",
        cache_key,
    )
    print(
        "QUERY:",
        keyword,
    )
    print(
        "CALLING CHECKERS API"
    )
    print(
        "========================================\n"
    )

    # ------------------------------------------------------
    # API KEY
    # ------------------------------------------------------

    api_key = getattr(
        settings,
        "PARSE_API_KEY",
        "",
    )

    if not api_key:

        raise StoreAPIError(
            "PARSE_API_KEY is not configured "
            "in settings.py."
        )

    # ------------------------------------------------------
    # REQUEST
    # ------------------------------------------------------

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

        if response.status_code == 429:

            raise StoreAPIError(
                "Checkers API rate limit reached. "
                "Please try again shortly."
            )

        response.raise_for_status()

    except StoreAPIError:
        raise

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
            f"Unable to connect to Checkers API: "
            f"{exc}"
        ) from exc

    # ------------------------------------------------------
    # JSON
    # ------------------------------------------------------

    try:

        data = response.json()
        print("=" * 80)
        print("CHECKERS RAW SEARCH RESPONSE")
        print(json.dumps(data, indent=2))
        print("=" * 80)


    except ValueError as exc:

        raise StoreAPIError(
            "Checkers API did not return valid JSON: "
            f"{response.text[:500]}"
        ) from exc

    # ------------------------------------------------------
    # FIND PRODUCTS
    # ------------------------------------------------------

    raw_products = []

    if isinstance(data, dict):

        possible_lists = [
            data.get("products"),
            data.get("results"),
            data.get("items"),
        ]

        for candidate in possible_lists:

            if isinstance(candidate, list):

                raw_products = candidate
                break

        if not raw_products:

            nested = data.get("data")

            if isinstance(nested, list):

                raw_products = nested

            elif isinstance(nested, dict):

                for field in [
                    "products",
                    "results",
                    "items",
                ]:

                    candidate = nested.get(field)

                    if isinstance(candidate, list):

                        raw_products = candidate
                        break

    elif isinstance(data, list):

        raw_products = data

    # ------------------------------------------------------
    # EMPTY RESULT
    # ------------------------------------------------------

    if not raw_products:

        _redis_set_json(
            cache_key,
            [],
            EMPTY_CACHE_TIMEOUT,
        )

        print(
            "CHECKERS SEARCH: "
            "No products found."
        )

        return []

    # ------------------------------------------------------
    # NORMALIZE
    # ------------------------------------------------------

    products = []

    for raw_product in raw_products:

        if not isinstance(
            raw_product,
            dict,
        ):
            continue

        try:

            normalized = normalize_product(
                raw_product,
                resolve_store=True,
            )

            if not normalized.get("id"):

                print(
                    "CHECKERS PRODUCT "
                    "SKIPPED: No product ID"
                )

                continue

            _cache_product(
                normalized
            )

            products.append(
                normalized
            )

        except Exception as exc:

            print(
                "Could not normalize "
                "Checkers product:",
                exc,
            )

    # ------------------------------------------------------
    # CACHE SEARCH
    # ------------------------------------------------------

    _redis_set_json(
        cache_key,
        products,
        CACHE_TIMEOUT,
    )

    print(
        "\n========================================"
    )
    print(
        "CHECKERS SEARCH SAVED TO REDIS"
    )
    print(
        "KEY:",
        cache_key,
    )
    print(
        "PRODUCTS:",
        len(products),
    )
    print(
        "TTL:",
        CACHE_TIMEOUT,
    )
    print(
        "========================================\n"
    )

    return products


# ==========================================================
# NORMALIZE PRODUCT
# ==========================================================

def normalize_product(
    product,
    resolve_store=True,
):
    """
    Convert a raw Checkers API product into the application's
    normalized product format.
    """

    if not isinstance(product, dict):

        raise StoreAPIError(
            "Invalid Checkers product data."
        )

    # ------------------------------------------------------
    # ID
    # ------------------------------------------------------

    product_id = _extract_product_id(
        product
    )

    # ------------------------------------------------------
    # RAW IDs
    # ------------------------------------------------------

    raw_id = product.get("id")
    raw_product_id = product.get("productId")
    raw_product_id_underscore = product.get("product_id")
    raw_sku = product.get("sku")
    raw_code = product.get("code")

    # ------------------------------------------------------
    # NAME
    # ------------------------------------------------------

    name = (
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or "Unknown Checkers Product"
    )

    name = str(name).strip()

    # ------------------------------------------------------
    # DESCRIPTION
    # ------------------------------------------------------

    description = (
        product.get("description")
        or product.get("shortDescription")
        or product.get("longDescription")
        or ""
    )

    if not isinstance(description, str):
        description = str(description)

    # ------------------------------------------------------
    # PRICES
    # ------------------------------------------------------

    sale_price = _extract_sale_price(product)
    regular_price = _extract_regular_price(product)

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

    sale_price = sale_price.quantize(
        Decimal("0.01")
    )

    regular_price = regular_price.quantize(
        Decimal("0.01")
    )

    # ------------------------------------------------------
    # PROMOTION
    # ------------------------------------------------------

    promotion = _extract_promotion(
        product
    )

    on_sale = _extract_on_sale(
        product,
        regular_price=regular_price,
        sale_price=sale_price,
    )

    if promotion and regular_price > sale_price:
        on_sale = True

    if regular_price < sale_price:
        regular_price = sale_price
        on_sale = False


    # ------------------------------------------------------
    # DISCOUNT
    # ------------------------------------------------------

    discount_amount = _extract_discount_amount(
        regular_price,
        sale_price,
        product,
    )

    if (
        regular_price > Decimal("0.00")
        and sale_price < regular_price
    ):

        discount_percentage = (
            (
                regular_price - sale_price
            )
            / regular_price
            * Decimal("100")
        ).quantize(
            Decimal("0.01")
        )

    else:

        discount_percentage = Decimal(
            "0.00"
        )

    # ------------------------------------------------------
    # EXPIRY
    # ------------------------------------------------------

    deal_expiry = _extract_deal_expiry(
        product
    )

    # ------------------------------------------------------
    # BRAND
    # ------------------------------------------------------

    brand = (
        product.get("brand")
        or product.get("brandName")
        or "Unknown"
    )

    if isinstance(brand, dict):

        brand = (
            brand.get("name")
            or brand.get("value")
            or brand.get("label")
            or "Unknown"
        )

    brand = str(brand).strip()

    # ------------------------------------------------------
    # CATEGORY
    # ------------------------------------------------------

    category = _extract_category(
        product
    )

    # ------------------------------------------------------
    # COLOUR
    # ------------------------------------------------------

    colour = _extract_colour(
        product
    )

    # ------------------------------------------------------
    # SIZE
    # ------------------------------------------------------

    size = _extract_size(
        product
    )

    # ------------------------------------------------------
    # STORE
    # ------------------------------------------------------

    store_location = _extract_store_location(
            product
        )
    
    store_id = _extract_store_id(
        product
    )
    print(
    f"CHECKERS STORE DEBUG | "
    f"product={name} | "
    f"store_id={store_id} | "
    f"location={store_location}")

    if (
    resolve_store
    and store_id
    and (
        not store_location
        or store_location == "Location not available"
    )
    ):
        store_location = get_store_location(store_id)

    print(
        f"CHECKERS STORE FINAL | "
        f"store_id={store_id} | "
        f"location={store_location}"
    )
    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

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

            if isinstance(value, dict):

                for nested_field in [
                    "quantity",
                    "available",
                    "stock",
                    "value",
                    "count",
                ]:

                    nested_value = value.get(
                        nested_field
                    )

                    if nested_value is not None:

                        value = nested_value
                        break

            if isinstance(value, bool):

                stock = 1 if value else 0
                break

            parsed_stock = int(
                float(value)
            )

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

    # ------------------------------------------------------
    # IMAGES
    # ------------------------------------------------------

    image = _extract_image(
        product
    )

    images = _extract_images(
        product
    )

    # ------------------------------------------------------
    # URL
    # ------------------------------------------------------

    url = (
        product.get("url")
        or product.get("productUrl")
        or product.get("productURL")
        or product.get("product_url")
        or product.get("link")
        or ""
    )

    if not isinstance(url, str):
        url = str(url)

    url = url.strip()

    # ------------------------------------------------------
    # COST
    # ------------------------------------------------------

    shipping_cost = Decimal(
        "0.00"
    )

    current_price = sale_price

    total_cost = (
        current_price + shipping_cost
    ).quantize(
        Decimal("0.01")
    )

    # ------------------------------------------------------
    # NORMALIZED PRODUCT
    # ------------------------------------------------------

    return {
        # IDENTIFIERS
        "id": product_id,
        "external_id": product_id,

        "raw_id": raw_id,
        "raw_product_id": raw_product_id,
        "raw_product_id_underscore": (
            raw_product_id_underscore
        ),
        "raw_sku": raw_sku,
        "raw_code": raw_code,

        # SOURCE
        "source": "checkers",

        # BASIC INFORMATION
        "name": name,
        "title": name,
        "description": description,

        # PRODUCT INFORMATION
        "brand": brand,
        "category": category,
        "colour": colour,
        "size": size,

        # PRICE
        "price": current_price,
        "regular_price": regular_price,
        "sale_price": (
            current_price
            if on_sale
            else None
        ),

        # PROMOTION
        "on_sale": on_sale,
        "promotion": promotion,
        "discount_amount": discount_amount,
        "discount_percentage": (
            discount_percentage
        ),
        "deal_expiry": deal_expiry,

        # COST
        "shipping_cost": shipping_cost,
        "total_cost": total_cost,

        # STOCK
        "stock": stock,
        "rating": _extract_rating(product),


        # STORE
        "store": "Checkers",
        "store_id": store_id,
        "location": store_location,

        # IMAGES
        "image": image,
        "thumbnail": image,
        "images": images,

        # URL
        "url": url,
    }
