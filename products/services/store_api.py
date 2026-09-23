"""
Production-oriented retailer integration for the AI Shopping project.

Data sources:
- Checkers via Parse.bot
- Pick n Pay via Parse.bot
- OpenStreetMap Overpass for nearby store locations
- Django cache / Redis when configured

The public retailer APIs are external services. Never put API keys in source
control; configure PARSE_API_KEY in the deployment environment.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.core.cache import cache
from django.conf import settings


# ============================================================
# CONFIGURATION
# ============================================================

PARSE_API_KEY = (
    getattr(settings, "PARSE_API_KEY", None)
    or os.getenv("PARSE_API_KEY", "")
).strip()

CACHE_TIMEOUT = int(os.getenv("PRODUCT_CACHE_TIMEOUT", "21600"))
STALE_CACHE_TIMEOUT = int(os.getenv("PRODUCT_STALE_CACHE_TIMEOUT", "86400"))
RATE_LIMIT_COOLDOWN = int(os.getenv("RETAILER_RATE_LIMIT_COOLDOWN", "65"))
STORE_CACHE_TIMEOUT = int(os.getenv("STORE_CACHE_TIMEOUT", "86400"))
EMPTY_CACHE_TIMEOUT = 60
REQUEST_TIMEOUT = int(os.getenv("RETAILER_REQUEST_TIMEOUT", "15"))
OSM_RADIUS_KM = float(os.getenv("OSM_RADIUS_KM", "25"))

PARSE_BASE_URL = "https://api.parse.bot/scraper"

CHECKERS_SCRAPER_ID = "a7a3a4ba-dfb7-4476-9712-8753b2fb3140"
PNP_SCRAPER_ID = "b87810bc-903f-41b8-b38d-c5c911cab324"

CHECKERS_SNAPSHOT_VERSION = "9"
PNP_SNAPSHOT_VERSION = "9"

CHECKERS_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/search_products"
)
CHECKERS_STORE_URL = (
    f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/find_stores"
)

PNP_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/search_products"
)
PNP_STORES_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/get_stores"
)
PNP_STORE_PRODUCTS_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/search_store_products"
)
PNP_SPECIALS_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/get_specials"
)

OVERPASS_URL = os.getenv(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
)
OSM_USER_AGENT = os.getenv(
    "OSM_USER_AGENT",
    "AIShoppingProject/1.0 (DUT student project)",
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": OSM_USER_AGENT,
    }
)


class StoreAPIError(Exception):
    """Raised when a retailer integration fails."""


# ============================================================
# CACHE HELPERS
# ============================================================

def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: Any, timeout: int = CACHE_TIMEOUT):
    try:
        cache.set(key, value, timeout)
    except Exception:
        # A cache outage must not take down product search.
        pass


def _stale_key(key: str) -> str:
    return f"{key}:stale"


def _cache_stale_set(key: str, value: Any):
    _cache_set(_stale_key(key), value, STALE_CACHE_TIMEOUT)


def _cache_stale_get(key: str):
    return _cache_get(_stale_key(key))


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return value != 0

    text = str(value).strip().lower()
    if text in {
        "true", "1", "yes", "y", "available", "in stock",
        "instock", "in_stock", "active", "sellable",
    }:
        return True
    if text in {
        "false", "0", "no", "n", "unavailable", "out of stock",
        "outofstock", "out_of_stock", "inactive",
    }:
        return False
    return default


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)

    if isinstance(value, Decimal):
        return value

    if isinstance(value, bool):
        return Decimal("1") if value else Decimal("0")

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
            "formattedValue",
        ):
            if key in value:
                result = _to_decimal(value[key], default)
                if result != Decimal(default):
                    return result
        return Decimal(default)

    text = str(value).strip()
    if not text:
        return Decimal(default)

    text = re.sub(r"[^\d,.\-]", "", text)

    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(_to_decimal(value))
    except Exception:
        return default


def _retailer_key(retailer: str) -> str:
    return (
        _safe_string(retailer, "Checkers")
        .lower()
        .replace(" ", "_")
    )


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:80]


# ============================================================
# PRODUCT / STORE ID HELPERS
# ============================================================

def _extract_product_id(product: dict) -> str:
    for key in (
        "id", "product_id", "productId", "productID", "sku", "code",
        "product_code", "productCode", "external_id", "externalId",
        "articleNumber",
    ):
        value = product.get(key)
        if value not in (None, ""):
            return _safe_string(value)
    return ""


def _extract_store_id(product: dict) -> str:
    if not isinstance(product, dict):
        return ""

    for key in (
        "store_id", "storeId", "storeID", "store_code", "storeCode",
        "branch_id", "branchId", "branchID", "branch_code", "branchCode",
    ):
        value = product.get(key)
        if value not in (None, ""):
            return _safe_string(value)

    for nested_key in ("store", "branch", "location"):
        nested = product.get(nested_key)
        if isinstance(nested, dict):
            for key in (
                "id", "store_id", "storeId", "storeID", "store_code",
                "storeCode", "branch_id", "branchId", "branch_code",
                "branchCode", "code",
            ):
                value = nested.get(key)
                if value not in (None, ""):
                    return _safe_string(value)

    return ""


def _stable_product_id(retailer: str, product: dict) -> str:
    raw_id = _extract_product_id(product)
    if raw_id:
        return f"{_retailer_key(retailer)}_{raw_id}"

    seed = "|".join(
        [
            retailer,
            _safe_string(
                product.get("name")
                or product.get("title")
                or product.get("product_name")
            ),
            _safe_string(
                product.get("size")
                or product.get("pack_size")
            ),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    return f"{_retailer_key(retailer)}_{digest}"


# ============================================================
# PRICE / IMAGE / STOCK EXTRACTION
# ============================================================

def _extract_price_from_fields(product: dict) -> Decimal:
    # Checkers explicitly returns priceWithoutDecimal in ZAR cents.
    if product.get("priceWithoutDecimal") not in (None, ""):
        try:
            return (
                Decimal(str(product["priceWithoutDecimal"])) / Decimal("100")
            )
        except Exception:
            pass

    for key in (
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
        if key in product:
            price = _to_decimal(product.get(key))
            if price > 0:
                return price

    return Decimal("0")


def _extract_regular_price(product: dict) -> Decimal:
    price_obj = product.get("price")
    if isinstance(price_obj, dict):
        for key in ("oldPrice", "old_price", "regular_price", "regularPrice"):
            if key in price_obj:
                value = _to_decimal(price_obj[key])
                if value > 0:
                    return value

    for key in (
        "regular_price", "regularPrice", "original_price", "originalPrice",
        "old_price", "oldPrice", "was_price", "wasPrice", "list_price",
        "listPrice",
    ):
        if key in product:
            value = _to_decimal(product.get(key))
            if value > 0:
                return value

    return Decimal("0")


def _extract_image(product: dict) -> str:
    for key in (
        "image", "image_url", "imageUrl", "thumbnail",
        "thumbnail_url", "thumbnailUrl",
    ):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    images = product.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                return image.strip()
            if isinstance(image, dict):
                for key in ("url", "image", "src", "large", "medium", "small"):
                    value = image.get(key)
                    if value:
                        return _safe_string(value)
    return ""


def _extract_images(product: dict) -> list[str]:
    images = product.get("images")
    output: list[str] = []

    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                output.append(image.strip())
            elif isinstance(image, dict):
                for key in ("url", "image", "src", "large", "medium", "small"):
                    value = image.get(key)
                    if value:
                        output.append(_safe_string(value))
                        break

    image = _extract_image(product)
    if image and image not in output:
        output.insert(0, image)

    return list(dict.fromkeys(output))


def _extract_stock(product: dict) -> bool:
    for key in (
        "isStockAvailable", "inStock", "available", "is_available",
        "stock", "availability", "stockStatus", "stockLevelStatus",
    ):
        if key in product:
            value = product.get(key)
            if isinstance(value, (int, float)):
                return value > 0
            return _safe_bool(value, True)
    return True


def _extract_promotion(product: dict) -> str:
    values = [
        product.get("promotion"),
        product.get("promotion_text"),
        product.get("promotionText"),
        product.get("deal"),
        product.get("deal_type"),
        product.get("dealType"),
        product.get("badge"),
        product.get("badgeText"),
    ]

    badges = product.get("badges")
    if isinstance(badges, list):
        values.extend(
            _safe_string(x.get("text") if isinstance(x, dict) else x)
            for x in badges
        )

    for value in values:
        text = _safe_string(value)
        if text:
            return text

    return ""


# ============================================================
# LOCATION / DISTANCE
# ============================================================

def _build_location(store: dict | None) -> dict:
    if not isinstance(store, dict):
        return {}

    address = store.get("address") or store.get("storeAddress") or store.get("location") or ""
    if isinstance(address, dict):
        parts = [
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
        address_text = ", ".join(_safe_string(x) for x in parts if x)
    else:
        address_text = _safe_string(address)

    latitude = (
        store.get("latitude")
        or store.get("lat")
        or store.get("storeLatitude")
    )
    longitude = (
        store.get("longitude")
        or store.get("lng")
        or store.get("lon")
        or store.get("storeLongitude")
    )

    return {
        "store_id": _safe_string(
            store.get("storeId")
            or store.get("store_id")
            or store.get("id")
            or store.get("code")
        ),
        "name": _safe_string(
            store.get("storeName")
            or store.get("store_name")
            or store.get("name")
        ),
        "address": address_text,
        "city": _safe_string(store.get("city")),
        "province": _safe_string(store.get("province")),
        "postal_code": _safe_string(
            store.get("postal_code") or store.get("postcode")
        ),
        "latitude": _number(latitude) if latitude is not None else None,
        "longitude": _number(longitude) if longitude is not None else None,
    }


def _haversine_km(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    radius = 6371.0088

    lat1 = math.radians(latitude1)
    lat2 = math.radians(latitude2)
    delta_lat = math.radians(latitude2 - latitude1)
    delta_lon = math.radians(longitude2 - longitude1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(a))


def _add_distance(
    product: dict,
    latitude: float | None,
    longitude: float | None,
):
    location = product.get("location") or {}
    if not isinstance(location, dict):
        location = {}

    store_lat = location.get("latitude")
    store_lon = location.get("longitude")

    if (
        latitude is not None
        and longitude is not None
        and store_lat is not None
        and store_lon is not None
    ):
        try:
            product["distance_km"] = round(
                _haversine_km(
                    float(latitude),
                    float(longitude),
                    float(store_lat),
                    float(store_lon),
                ),
                2,
            )
        except Exception:
            product["distance_km"] = None
    else:
        product["distance_km"] = None

    # Keep old template compatibility.
    product["distance"] = product["distance_km"]


# ============================================================
# PARSE.BOT REQUEST
# ============================================================

def _parse_request(
    url: str,
    snapshot_version: str,
    params: dict | None = None,
    method: str = "GET",
):
    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured. Add it to your environment."
        )

    headers = {
        "X-API-Key": PARSE_API_KEY,
        "API-Snapshot-Version": str(snapshot_version),
        "Accept": "application/json",
    }

    if CHECKERS_SCRAPER_ID in url:
        cooldown_key = "retailer:cooldown:checkers"
        retailer_name = "Checkers"
    elif PNP_SCRAPER_ID in url:
        cooldown_key = "retailer:cooldown:pnp"
        retailer_name = "Pick n Pay"
    else:
        cooldown_key = ""
        retailer_name = "retailer"

    if cooldown_key and _cache_get(cooldown_key):
        raise StoreAPIError(
            f"{retailer_name} API is temporarily rate-limited. "
            f"Retry after the {RATE_LIMIT_COOLDOWN}-second cooldown."
        )

    try:
        if method.upper() == "POST":
            response = SESSION.post(
                url,
                headers=headers,
                json=params or {},
                timeout=REQUEST_TIMEOUT,
            )
        else:
            response = SESSION.get(
                url,
                headers=headers,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
    except requests.Timeout as exc:
        raise StoreAPIError("Retailer API request timed out.") from exc
    except requests.RequestException as exc:
        raise StoreAPIError(f"Retailer API connection failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise StoreAPIError(
            "Retailer API authentication/access failed. Check PARSE_API_KEY."
        )

    if response.status_code == 429:
        if CHECKERS_SCRAPER_ID in url:
            retailer_name = "Checkers"
            cooldown_key = "retailer:cooldown:checkers"
        elif PNP_SCRAPER_ID in url:
            retailer_name = "Pick n Pay"
            cooldown_key = "retailer:cooldown:pnp"
        else:
            retailer_name = "retailer"
            cooldown_key = "retailer:cooldown:unknown"

        _cache_set(cooldown_key, True, RATE_LIMIT_COOLDOWN)
        raise StoreAPIError(
            f"{retailer_name} API rate limit reached. "
            f"Using cached data when available; new live requests are paused "
            f"for {RATE_LIMIT_COOLDOWN} seconds."
        )

    if response.status_code >= 400:
        raise StoreAPIError(
            f"Retailer API returned HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise StoreAPIError("Retailer API returned invalid JSON.") from exc


def _response_data(payload: Any):
    if not isinstance(payload, dict):
        return payload
    return payload.get("data", payload)


def _extract_raw_products(payload: Any) -> list[dict]:
    if not payload:
        return []

    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("products", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    for key in ("data", "result", "response"):
        nested = payload.get(key)
        if nested is not payload:
            found = _extract_raw_products(nested)
            if found:
                return found

    return []


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_product(
    product: dict,
    resolve_store: bool = False,
    retailer: str = "Checkers",
) -> dict:
    if not isinstance(product, dict):
        product = {}

    retailer = _safe_string(retailer, "Checkers")
    raw_id = _extract_product_id(product)

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

    price = _extract_price_from_fields(product)
    regular_price = _extract_regular_price(product)

    if regular_price <= 0:
        regular_price = price

    # PnP sometimes nests the sale price under price.value.
    if price <= 0 and isinstance(product.get("price"), dict):
        price = _to_decimal(product["price"].get("value"))

    if price <= 0:
        price = regular_price

    promotion = _extract_promotion(product)

    explicit_on_sale = (
        _safe_bool(
            product.get("onPromotion")
            or product.get("isOnPromotion")
            or product.get("on_sale"),
            False,
        )
    )

    old_price = regular_price
    if isinstance(product.get("price"), dict):
        old_price = _to_decimal(
            product["price"].get("oldPrice"),
            str(regular_price),
        ) or regular_price

    if old_price > price:
        regular_price = old_price

    on_sale = (
        explicit_on_sale
        or (
            regular_price > price > 0
        )
    )

    discount_amount = (
        regular_price - price
        if regular_price > price
        else Decimal("0")
    )

    discount_percentage = (
        discount_amount / regular_price * Decimal("100")
        if regular_price > 0 and discount_amount > 0
        else Decimal("0")
    )

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
        product.get("colour") or product.get("color")
    )
    size = _safe_string(
        product.get("size")
        or product.get("pack_size")
        or product.get("packSize")
    )

    stock = _extract_stock(product)
    rating = _to_decimal(product.get("rating"))

    store_id = _extract_store_id(product)
    store_name = _safe_string(
        product.get("store")
        or product.get("store_name")
        or product.get("storeName")
    )

    location = product.get("location")
    if not isinstance(location, dict):
        location = {}

    if not location:
        nested_store = product.get("store")
        if isinstance(nested_store, dict):
            location = _build_location(nested_store)

    if resolve_store and store_id and retailer.lower() == "checkers":
        try:
            location = get_store_location(store_id)
        except StoreAPIError:
            pass

    image = _extract_image(product)
    images = _extract_images(product)

    url = _safe_string(
        product.get("url")
        or product.get("product_url")
        or product.get("productUrl")
        or product.get("link")
    )

    deal_expiry = _safe_string(
        product.get("deal_expiry")
        or product.get("dealExpiry")
        or product.get("valid_until")
        or product.get("validUntil")
        or product.get("expiry")
    )

    return {
        "id": _stable_product_id(retailer, product),
        "external_id": raw_id,
        "raw_id": raw_id,
        "raw_product_id": raw_id,
        "raw_product_id_underscore": raw_id,
        "raw_sku": _safe_string(product.get("sku")),
        "raw_code": _safe_string(product.get("code")),
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
        "sale_price": price if on_sale else None,
        "on_sale": on_sale,
        "promotion": promotion,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "deal_expiry": deal_expiry,

        "shipping_cost": Decimal("0"),
        "total_cost": price,

        "stock": stock,
        "in_stock": stock,
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

def _cache_product(product: dict):
    if not isinstance(product, dict):
        return

    product_id = product.get("id")
    if not product_id:
        return

    retailer = _retailer_key(product.get("source"))
    _cache_set(
        f"product:{retailer}:{product_id}",
        product,
        CACHE_TIMEOUT,
    )


def get_product(product_id: str, retailer: str = "Checkers"):
    key = f"product:{_retailer_key(retailer)}:{product_id}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # Product detail endpoints differ between retailers. The search result
    # cache is intentionally preferred because it avoids unnecessary paid
    # API calls. A missing cache result is reported cleanly to the view.
    return None


# ============================================================
# CHECKERS
# ============================================================

def get_store_location(store_id: str):
    store_id = _safe_string(store_id)
    if not store_id:
        return {}

    cache_key = f"checkers:store:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _parse_request(
        CHECKERS_STORE_URL,
        CHECKERS_SNAPSHOT_VERSION,
        params={"storeId": store_id},
        method="POST",
    )

    section = _response_data(data)
    store = {}

    if isinstance(section, dict):
        store = (
            section.get("store")
            or section.get("location")
            or section
        )

    location = _build_location(store)
    if location:
        _cache_set(cache_key, location, STORE_CACHE_TIMEOUT)
    return location


def search_checkers_products(
    keyword: str,
    limit: int = 50,
    latitude: float | None = None,
    longitude: float | None = None,
):
    keyword = _safe_string(keyword)
    limit = max(1, min(int(limit), 100))

    cache_key = (
        f"checkers:search:{keyword.lower()}:{limit}"
    )
    cached = _cache_get(cache_key)

    if cached is not None:
        products = cached
    else:
        try:
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
        except StoreAPIError:
            stale = _cache_stale_get(cache_key)
            if stale is not None:
                products = stale
            else:
                raise
        else:
            products = [
            normalize_product(
                raw,
                resolve_store=False,
                retailer="Checkers",
            )
            for raw in _extract_raw_products(data)
            ]

            for product in products:
                _cache_product(product)

            _cache_set(
                cache_key,
                products,
                CACHE_TIMEOUT if products else EMPTY_CACHE_TIMEOUT,
            )
            if products:
                _cache_stale_set(cache_key, products)

    for product in products:
        _add_distance(product, latitude, longitude)

    return products


# Backwards-compatible public function used by products/views.py.
# It now searches both main retailers and uses OSM/retailer branch data when
# coordinates are supplied.
def search_products(
    keyword: str,
    limit: int = 100,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
):
    return search_all_retailers(
        keyword=keyword,
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


# ============================================================
# PICK N PAY
# ============================================================

def search_pnp_products(
    keyword: str,
    limit: int = 50,
):
    keyword = _safe_string(keyword)
    limit = max(1, min(int(limit), 100))

    cache_key = f"pnp:search:{keyword.lower()}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _parse_request(
            PNP_SEARCH_URL,
            PNP_SNAPSHOT_VERSION,
            params={
                "query": keyword,
                "page": "0",
                "page_size": str(limit),
                "sort": "relevance",
            },
            method="GET",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    products = [
        normalize_product(
            raw,
            resolve_store=False,
            retailer="Pick n Pay",
        )
        for raw in _extract_raw_products(data)
    ]

    for product in products:
        _cache_product(product)

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT if products else EMPTY_CACHE_TIMEOUT,
    )
    if products:
        _cache_stale_set(cache_key, products)
    return products


def get_pnp_stores(query: str = ""):
    query = _safe_string(query)
    cache_key = f"pnp:stores:{query.lower()}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _parse_request(
            PNP_STORES_URL,
            PNP_SNAPSHOT_VERSION,
            params={"query": query} if query else {},
            method="GET",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    section = _response_data(data)
    if isinstance(section, dict):
        raw_stores = (
            section.get("stores")
            or section.get("results")
            or section.get("items")
            or []
        )
    elif isinstance(section, list):
        raw_stores = section
    else:
        raw_stores = []

    stores = []
    for raw in raw_stores:
        if not isinstance(raw, dict):
            continue
        location = _build_location(raw)
        if location.get("store_id") or location.get("name"):
            location["retailer"] = "Pick n Pay"
            stores.append(location)

    _cache_set(
        cache_key,
        stores,
        STORE_CACHE_TIMEOUT if stores else EMPTY_CACHE_TIMEOUT,
    )
    if stores:
        _cache_stale_set(cache_key, stores)
    return stores


def search_pnp_store_products(
    query: str,
    store_id: str,
    page_size: int = 20,
):
    query = _safe_string(query)
    store_id = _safe_string(store_id)
    page_size = max(1, min(int(page_size), 72))

    if not store_id:
        return []

    cache_key = (
        f"pnp:store_products:{store_id}:"
        f"{query.lower()}:{page_size}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _parse_request(
            PNP_STORE_PRODUCTS_URL,
            PNP_SNAPSHOT_VERSION,
            params={
                "query": query,
                "store_id": store_id,
                "page": "0",
                "page_size": str(page_size),
            },
            method="GET",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    products = []
    for raw in _extract_raw_products(data):
        normalized = normalize_product(
            raw,
            resolve_store=False,
            retailer="Pick n Pay",
        )

        normalized["store_id"] = (
            normalized.get("store_id") or store_id
        )

        # The branch endpoint is the authoritative source for branch price,
        # promotion and stock.
        if not normalized.get("store"):
            normalized["store"] = "Pick n Pay"

        products.append(normalized)
        _cache_product(normalized)

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT if products else EMPTY_CACHE_TIMEOUT,
    )
    if products:
        _cache_stale_set(cache_key, products)
    return products


def get_pnp_specials(
    page: int = 0,
    page_size: int = 20,
    category_id: str = "pnpbase",
):
    cache_key = (
        f"pnp:specials:{page}:{page_size}:{category_id}"
    )
    cached = _cache_get(cache_key)
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

    products = [
        normalize_product(
            raw,
            retailer="Pick n Pay",
        )
        for raw in _extract_raw_products(data)
    ]

    for product in products:
        _cache_product(product)

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT if products else EMPTY_CACHE_TIMEOUT,
    )
    return products


# ============================================================
# OPENSTREETMAP / OVERPASS
# ============================================================

def _osm_query(latitude: float, longitude: float, radius_km: float):
    radius_m = int(max(500, min(radius_km * 1000, 50000)))

    # Query supermarkets and convenience/grocery shops around the user.
    return f"""
[out:json][timeout:12];
(
  nwr["shop"="supermarket"](around:{radius_m},{latitude},{longitude});
  nwr["shop"="convenience"](around:{radius_m},{latitude},{longitude});
);
out center tags;
"""


def find_nearby_stores(
    latitude: float,
    longitude: float,
    radius_km: float = OSM_RADIUS_KM,
    retailer: str = "",
):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        return []

    retailer_filter = _safe_string(retailer).lower()
    cache_key = (
        f"osm:stores:{round(latitude, 3)}:{round(longitude, 3)}:"
        f"{round(radius_km, 1)}:{retailer_filter}"
    )

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = SESSION.post(
            OVERPASS_URL,
            data=_osm_query(latitude, longitude, radius_km),
            headers={"User-Agent": OSM_USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            return []

        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    stores = []

    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        center = element.get("center") or {}

        lat = element.get("lat") or center.get("lat")
        lon = element.get("lon") or center.get("lon")

        if lat is None or lon is None:
            continue

        name = _safe_string(
            tags.get("name")
            or tags.get("brand")
            or tags.get("operator")
        )

        if not name:
            continue

        name_lower = name.lower()

        if retailer_filter:
            if retailer_filter == "checkers" and "checkers" not in name_lower:
                continue
            if retailer_filter in {"pick n pay", "pnp"} and not (
                "pick n pay" in name_lower or "pnp" in name_lower
            ):
                continue

        distance = _haversine_km(
            latitude,
            longitude,
            float(lat),
            float(lon),
        )

        if distance > radius_km:
            continue

        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:suburb"),
            tags.get("addr:city"),
        ]

        stores.append(
            {
                "store_id": _safe_string(element.get("id")),
                "name": name,
                "retailer": (
                    "Checkers"
                    if "checkers" in name_lower
                    else "Pick n Pay"
                    if "pick n pay" in name_lower or "pnp" in name_lower
                    else "Other"
                ),
                "address": ", ".join(
                    _safe_string(x) for x in address_parts if x
                ),
                "latitude": float(lat),
                "longitude": float(lon),
                "distance_km": round(distance, 2),
                "distance": round(distance, 2),
                "source": "OpenStreetMap",
            }
        )

    stores.sort(key=lambda x: x["distance_km"])

    _cache_set(
        cache_key,
        stores,
        STORE_CACHE_TIMEOUT if stores else EMPTY_CACHE_TIMEOUT,
    )
    return stores


def get_store_locations_near_user(
    latitude: float,
    longitude: float,
    radius_km: float = OSM_RADIUS_KM,
):
    return find_nearby_stores(latitude, longitude, radius_km)


# ============================================================
# MERGE / NEAREST BRANCH
# ============================================================

def _nearest_store(
    stores: list[dict],
    latitude: float | None,
    longitude: float | None,
):
    if latitude is None or longitude is None or not stores:
        return None

    candidates = []
    for store in stores:
        lat = store.get("latitude")
        lon = store.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            distance = _haversine_km(
                float(latitude),
                float(longitude),
                float(lat),
                float(lon),
            )
            copy = dict(store)
            copy["distance_km"] = round(distance, 2)
            copy["distance"] = round(distance, 2)
            candidates.append(copy)
        except Exception:
            continue

    return min(candidates, key=lambda x: x["distance_km"]) if candidates else None


def _attach_location(
    products: list[dict],
    stores: list[dict],
    latitude: float | None,
    longitude: float | None,
):
    nearest = _nearest_store(stores, latitude, longitude)

    for product in products:
        if not product.get("location") and nearest:
            product["location"] = nearest
            product["store_id"] = (
                product.get("store_id") or nearest.get("store_id")
            )
            if not product.get("store"):
                product["store"] = nearest.get("name", "")

        _add_distance(product, latitude, longitude)

    return products


# ============================================================
# ALL RETAILERS / PRICE COMPARISON
# ============================================================

def search_all_retailers(
    keyword: str,
    limit: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
):
    keyword = _safe_string(keyword)
    limit = max(1, min(int(limit), 100))

    if not keyword:
        return []

    if radius_km is None:
        radius_km = OSM_RADIUS_KM

    results: list[dict] = []
    errors: list[str] = []

    # --------------------------------------------------------
    # Checkers
    # --------------------------------------------------------
    try:
        checkers = search_checkers_products(
            keyword,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
        )

        if latitude is not None and longitude is not None:
            osm_checkers = find_nearby_stores(
                latitude,
                longitude,
                radius_km,
                retailer="Checkers",
            )
            _attach_location(
                checkers,
                osm_checkers,
                latitude,
                longitude,
            )

        results.extend(checkers)
    except StoreAPIError as exc:
        errors.append(f"Checkers: {exc}")

    # --------------------------------------------------------
    # Pick n Pay
    # --------------------------------------------------------
    try:
        pnp = []

        if latitude is not None and longitude is not None:
            # First get PnP's branch list. This is cached for 24 hours.
            pnp_stores = get_pnp_stores()

            # Restrict paid branch product requests to nearby branches.
            nearby_pnp = []
            for store in pnp_stores:
                lat = store.get("latitude")
                lon = store.get("longitude")
                if lat is None or lon is None:
                    continue

                try:
                    distance = _haversine_km(
                        float(latitude),
                        float(longitude),
                        float(lat),
                        float(lon),
                    )
                except Exception:
                    continue

                if distance <= radius_km:
                    copy = dict(store)
                    copy["distance_km"] = round(distance, 2)
                    copy["distance"] = round(distance, 2)
                    nearby_pnp.append(copy)

            nearby_pnp.sort(key=lambda x: x["distance_km"])

            # Avoid making a branch API call for every store.
            # One nearest branch keeps API usage within the free-tier limit.
            # The generic PnP catalogue is used as fallback if this branch fails.
            for store in nearby_pnp[:1]:
                store_id = store.get("store_id")
                if not store_id:
                    continue

                try:
                    branch_products = search_pnp_store_products(
                        keyword,
                        store_id,
                        page_size=min(limit, 20),
                    )
                    for product in branch_products:
                        product["location"] = store
                        product["store"] = (
                            product.get("store")
                            or store.get("name")
                            or "Pick n Pay"
                        )
                        product["store_id"] = store_id
                        _add_distance(product, latitude, longitude)
                    pnp.extend(branch_products)
                except StoreAPIError as exc:
                    errors.append(
                        f"Pick n Pay {store_id}: {exc}"
                    )

            # If the branch lookup fails, use the single generic catalogue call.
            # If PnP is rate-limited, search_pnp_products() will use stale cache
            # when available instead of repeatedly hammering the API.
            if not pnp:
                pnp = search_pnp_products(keyword, limit)
                osm_pnp = find_nearby_stores(
                    latitude,
                    longitude,
                    radius_km,
                    retailer="Pick n Pay",
                )
                _attach_location(
                    pnp,
                    osm_pnp,
                    latitude,
                    longitude,
                )
        else:
            pnp = search_pnp_products(keyword, limit)

        results.extend(pnp)
    except StoreAPIError as exc:
        errors.append(f"Pick n Pay: {exc}")

    # --------------------------------------------------------
    # Deduplicate
    # --------------------------------------------------------
    unique = {}
    for product in results:
        key = (
            product.get("id")
            or "|".join(
                [
                    _safe_string(product.get("source")),
                    _safe_string(product.get("name")).lower(),
                    _safe_string(product.get("size")).lower(),
                    str(product.get("price")),
                    _safe_string(product.get("store_id")),
                ]
            )
        )
        unique[key] = product

    results = list(unique.values())

    # --------------------------------------------------------
    # Radius filter
    # --------------------------------------------------------
    if latitude is not None and longitude is not None:
        results = [
            product
            for product in results
            if (
                product.get("distance_km") is None
                or product.get("distance_km") <= radius_km
            )
        ]

    results.sort(
        key=lambda item: _to_decimal(
            item.get("price"),
            "999999999.99",
        )
    )

    if not results and errors:
        raise StoreAPIError(
            "No retailer results were available. "
            + " | ".join(errors[:3])
        )

    return results


def _normalized_match_key(product: dict) -> str:
    name = _safe_string(
        product.get("name")
        or product.get("title")
    ).lower()

    name = re.sub(r"\b\d+(?:[.,]\d+)?\s*(kg|g|l|ml|pack|pk)\b", "", name)
    name = re.sub(r"[^a-z0-9]+", " ", name).strip()

    brand = _safe_string(product.get("brand")).lower()
    size = _safe_string(product.get("size")).lower()

    return f"{brand}|{name}|{size}"


def compare_products(products: list[dict]):
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
            "999999999.99",
        ),
    )

    cheapest = sorted_products[0]
    expensive = sorted_products[-1]

    return {
        "products": sorted_products,
        "cheapest": cheapest,
        "most_expensive": expensive,
        "saving": (
            _to_decimal(expensive.get("price"))
            - _to_decimal(cheapest.get("price"))
        ),
    }


def compare_equivalent_products(products: list[dict]):
    groups: dict[str, list[dict]] = {}

    for product in products or []:
        key = _normalized_match_key(product)
        groups.setdefault(key, []).append(product)

    output = []

    for key, group in groups.items():
        if len(group) < 2:
            continue

        ordered = sorted(
            group,
            key=lambda item: _to_decimal(
                item.get("price"),
                "999999999.99",
            ),
        )

        cheapest = ordered[0]
        highest = ordered[-1]

        output.append(
            {
                "match_key": key,
                "products": ordered,
                "cheapest": cheapest,
                "most_expensive": highest,
                "saving": (
                    _to_decimal(highest.get("price"))
                    - _to_decimal(cheapest.get("price"))
                ),
            }
        )

    return output


def get_cheapest_product(products):
    if not products:
        return None
    return min(
        products,
        key=lambda item: _to_decimal(
            item.get("price"),
            "999999999.99",
        ),
    )


def get_most_expensive_product(products):
    if not products:
        return None
    return max(
        products,
        key=lambda item: _to_decimal(item.get("price")),
    )


# ============================================================
# COMPATIBILITY ADAPTERS
# ============================================================

def extract_store_locations(payload):
    data = _response_data(payload)

    if isinstance(data, dict):
        stores = (
            data.get("stores")
            or data.get("results")
            or data.get("items")
            or []
        )
    elif isinstance(data, list):
        stores = data
    else:
        stores = []

    output = []
    for store in stores:
        if not isinstance(store, dict):
            continue
        location = _build_location(store)
        location["retailer"] = _safe_string(
            store.get("retailer") or store.get("source")
        )
        output.append(location)
    return output


def extract_pnp_products(payload):
    return [
        normalize_product(
            product,
            retailer="Pick n Pay",
        )
        for product in _extract_raw_products(payload)
    ]


def extract_price_comparisons(payload):
    data = _response_data(payload)
    if isinstance(data, dict):
        comparison = data.get("comparison", [])
    elif isinstance(data, list):
        comparison = data
    else:
        comparison = []

    if isinstance(comparison, dict):
        return [comparison]
    return comparison


# ============================================================
# OPTIONAL LEGACY FUNCTIONS
# ============================================================

def search_retailer3_products(keyword, limit=20):
    return []


def get_retailer3_specials(page=0):
    return []


def get_retailer3_stores():
    return []


def compare_retailer3_prices(query):
    return []


def normalize_shoprite_product(product):
    return normalize_product(product, retailer="Shoprite")


def extract_shoprite_products(payload):
    return [
        normalize_shoprite_product(product)
        for product in _extract_raw_products(payload)
    ]


# ============================================================
# CACHE MANAGEMENT
# ============================================================

def clear_store_cache():
    """
    Clear known product/store cache entries.

    django-redis supports delete_pattern. Other cache backends may not.
    """
    try:
        delete_pattern = getattr(cache, "delete_pattern", None)
        if callable(delete_pattern):
            for pattern in (
                "checkers:*",
                "pnp:*",
                "product:*",
                "osm:*",
                "retailer:cooldown:*",
            ):
                delete_pattern(pattern)
            return True

        return False
    except Exception:
        return False
