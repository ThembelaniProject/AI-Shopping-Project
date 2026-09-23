# products/services/store_api.py

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation

import redis
import requests

from django.conf import settings


# ============================================================
# CONFIGURATION
# ============================================================

PARSE_API_KEY = (
    getattr(settings, "PARSE_API_KEY", None)
    or os.environ.get("PARSE_API_KEY")
)

if not PARSE_API_KEY:
    raise RuntimeError(
        "PARSE_API_KEY is not configured. "
        "Add PARSE_API_KEY to your Django settings.py or .env file."
    )


# ============================================================
# REDIS
# ============================================================

REDIS_URL = (
    getattr(settings, "REDIS_URL", None)
    or os.environ.get("REDIS_URL")
)

if not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL is not configured. "
        "Add REDIS_URL to your Django settings.py or .env file."
    )

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


CACHE_TIMEOUT = 60 * 60 * 24
EMPTY_CACHE_TIMEOUT = 60
STORE_ERROR_CACHE_TIMEOUT = 60

REQUEST_TIMEOUT = 30


# ============================================================
# PARSE.BOT SCRAPER IDS
# ============================================================

CHECKERS_SCRAPER_ID = (
    "a7a3a4ba-dfb7-4476-9712-8753b2fb3140"
)

PNP_SCRAPER_ID = (
    "b87810bc-903f-41b8-b38d-c5c911cab324"
)

RETAILER3_SCRAPER_ID = (
    "98bf936f-1cdc-4e00-b994-5c44eb2d1d31"
)


# ============================================================
# PARSE.BOT SNAPSHOT VERSIONS
# ============================================================

CHECKERS_SNAPSHOT_VERSION = "9"
PNP_SNAPSHOT_VERSION = "9"
RETAILER3_SNAPSHOT_VERSION = "8"


# ============================================================
# PARSE.BOT BASE
# ============================================================

PARSE_BASE_URL = "https://api.parse.bot/scraper"


# ============================================================
# CHECKERS API
# ============================================================

CHECKERS_SEARCH_URL = (
    f"{PARSE_BASE_URL}/"
    f"{CHECKERS_SCRAPER_ID}/"
    "search_products"
)

CHECKERS_STORE_URL = (
    f"{PARSE_BASE_URL}/"
    f"{CHECKERS_SCRAPER_ID}/"
    "get_store"
)


# ============================================================
# PICK N PAY API
# ============================================================

PNP_SEARCH_URL = (
    f"{PARSE_BASE_URL}/"
    f"{PNP_SCRAPER_ID}/"
    "search_products"
)

PNP_SPECIALS_URL = (
    f"{PARSE_BASE_URL}/"
    f"{PNP_SCRAPER_ID}/"
    "get_specials"
)

PNP_STORES_URL = (
    f"{PARSE_BASE_URL}/"
    f"{PNP_SCRAPER_ID}/"
    "get_stores"
)

PNP_STORE_PRODUCTS_URL = (
    f"{PARSE_BASE_URL}/"
    f"{PNP_SCRAPER_ID}/"
    "search_store_products"
)


# ============================================================
# RETAILER 3 API
# ============================================================

RETAILER3_SEARCH_URL = (
    f"{PARSE_BASE_URL}/"
    f"{RETAILER3_SCRAPER_ID}/"
    "search_products"
)

RETAILER3_SPECIALS_URL = (
    f"{PARSE_BASE_URL}/"
    f"{RETAILER3_SCRAPER_ID}/"
    "get_all_specials"
)

RETAILER3_STORE_LOCATOR_URL = (
    f"{PARSE_BASE_URL}/"
    f"{RETAILER3_SCRAPER_ID}/"
    "get_store_locator"
)

RETAILER3_COMPARE_PRICES_URL = (
    f"{PARSE_BASE_URL}/"
    f"{RETAILER3_SCRAPER_ID}/"
    "compare_prices"
)


# ============================================================
# ERROR
# ============================================================

class StoreAPIError(Exception):
    pass


# ============================================================
# JSON / REDIS HELPERS
# ============================================================

def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def _cache_set(
    key,
    value,
    timeout=CACHE_TIMEOUT,
):
    try:
        redis_client.setex(
            key,
            timeout,
            json.dumps(
                value,
                default=_json_default,
            ),
        )
    except Exception:
        # Redis must never crash Django.
        pass


def _cache_get(key):
    try:
        value = redis_client.get(key)

        if not value:
            return None

        return json.loads(value)

    except Exception:
        return None


# ============================================================
# GENERAL HELPERS
# ============================================================

def _safe_string(
    value,
    default="",
):
    if value is None:
        return default

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _safe_bool(
    value,
    default=False,
):
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "1",
            "yes",
            "y",
            "available",
            "in stock",
            "instock",
        }

    return bool(value)


def _to_decimal(
    value,
    default="0",
):
    if value is None:
        return Decimal(default)

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    if isinstance(value, dict):

        for key in (
            "value",
            "amount",
            "price",
            "current",
            "current_price",
            "sale_price",
            "special_price",
            "regular_price",
            "oldPrice",
            "old_price",
        ):

            if key in value:

                result = _to_decimal(
                    value[key],
                    default=default,
                )

                if result != Decimal(default):
                    return result

        return Decimal(default)

    text = str(value).strip()

    if not text:
        return Decimal(default)

    # Remove currency letters/symbols.
    text = re.sub(
        r"[^\d,.\-]",
        "",
        text,
    )

    # R49,99 -> 49.99
    if "," in text and "." not in text:
        text = text.replace(",", ".")

    # 1,299.99 -> 1299.99
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return Decimal(text)

    except (
        InvalidOperation,
        ValueError,
    ):
        return Decimal(default)


def _price_number(value):
    return float(
        _to_decimal(value)
    )


# ============================================================
# RETAILER KEY
# ============================================================

def _retailer_key(
    retailer,
):
    return (
        _safe_string(
            retailer,
            "Checkers",
        )
        .lower()
        .replace(" ", "_")
    )


# ============================================================
# PRODUCT ID
# ============================================================

def _extract_product_id(product):
    if not isinstance(product, dict):
        return ""

    for key in (
        "id",
        "product_id",
        "productId",
        "productID",
        "sku",
        "code",
        "product_code",
        "productCode",
        "external_id",
        "externalId",
    ):

        value = product.get(key)

        if value is not None:

            value = str(value).strip()

            if value:
                return value

    return ""


# ============================================================
# STORE ID
# ============================================================

def _extract_store_id(product):
    """
    Extract store/branch ID from a product or store object.

    This function is required by products/views.py.
    """

    if not isinstance(product, dict):
        return ""

    # --------------------------------------------------------
    # Direct store ID
    # --------------------------------------------------------

    for key in (
        "store_id",
        "storeId",
        "storeID",
        "store_code",
        "storeCode",
        "store_code_id",
        "branch_id",
        "branchId",
        "branchID",
        "branch_code",
        "branchCode",
    ):

        value = product.get(key)

        if value is not None:

            value = str(value).strip()

            if value:
                return value

    # --------------------------------------------------------
    # Nested store
    # --------------------------------------------------------

    store = product.get("store")

    if isinstance(store, dict):

        for key in (
            "id",
            "store_id",
            "storeId",
            "storeID",
            "store_code",
            "storeCode",
            "code",
        ):

            value = store.get(key)

            if value is not None:

                value = str(value).strip()

                if value:
                    return value

    # --------------------------------------------------------
    # Nested branch
    # --------------------------------------------------------

    branch = product.get("branch")

    if isinstance(branch, dict):

        for key in (
            "id",
            "branch_id",
            "branchId",
            "branch_code",
            "branchCode",
            "code",
        ):

            value = branch.get(key)

            if value is not None:

                value = str(value).strip()

                if value:
                    return value

    # --------------------------------------------------------
    # Nested location
    # --------------------------------------------------------

    location = product.get("location")

    if isinstance(location, dict):

        for key in (
            "store_id",
            "storeId",
            "storeID",
            "store_code",
            "storeCode",
            "branch_id",
            "branchId",
            "branch_code",
            "branchCode",
        ):

            value = location.get(key)

            if value is not None:

                value = str(value).strip()

                if value:
                    return value

    return ""


# ============================================================
# STABLE PRODUCT ID
# ============================================================

def _stable_product_id(
    retailer,
    product,
):
    raw_id = _extract_product_id(
        product
    )

    retailer_key = _retailer_key(
        retailer
    )

    if raw_id:
        return (
            f"{retailer_key}_"
            f"{raw_id}"
        )

    name = _safe_string(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or product.get("productName")
    )

    price = str(
        _extract_price_from_fields(
            product
        )
    )

    seed = (
        f"{retailer}|"
        f"{name}|"
        f"{price}"
    )

    digest = hashlib.sha256(
        seed.encode("utf-8")
    ).hexdigest()[:16]

    return (
        f"{retailer_key}_"
        f"{digest}"
    )


# ============================================================
# PRICE EXTRACTION
# ============================================================

def _extract_price_from_fields(product):

    if not isinstance(product, dict):
        return Decimal("0")

    for field in (
        "price",
        "current_price",
        "currentPrice",
        "sale_price",
        "salePrice",
        "special_price",
        "specialPrice",
        "selling_price",
        "sellingPrice",
        "amount",
    ):

        if field not in product:
            continue

        price = _to_decimal(
            product.get(field)
        )

        if price > 0:
            return price

    return Decimal("0")


def _extract_regular_price(product):

    if not isinstance(product, dict):
        return Decimal("0")

    for field in (
        "regular_price",
        "regularPrice",
        "original_price",
        "originalPrice",
        "old_price",
        "oldPrice",
        "was_price",
        "wasPrice",
        "list_price",
        "listPrice",
    ):

        if field not in product:
            continue

        price = _to_decimal(
            product.get(field)
        )

        if price > 0:
            return price

    return Decimal("0")


# ============================================================
# IMAGE HELPERS
# ============================================================

def _extract_image(product):

    if not isinstance(product, dict):
        return ""

    for key in (
        "image",
        "image_url",
        "imageUrl",
        "thumbnail",
        "thumbnail_url",
        "thumbnailUrl",
    ):

        value = product.get(key)

        if isinstance(value, str):

            value = value.strip()

            if value:
                return value

    images = product.get(
        "images"
    )

    if isinstance(images, list):

        for image in images:

            if isinstance(image, str):

                if image.strip():
                    return image.strip()

            elif isinstance(image, dict):

                for key in (
                    "url",
                    "image",
                    "src",
                ):

                    value = image.get(key)

                    if value:
                        return str(value)

    return ""


def _extract_images(product):

    if not isinstance(product, dict):
        return []

    images = product.get(
        "images"
    )

    if isinstance(images, list):

        output = []

        for image in images:

            if isinstance(image, str):

                if image.strip():
                    output.append(
                        image.strip()
                    )

            elif isinstance(image, dict):

                for key in (
                    "url",
                    "image",
                    "src",
                ):

                    value = image.get(key)

                    if value:
                        output.append(
                            str(value)
                        )
                        break

        return output

    image = _extract_image(
        product
    )

    if image:
        return [image]

    return []


# ============================================================
# LOCATION
# ============================================================

def _build_location(store):

    if not isinstance(store, dict):
        return {}

    address = (
        store.get("address")
        or store.get("location")
        or {}
    )

    if isinstance(address, str):

        address_text = address

    elif isinstance(address, dict):

        address_parts = [
            address.get("street"),
            address.get("street_address"),
            address.get("address_line_1"),
            address.get("addressLine1"),
            address.get("suburb"),
            address.get("city"),
            address.get("province"),
            address.get("postal_code"),
            address.get("postcode"),
        ]

        address_text = ", ".join(
            str(value)
            for value in address_parts
            if value
        )

    else:

        address_text = ""

    latitude = (
        store.get("latitude")
        or store.get("lat")
    )

    longitude = (
        store.get("longitude")
        or store.get("lng")
        or store.get("lon")
    )

    return {
        "store_id": _safe_string(
            store.get("id")
            or store.get("store_id")
            or store.get("storeId")
            or store.get("code")
        ),

        "name": _safe_string(
            store.get("name")
            or store.get("store_name")
            or store.get("storeName")
        ),

        "address": address_text,

        "city": _safe_string(
            store.get("city")
        ),

        "province": _safe_string(
            store.get("province")
        ),

        "postal_code": _safe_string(
            store.get("postal_code")
            or store.get("postcode")
        ),

        "latitude": latitude,
        "longitude": longitude,
    }


# ============================================================
# PARSE.BOT REQUEST
# ============================================================

def _parse_request(
    url,
    snapshot_version,
    params=None,
    method="GET",
):
    headers = {
        "X-API-Key": PARSE_API_KEY,
        "API-Snapshot-Version": str(
            snapshot_version
        ),
        "Accept": "application/json",
    }

    try:

        if method.upper() == "POST":

            response = requests.post(
                url,
                headers=headers,
                json=params or {},
                timeout=REQUEST_TIMEOUT,
            )

        else:

            response = requests.get(
                url,
                headers=headers,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )

    except requests.Timeout as exc:

        raise StoreAPIError(
            f"API timeout: {url}"
        ) from exc

    except requests.RequestException as exc:

        raise StoreAPIError(
            f"API connection error: {exc}"
        ) from exc

    if response.status_code == 401:

        raise StoreAPIError(
            "Parse.bot authentication failed. "
            "Check PARSE_API_KEY."
        )

    if response.status_code == 403:

        raise StoreAPIError(
            "Parse.bot access denied. "
            "Check API key and scraper permissions."
        )

    if response.status_code == 429:

        raise StoreAPIError(
            "Parse.bot rate limit reached."
        )

    if response.status_code >= 400:

        raise StoreAPIError(
            f"Parse.bot returned HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    try:

        return response.json()

    except ValueError as exc:

        raise StoreAPIError(
            "Parse.bot returned invalid JSON."
        ) from exc


# ============================================================
# RESPONSE HELPERS
# ============================================================

def _response_data(payload):

    if not isinstance(payload, dict):
        return payload

    return payload.get(
        "data",
        payload
    )


def _extract_raw_products(data):

    if not data:
        return []

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    # Direct response
    for key in (
        "products",
        "results",
        "items",
    ):

        value = data.get(key)

        if isinstance(value, list):
            return value

    # data.products
    nested_data = data.get(
        "data"
    )

    if isinstance(nested_data, dict):

        for key in (
            "products",
            "results",
            "items",
        ):

            value = nested_data.get(key)

            if isinstance(value, list):
                return value

    # result.products
    result = data.get(
        "result"
    )

    if isinstance(result, dict):

        products = _extract_raw_products(
            result
        )

        if products:
            return products

    # response.products
    response = data.get(
        "response"
    )

    if isinstance(response, dict):

        products = _extract_raw_products(
            response
        )

        if products:
            return products

    return []


# ============================================================
# NORMALIZE PRODUCT
# ============================================================

def normalize_product(
    product,
    resolve_store=False,
    retailer="Checkers",
):

    if not isinstance(product, dict):
        product = {}

    retailer = _safe_string(
        retailer,
        "Checkers"
    )

    raw_id = _extract_product_id(
        product
    )

    name = _safe_string(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or product.get("productName"),
        "Unknown product",
    )

    description = _safe_string(
        product.get("description")
        or product.get("short_description")
        or product.get("shortDescription")
    )

    sale_price = _extract_price_from_fields(
        product
    )

    regular_price = _extract_regular_price(
        product
    )

    if regular_price <= 0:
        regular_price = sale_price

    price = sale_price

    if price <= 0:
        price = regular_price

    promotion = _safe_string(
        product.get("promotion")
        or product.get("deal")
        or product.get("deal_type")
        or product.get("dealType")
        or product.get("promotion_text")
        or product.get("promotionText")
    )

    discount_amount = (
        regular_price - price
        if regular_price > price
        else Decimal("0")
    )

    if (
        regular_price > 0
        and discount_amount > 0
    ):

        discount_percentage = (
            discount_amount
            / regular_price
            * Decimal("100")
        )

    else:

        discount_percentage = Decimal("0")

    category = _safe_string(
        product.get("category")
        or product.get("category_name")
        or product.get("categoryName")
    )

    brand = _safe_string(
        product.get("brand")
        or product.get("brand_name")
        or product.get("brandName")
    )

    colour = _safe_string(
        product.get("colour")
        or product.get("color")
    )

    size = _safe_string(
        product.get("size")
        or product.get("pack_size")
        or product.get("packSize")
    )

    stock_value = (
        product.get("stock")
        if "stock" in product
        else product.get("availability")
    )

    stock = _safe_bool(
        stock_value,
        True
    )

    rating = _to_decimal(
        product.get("rating")
    )

    image = _extract_image(
        product
    )

    images = _extract_images(
        product
    )

    url = _safe_string(
        product.get("url")
        or product.get("product_url")
        or product.get("productUrl")
        or product.get("link")
    )

    # IMPORTANT:
    # Use the compatibility helper required
    # by products/views.py.
    store_id = _extract_store_id(
        product
    )

    store_name = _safe_string(
        product.get("store")
        or product.get("store_name")
        or product.get("storeName")
    )

    location = product.get(
        "location"
    )

    if not isinstance(location, dict):
        location = {}

    if resolve_store and store_id:

        try:

            location = get_store_location(
                store_id
            )

        except StoreAPIError:

            location = location or {}

    deal_expiry = _safe_string(
        product.get("deal_expiry")
        or product.get("dealExpiry")
        or product.get("valid_until")
        or product.get("validUntil")
        or product.get("expiry")
    )

    return {
        "id": _stable_product_id(
            retailer,
            product
        ),

        "external_id": raw_id,
        "raw_id": raw_id,
        "raw_product_id": raw_id,
        "raw_product_id_underscore": raw_id,

        "raw_sku": _safe_string(
            product.get("sku")
        ),

        "raw_code": _safe_string(
            product.get("code")
        ),

        "source": retailer,

        "name": name,
        "title": name,

        "description": description,

        "brand": brand,
        "category": category,

        "colour": colour,
        "size": size,

        "price": price,
        "regular_price": regular_price,
        "sale_price": sale_price,

        "on_sale": (
            price > 0
            and regular_price > price
        ),

        "promotion": promotion,

        "discount_amount": discount_amount,

        "discount_percentage": (
            discount_percentage
        ),

        "deal_expiry": deal_expiry,

        "shipping_cost": Decimal("0"),
        "total_cost": price,

        "stock": stock,

        "rating": rating,

        "store": store_name,
        "store_id": store_id,

        "location": location,

        "image": image,
        "thumbnail": image,
        "images": images,

        "url": url,
    }


# ============================================================
# PRODUCT CACHE
# ============================================================

def _cache_product(product):

    if not isinstance(product, dict):
        return

    retailer = _retailer_key(
        product.get("source")
    )

    product_id = product.get(
        "id"
    )

    if not product_id:
        return

    key = (
        f"{retailer}:product:"
        f"{product_id}"
    )

    _cache_set(
        key,
        product,
        CACHE_TIMEOUT
    )


def get_product(
    product_id,
    retailer="Checkers",
):

    key = (
        f"{_retailer_key(retailer)}:"
        f"product:"
        f"{product_id}"
    )

    return _cache_get(key)


# ============================================================
# CHECKERS STORE
# ============================================================

def get_store_location(
    store_id,
):

    cache_key = (
        f"checkers:store:"
        f"{store_id}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        CHECKERS_STORE_URL,
        CHECKERS_SNAPSHOT_VERSION,
        params={
            "storeId": store_id
        },
        method="POST",
    )

    store = {}

    if isinstance(data, dict):

        data_section = data.get(
            "data"
        )

        if isinstance(
            data_section,
            dict
        ):

            store = (
                data_section.get(
                    "store"
                )
                or data_section.get(
                    "location"
                )
            )

        if not store:

            store = (
                data.get("store")
                or data.get("location")
            )

        if not store:

            store = data_section

    location = _build_location(
        store or {}
    )

    if location:

        _cache_set(
            cache_key,
            location,
            CACHE_TIMEOUT
        )

    return location


# ============================================================
# CHECKERS SEARCH
# ============================================================

def search_products(
    keyword,
    limit=100,
):

    keyword = _safe_string(
        keyword
    )

    cache_key = (
        f"checkers:search:"
        f"{keyword.lower()}:"
        f"{limit}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        CHECKERS_SEARCH_URL,
        CHECKERS_SNAPSHOT_VERSION,
        params={
            "query": keyword,
            "page": "0",
            "limit": str(limit),
        },
        method="POST",
    )

    raw_products = _extract_raw_products(
        data
    )

    products = []

    for raw_product in raw_products:

        normalized = normalize_product(
            raw_product,
            resolve_store=True,
            retailer="Checkers",
        )

        _cache_product(
            normalized
        )

        products.append(
            normalized
        )

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT
        if products
        else EMPTY_CACHE_TIMEOUT
    )

    return products


# ============================================================
# GENERIC RETAILER SEARCH
# ============================================================

def _search_parse_retailer(
    retailer,
    endpoint,
    snapshot_version,
    keyword="",
    limit=20,
    extra_params=None,
):

    retailer_key = _retailer_key(
        retailer
    )

    cache_key = (
        f"{retailer_key}:search:"
        f"{keyword.lower()}:"
        f"{limit}:"
        f"{json.dumps(extra_params or {}, sort_keys=True)}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    params = {
        "query": keyword,
        "page": "0",
        "page_size": str(limit),
    }

    if extra_params:
        params.update(
            extra_params
        )

    data = _parse_request(
        endpoint,
        snapshot_version,
        params=params,
        method="GET",
    )

    raw_products = _extract_raw_products(
        data
    )

    products = []

    for raw_product in raw_products:

        normalized = normalize_product(
            raw_product,
            resolve_store=False,
            retailer=retailer,
        )

        _cache_product(
            normalized
        )

        products.append(
            normalized
        )

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT
        if products
        else EMPTY_CACHE_TIMEOUT
    )

    return products


# ============================================================
# PICK N PAY SEARCH
# ============================================================

def search_pnp_products(
    keyword,
    limit=20,
):

    return _search_parse_retailer(
        retailer="Pick n Pay",
        endpoint=PNP_SEARCH_URL,
        snapshot_version=PNP_SNAPSHOT_VERSION,
        keyword=keyword,
        limit=limit,
        extra_params={
            "sort": "relevance",
        },
    )


# ============================================================
# PICK N PAY SPECIALS
# ============================================================

def get_pnp_specials(
    page=0,
    page_size=20,
    category_id="pnpbase",
):

    cache_key = (
        f"pnp:specials:"
        f"{page}:"
        f"{page_size}:"
        f"{category_id}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        PNP_SPECIALS_URL,
        PNP_SNAPSHOT_VERSION,
        params={
            "page": str(page),
            "page_size": str(page_size),
            "category_id": category_id,
        },
        method="GET",
    )

    raw_products = _extract_raw_products(
        data
    )

    products = []

    for raw_product in raw_products:

        normalized = normalize_product(
            raw_product,
            resolve_store=False,
            retailer="Pick n Pay",
        )

        _cache_product(
            normalized
        )

        products.append(
            normalized
        )

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT
        if products
        else EMPTY_CACHE_TIMEOUT
    )

    return products


# ============================================================
# PICK N PAY STORES
# ============================================================

def get_pnp_stores(
    query="",
):

    query = _safe_string(
        query
    )

    cache_key = (
        f"pnp:stores:"
        f"{query.lower()}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        PNP_STORES_URL,
        PNP_SNAPSHOT_VERSION,
        params={
            "query": query
        },
        method="GET",
    )

    stores = extract_store_locations(
        data
    )

    _cache_set(
        cache_key,
        stores,
        CACHE_TIMEOUT
        if stores
        else EMPTY_CACHE_TIMEOUT
    )

    return stores


# ============================================================
# PICK N PAY STORE PRODUCTS
# ============================================================

def search_pnp_store_products(
    query,
    store_id,
    page_size=10,
):

    query = _safe_string(
        query
    )

    store_id = _safe_string(
        store_id
    )

    cache_key = (
        f"pnp:store_products:"
        f"{store_id}:"
        f"{query.lower()}:"
        f"{page_size}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        PNP_STORE_PRODUCTS_URL,
        PNP_SNAPSHOT_VERSION,
        params={
            "query": query,
            "store_id": store_id,
            "page_size": str(
                page_size
            ),
        },
        method="GET",
    )

    raw_products = _extract_raw_products(
        data
    )

    products = []

    for raw_product in raw_products:

        normalized = normalize_product(
            raw_product,
            resolve_store=False,
            retailer="Pick n Pay",
        )

        if not normalized.get(
            "store_id"
        ):
            normalized[
                "store_id"
            ] = store_id

        _cache_product(
            normalized
        )

        products.append(
            normalized
        )

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT
        if products
        else EMPTY_CACHE_TIMEOUT
    )

    return products


# ============================================================
# RETAILER 3 SEARCH
# ============================================================

def search_retailer3_products(
    keyword,
    limit=20,
):

    return _search_parse_retailer(
        retailer="Retailer 3",
        endpoint=RETAILER3_SEARCH_URL,
        snapshot_version=RETAILER3_SNAPSHOT_VERSION,
        keyword=keyword,
        limit=limit,
    )


# ============================================================
# RETAILER 3 SPECIALS
# ============================================================

def get_retailer3_specials(
    page=0,
):

    cache_key = (
        f"retailer3:specials:"
        f"{page}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        RETAILER3_SPECIALS_URL,
        RETAILER3_SNAPSHOT_VERSION,
        params={
            "page": str(page)
        },
        method="GET",
    )

    raw_products = _extract_raw_products(
        data
    )

    products = []

    for raw_product in raw_products:

        normalized = normalize_product(
            raw_product,
            resolve_store=False,
            retailer="Retailer 3",
        )

        _cache_product(
            normalized
        )

        products.append(
            normalized
        )

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT
        if products
        else EMPTY_CACHE_TIMEOUT
    )

    return products


# ============================================================
# RETAILER 3 STORE LOCATOR
# ============================================================

def get_retailer3_stores():

    cache_key = (
        "retailer3:store_locator"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        RETAILER3_STORE_LOCATOR_URL,
        RETAILER3_SNAPSHOT_VERSION,
        params={},
        method="GET",
    )

    stores = extract_store_locations(
        data
    )

    _cache_set(
        cache_key,
        stores,
        CACHE_TIMEOUT
        if stores
        else EMPTY_CACHE_TIMEOUT
    )

    return stores


# ============================================================
# RETAILER 3 PRICE COMPARISON
# ============================================================

def compare_retailer3_prices(
    query,
):

    query = _safe_string(
        query
    )

    cache_key = (
        f"retailer3:"
        f"price_comparison:"
        f"{query.lower()}"
    )

    cached = _cache_get(
        cache_key
    )

    if cached is not None:
        return cached

    data = _parse_request(
        RETAILER3_COMPARE_PRICES_URL,
        RETAILER3_SNAPSHOT_VERSION,
        params={
            "query": query
        },
        method="GET",
    )

    comparison = extract_price_comparisons(
        data
    )

    _cache_set(
        cache_key,
        comparison,
        CACHE_TIMEOUT
        if comparison
        else EMPTY_CACHE_TIMEOUT
    )

    return comparison


# ============================================================
# STORE EXTRACTION
# ============================================================

def extract_store_locations(
    payload,
):

    if not payload:
        return []

    data = _response_data(
        payload
    )

    if isinstance(data, dict):

        stores = data.get(
            "stores",
            []
        )

    elif isinstance(data, list):

        stores = data

    else:

        stores = []

    output = []

    for store in stores:

        if not isinstance(
            store,
            dict
        ):
            continue

        location = _build_location(
            store
        )

        location["retailer"] = (
            _safe_string(
                store.get(
                    "retailer"
                )
                or store.get(
                    "source"
                )
            )
        )

        output.append(
            location
        )

    return output


# ============================================================
# PRICE COMPARISON EXTRACTION
# ============================================================

def extract_price_comparisons(
    payload,
):

    if not payload:
        return []

    data = _response_data(
        payload
    )

    if isinstance(data, dict):

        comparison = data.get(
            "comparison",
            []
        )

    elif isinstance(data, list):

        comparison = data

    else:

        comparison = []

    if isinstance(
        comparison,
        dict
    ):

        comparison = [
            comparison
        ]

    return comparison


# ============================================================
# SHOPRITE PRODUCT NORMALIZER
# ============================================================

def normalize_shoprite_product(
    product,
):

    if not isinstance(
        product,
        dict
    ):
        product = {}

    regular_price = _to_decimal(
        product.get("price")
    )

    special_price = _to_decimal(
        product.get("special_price")
    )

    if special_price <= 0:
        special_price = regular_price

    current_price = (
        special_price
        if special_price > 0
        else regular_price
    )

    discount_amount = (
        regular_price
        - special_price
        if regular_price > special_price
        else Decimal("0")
    )

    if (
        regular_price > 0
        and discount_amount > 0
    ):

        discount_percentage = (
            discount_amount
            / regular_price
            * Decimal("100")
        )

    else:

        discount_percentage = Decimal("0")

    return {
        "id": _stable_product_id(
            "Shoprite",
            product
        ),

        "external_id": _safe_string(
            product.get("code")
            or product.get("id")
        ),

        "raw_id": _safe_string(
            product.get("code")
            or product.get("id")
        ),

        "raw_product_id": _safe_string(
            product.get("code")
            or product.get("id")
        ),

        "source": "Shoprite",

        "name": _safe_string(
            product.get("name")
            or product.get("title"),
            "Unknown product"
        ),

        "title": _safe_string(
            product.get("name")
            or product.get("title"),
            "Unknown product"
        ),

        "description": _safe_string(
            product.get(
                "description"
            )
        ),

        "brand": _safe_string(
            product.get("brand")
        ),

        "category": _safe_string(
            product.get("category")
        ),

        "colour": _safe_string(
            product.get("colour")
            or product.get("color")
        ),

        "size": _safe_string(
            product.get("size")
        ),

        "price": current_price,

        "regular_price": regular_price,

        "sale_price": special_price,

        "on_sale": (
            regular_price > special_price
            and special_price > 0
        ),

        "promotion": _safe_string(
            product.get("deal_type")
            or product.get("promotion")
        ),

        "discount_amount": (
            discount_amount
        ),

        "discount_percentage": (
            discount_percentage
        ),

        "deal_expiry": _safe_string(
            product.get("valid_until")
        ),

        "shipping_cost": Decimal("0"),

        "total_cost": current_price,

        "stock": _safe_bool(
            product.get(
                "availability"
            ),
            True,
        ),

        "rating": _to_decimal(
            product.get("rating")
        ),

        "store": _safe_string(
            product.get("store")
            or product.get(
                "store_name"
            )
        ),

        "store_id": _extract_store_id(
            product
        ),

        "location": (
            product.get(
                "location"
            )
            if isinstance(
                product.get(
                    "location"
                ),
                dict,
            )
            else {}
        ),

        "image": _extract_image(
            product
        ),

        "thumbnail": _extract_image(
            product
        ),

        "images": _extract_images(
            product
        ),

        "url": _safe_string(
            product.get("url")
        ),
    }


# ============================================================
# SHOPRITE RESPONSE ADAPTER
# ============================================================

def extract_shoprite_products(
    payload,
):

    data = _response_data(
        payload
    )

    if isinstance(data, dict):

        products = data.get(
            "products",
            []
        )

    elif isinstance(data, list):

        products = data

    else:

        products = []

    return [
        normalize_shoprite_product(
            product
        )
        for product in products
        if isinstance(
            product,
            dict
        )
    ]


# ============================================================
# PICK N PAY RESPONSE ADAPTER
# ============================================================

def extract_pnp_products(
    payload,
):

    raw_products = _extract_raw_products(
        payload
    )

    return [
        normalize_product(
            product,
            resolve_store=False,
            retailer="Pick n Pay",
        )
        for product in raw_products
        if isinstance(
            product,
            dict
        )
    ]


# ============================================================
# SEARCH ALL RETAILERS
# ============================================================

def search_all_retailers(
    keyword,
    limit=20,
):

    keyword = _safe_string(
        keyword
    )

    results = []
    errors = []

    retailer_functions = (
        (
            "Checkers",
            lambda: search_products(
                keyword,
                limit,
            ),
        ),

        (
            "Pick n Pay",
            lambda: search_pnp_products(
                keyword,
                limit,
            ),
        ),

        (
            "Retailer 3",
            lambda: search_retailer3_products(
                keyword,
                limit,
            ),
        ),
    )

    for (
        retailer,
        search_function,
    ) in retailer_functions:

        try:

            retailer_results = (
                search_function()
            )

            if retailer_results:
                results.extend(
                    retailer_results
                )

        except StoreAPIError as exc:

            errors.append(
                f"{retailer}: {exc}"
            )

        except Exception as exc:

            errors.append(
                f"{retailer}: {exc}"
            )

    # ========================================================
    # NUMERIC PRICE SORT
    # ========================================================

    results.sort(
        key=lambda item: _to_decimal(
            item.get("price"),
            default="999999999.99",
        )
    )

    if not results and errors:

        raise StoreAPIError(
            "All retailer searches failed. "
            + " | ".join(errors)
        )

    return results


# ============================================================
# PRODUCT COMPARISON
# ============================================================

def compare_products(
    products,
):

    if not products:

        return {
            "products": [],
            "cheapest": None,
            "most_expensive": None,
            "saving": Decimal("0"),
        }

    sorted_products = sorted(
        products,
        key=lambda item: _to_decimal(
            item.get("price"),
            default="999999999.99",
        ),
    )

    cheapest = sorted_products[0]

    most_expensive = (
        sorted_products[-1]
    )

    cheapest_price = _to_decimal(
        cheapest.get("price")
    )

    expensive_price = _to_decimal(
        most_expensive.get("price")
    )

    saving = (
        expensive_price
        - cheapest_price
    )

    return {
        "products": sorted_products,
        "cheapest": cheapest,
        "most_expensive": most_expensive,
        "saving": saving,
    }


# ============================================================
# CHEAPEST
# ============================================================

def get_cheapest_product(
    products,
):

    if not products:
        return None

    return min(
        products,
        key=lambda item: _to_decimal(
            item.get("price"),
            default="999999999.99",
        ),
    )


# ============================================================
# MOST EXPENSIVE
# ============================================================

def get_most_expensive_product(
    products,
):

    if not products:
        return None

    return max(
        products,
        key=lambda item: _to_decimal(
            item.get("price")
        ),
    )


# ============================================================
# CLEAR CACHE
# ============================================================

def clear_store_cache():

    try:

        patterns = (
            "*:search:*",
            "*:product:*",
            "*:specials:*",
            "*:stores:*",
            "*:store_products:*",
            "*:store_locator",
            "*:price_comparison:*",
            "checkers:store:*",
        )

        keys = []

        for pattern in patterns:

            keys.extend(
                redis_client.keys(
                    pattern
                )
            )

        # Remove duplicates.
        keys = list(
            set(keys)
        )

        if keys:
            redis_client.delete(
                *keys
            )

        return True

    except Exception:

        return False