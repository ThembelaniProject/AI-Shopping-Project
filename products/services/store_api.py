"""
Retail product integration for the AI Shopping project.

Primary provider:
    LoyaltyHub SA Grocery Price API
    - South African supermarket prices
    - Checkers, Shoprite, Pick n Pay, Woolworths, Clicks, Makro
    - price, stock, barcode, image and freshness metadata
    - free beta tier: 100 calls/month, 20 requests/minute

Store locations:
    OpenStreetMap Overpass, cached for 24 hours.

Fallback provider:
    PriceCheck.co.za through Parse.bot, only when LoyaltyHub is not
    configured or unavailable.

The code is deliberately cache-first so one search does not repeatedly
consume an API call.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache


# ============================================================
# CONFIGURATION
# ============================================================

LOYALTYHUB_API_KEY = (
    getattr(settings, "LOYALTYHUB_API_KEY", None)
    or os.getenv("LOYALTYHUB_API_KEY", "")
).strip()

PARSE_API_KEY = (
    getattr(settings, "PARSE_API_KEY", None)
    or os.getenv("PARSE_API_KEY", "")
).strip()

# loyaltyhub is the recommended provider.
API_PROVIDER = os.getenv("RETAILER_API_PROVIDER", "loyaltyhub").strip().lower()

LOYALTYHUB_BASE_URL = "https://loyaltyhub.co.za/api/v1"
LOYALTYHUB_PRICES_URL = f"{LOYALTYHUB_BASE_URL}/prices"
LOYALTYHUB_PRODUCTS_URL = f"{LOYALTYHUB_BASE_URL}/products"

# PriceCheck fallback.
PRICECHECK_SCRAPER_ID = "6de3452a-00ab-44bc-b023-4f6c36b1e64e"
PARSE_BASE_URL = "https://api.parse.bot/scraper"
PRICECHECK_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{PRICECHECK_SCRAPER_ID}/search_products"
)
PRICECHECK_OFFERS_URL = (
    f"{PARSE_BASE_URL}/{PRICECHECK_SCRAPER_ID}/get_product_offers"
)

CACHE_TIMEOUT = int(os.getenv("PRODUCT_CACHE_TIMEOUT", "21600"))       # 6 hours
STALE_CACHE_TIMEOUT = int(
    os.getenv("PRODUCT_STALE_CACHE_TIMEOUT", "172800")
)  # 48 hours
STORE_CACHE_TIMEOUT = int(os.getenv("STORE_CACHE_TIMEOUT", "86400"))  # 24 hours
REQUEST_TIMEOUT = int(os.getenv("RETAILER_REQUEST_TIMEOUT", "15"))
OSM_RADIUS_KM = float(os.getenv("OSM_RADIUS_KM", "25"))

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

def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: Any, timeout: int = CACHE_TIMEOUT):
    try:
        cache.set(key, value, timeout)
    except Exception:
        # Product search must still work if Redis is temporarily unavailable.
        pass


def _stale_key(key: str) -> str:
    return f"{key}:stale"


def _cache_stale_get(key: str):
    return _cache_get(_stale_key(key))


def _cache_stale_set(key: str, value: Any):
    _cache_set(_stale_key(key), value, STALE_CACHE_TIMEOUT)


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)

    if isinstance(value, Decimal):
        return value

    if isinstance(value, bool):
        return Decimal("1") if value else Decimal("0")

    if isinstance(value, dict):
        for key in (
            "value",
            "amount",
            "price",
            "current_price",
            "sale_price",
            "regular_price",
            "old_price",
            "oldPrice",
        ):
            if key in value:
                result = _to_decimal(value[key], default)
                if result != Decimal(default):
                    return result
        return Decimal(default)

    text = str(value).strip()
    if not text:
        return Decimal(default)

    text = re.sub(r"[^0-9,.-]", "", text)

    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, (int, float)):
        return value != 0

    text = str(value).strip().lower()

    if text in {
        "true",
        "1",
        "yes",
        "y",
        "available",
        "in stock",
        "instock",
        "active",
    }:
        return True

    if text in {
        "false",
        "0",
        "no",
        "n",
        "unavailable",
        "out of stock",
        "outofstock",
        "inactive",
    }:
        return False

    return default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(_to_decimal(value))
    except Exception:
        return default


def _retailer_key(value: str) -> str:
    return (
        _safe_string(value, "Retailer")
        .lower()
        .replace("&", "and")
        .replace(" ", "_")
    )


def _stable_product_id(retailer: str, product: dict) -> str:
    raw = (
        product.get("barcode")
        or product.get("product_id")
        or product.get("productId")
        or product.get("sku")
        or product.get("id")
    )

    if raw:
        return f"{_retailer_key(retailer)}_{_safe_string(raw)}"

    seed = "|".join(
        [
            retailer,
            _safe_string(product.get("name")).lower(),
            _safe_string(product.get("size")).lower(),
            _safe_string(product.get("price")),
        ]
    )

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    return f"{_retailer_key(retailer)}_{digest}"


def _normalise_retailer(value: str) -> str:
    text = _safe_string(value).lower()

    if "pick n pay" in text or text == "pnp":
        return "Pick n Pay"
    if "checkers" in text:
        return "Checkers"
    if "shoprite" in text:
        return "Shoprite"
    if "woolworth" in text:
        return "Woolworths"
    if "clicks" in text:
        return "Clicks"
    if "makro" in text:
        return "Makro"

    return _safe_string(value, "Retailer")


# ============================================================
# PRODUCT NORMALISATION
# ============================================================

def normalize_product(
    raw: dict,
    retailer: str | None = None,
    location: dict | None = None,
) -> dict:
    """
    Convert LoyaltyHub/PriceCheck records into one stable shape used
    by the Django templates and AI recommendation code.
    """

    raw = raw if isinstance(raw, dict) else {}

    source_retailer = _normalise_retailer(
        retailer
        or raw.get("retailer")
        or raw.get("store")
        or raw.get("merchant")
        or "Retailer"
    )

    name = _safe_string(
        raw.get("name")
        or raw.get("title")
        or raw.get("product_name")
        or "Unnamed product"
    )

    description = _safe_string(
        raw.get("description")
        or raw.get("short_description")
    )

    price = _to_decimal(
        raw.get("price")
        or raw.get("current_price")
        or raw.get("sale_price")
        or 0
    )

    regular_price = _to_decimal(
        raw.get("regular_price")
        or raw.get("original_price")
        or raw.get("was_price")
        or raw.get("old_price")
        or 0
    )

    sale_price_raw = raw.get("sale_price")
    sale_price = (
        _to_decimal(sale_price_raw)
        if sale_price_raw not in (None, "")
        else Decimal("0")
    )

    # Some providers only expose price + regular/old price.
    if sale_price <= 0 and regular_price > price > 0:
        sale_price = price

    final_price = sale_price if sale_price > 0 else price

    if regular_price <= 0:
        regular_price = final_price

    discount_amount = max(
        Decimal("0"),
        regular_price - final_price,
    )

    discount_percentage = Decimal("0")
    if regular_price > 0 and discount_amount > 0:
        discount_percentage = (
            discount_amount / regular_price
        ) * Decimal("100")

    promotion = _safe_string(
        raw.get("promotion")
        or raw.get("promotion_text")
        or raw.get("deal")
        or raw.get("badge")
    )

    on_sale = bool(
        raw.get("on_sale")
        or raw.get("on_special")
        or raw.get("is_on_sale")
        or raw.get("isOnPromotion")
        or discount_amount > 0
        or promotion
    )

    image = _safe_string(
        raw.get("image_url")
        or raw.get("image")
        or raw.get("thumbnail")
        or raw.get("thumbnail_url")
    )

    images = raw.get("images")
    if not isinstance(images, list):
        images = []

    clean_images = []
    for item in images:
        if isinstance(item, str) and item.strip():
            clean_images.append(item.strip())
        elif isinstance(item, dict):
            value = (
                item.get("url")
                or item.get("src")
                or item.get("image")
            )
            if value:
                clean_images.append(_safe_string(value))

    if image and image not in clean_images:
        clean_images.insert(0, image)

    image = clean_images[0] if clean_images else image

    in_stock = _safe_bool(
        raw.get("in_stock")
        if "in_stock" in raw
        else raw.get("inStock"),
        True,
    )

    stock_value = raw.get("stock")
    if isinstance(stock_value, (int, float)):
        stock = int(stock_value)
        in_stock = stock > 0
    else:
        stock = 1 if in_stock else 0

    store = _normalise_retailer(
        raw.get("store")
        or raw.get("retailer")
        or source_retailer
    )

    product_location = location or raw.get("location") or {}
    if not isinstance(product_location, dict):
        product_location = {}

    store_id = _safe_string(
        raw.get("store_id")
        or raw.get("storeId")
        or product_location.get("store_id")
        or product_location.get("id")
    )

    product_id = _stable_product_id(source_retailer, raw)

    # PriceCheck's product URL and LoyaltyHub barcode are both useful.
    url = _safe_string(
        raw.get("url")
        or raw.get("product_url")
        or raw.get("productUrl")
    )

    barcode = _safe_string(
        raw.get("barcode")
        or raw.get("ean")
        or raw.get("gtin")
    )

    updated_at = _safe_string(
        raw.get("updated_at")
        or raw.get("updatedAt")
    )

    return {
        "id": product_id,
        "product_id": product_id,
        "source": source_retailer,
        "retailer": source_retailer,
        "name": name,
        "title": name,
        "description": description,
        "brand": _safe_string(raw.get("brand")),
        "category": _safe_string(raw.get("category")),
        "colour": _safe_string(
            raw.get("colour") or raw.get("color")
        ),
        "size": _safe_string(
            raw.get("size") or raw.get("pack_size")
        ),
        "barcode": barcode,
        "price": final_price,
        "regular_price": regular_price,
        "sale_price": sale_price if sale_price > 0 else None,
        "on_sale": on_sale,
        "promotion": promotion,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "deal_expiry": _safe_string(
            raw.get("deal_expiry")
            or raw.get("dealExpiry")
        ),
        "shipping_cost": Decimal("0"),
        "total_cost": final_price,
        "stock": stock,
        "in_stock": in_stock,
        "rating": _to_decimal(raw.get("rating"), "0"),
        "store": store,
        "store_id": store_id,
        "location": product_location,
        "image": image,
        "thumbnail": image,
        "images": list(dict.fromkeys(clean_images)),
        "url": url,
        "updated_at": updated_at,
        "distance_km": None,
        "distance": None,
        "recommendation_score": Decimal("0"),
        "matched_preferences": [],
    }


# ============================================================
# LOCATION / DISTANCE
# ============================================================

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
            distance = round(
                _haversine_km(
                    float(latitude),
                    float(longitude),
                    float(store_lat),
                    float(store_lon),
                ),
                2,
            )
            product["distance_km"] = distance
            product["distance"] = distance
            return
        except Exception:
            pass

    product["distance_km"] = None
    product["distance"] = None


def _osm_query(
    latitude: float,
    longitude: float,
    radius_km: float,
):
    radius_m = int(
        max(
            500,
            min(radius_km * 1000, 50000),
        )
    )

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
        f"osm:stores:{round(latitude, 3)}:"
        f"{round(longitude, 3)}:{round(radius_km, 1)}:"
        f"{retailer_filter}"
    )

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = SESSION.post(
            OVERPASS_URL,
            data=_osm_query(
                latitude,
                longitude,
                radius_km,
            ),
            headers={
                "User-Agent": OSM_USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
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
                "pick n pay" in name_lower
                or "pnp" in name_lower
            ):
                continue

            if retailer_filter == "shoprite" and "shoprite" not in name_lower:
                continue

            if retailer_filter == "woolworths" and "woolworth" not in name_lower:
                continue

            if retailer_filter == "clicks" and "clicks" not in name_lower:
                continue

            if retailer_filter == "makro" and "makro" not in name_lower:
                continue

        try:
            distance = _haversine_km(
                latitude,
                longitude,
                float(lat),
                float(lon),
            )
        except Exception:
            continue

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
                "retailer": _normalise_retailer(name),
                "address": ", ".join(
                    _safe_string(x)
                    for x in address_parts
                    if x
                ),
                "city": _safe_string(tags.get("addr:city")),
                "province": _safe_string(
                    tags.get("addr:state")
                ),
                "latitude": float(lat),
                "longitude": float(lon),
                "distance_km": round(distance, 2),
                "distance": round(distance, 2),
                "source": "OpenStreetMap",
            }
        )

    stores.sort(
        key=lambda item: item["distance_km"]
    )

    _cache_set(
        cache_key,
        stores,
        STORE_CACHE_TIMEOUT if stores else 60,
    )

    return stores


def _nearest_store(
    stores: list[dict],
    latitude: float | None,
    longitude: float | None,
):
    if (
        latitude is None
        or longitude is None
        or not stores
    ):
        return None

    valid = []

    for store in stores:
        try:
            lat = float(store["latitude"])
            lon = float(store["longitude"])
            distance = _haversine_km(
                latitude,
                longitude,
                lat,
                lon,
            )
            item = dict(store)
            item["distance_km"] = round(distance, 2)
            item["distance"] = round(distance, 2)
            valid.append(item)
        except Exception:
            continue

    if not valid:
        return None

    return min(
        valid,
        key=lambda item: item["distance_km"],
    )


def _attach_location(
    products: list[dict],
    latitude: float | None,
    longitude: float | None,
    radius_km: float,
):
    # One cached OSM request per retailer/area, not one request per product.
    retailer_names = sorted(
        {
            _safe_string(
                product.get("retailer")
                or product.get("store")
            )
            for product in products
            if product.get("retailer") or product.get("store")
        }
    )

    stores_by_retailer = {}

    for retailer in retailer_names:
        if latitude is None or longitude is None:
            continue

        stores_by_retailer[retailer] = find_nearby_stores(
            latitude,
            longitude,
            radius_km,
            retailer=retailer,
        )

    for product in products:
        retailer = _normalise_retailer(
            product.get("retailer")
            or product.get("store")
            or ""
        )

        location = product.get("location") or {}

        if not location:
            nearby = stores_by_retailer.get(
                retailer,
                [],
            )
            nearest = _nearest_store(
                nearby,
                latitude,
                longitude,
            )

            if nearest:
                product["location"] = nearest
                product["store_id"] = (
                    product.get("store_id")
                    or nearest.get("store_id")
                )

        _add_distance(
            product,
            latitude,
            longitude,
        )

    return products


# ============================================================
# LOYALTYHUB API
# ============================================================

def _loyaltyhub_headers():
    if not LOYALTYHUB_API_KEY:
        raise StoreAPIError(
            "LOYALTYHUB_API_KEY is not configured."
        )

    return {
        "Authorization": f"Bearer {LOYALTYHUB_API_KEY}",
        "Accept": "application/json",
        "User-Agent": OSM_USER_AGENT,
    }


def _loyaltyhub_request(
    params: dict,
):
    try:
        response = SESSION.get(
            LOYALTYHUB_PRICES_URL,
            headers=_loyaltyhub_headers(),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise StoreAPIError(
            "LoyaltyHub API request timed out."
        ) from exc
    except requests.RequestException as exc:
        raise StoreAPIError(
            f"LoyaltyHub connection failed: {exc}"
        ) from exc

    if response.status_code == 401:
        raise StoreAPIError(
            "LoyaltyHub API key is invalid."
        )

    if response.status_code == 403:
        raise StoreAPIError(
            "LoyaltyHub API key is inactive or access is denied."
        )

    if response.status_code == 429:
        retry_after = response.headers.get(
            "Retry-After",
            "later",
        )
        raise StoreAPIError(
            "LoyaltyHub rate/quota limit reached. "
            f"Retry after {retry_after}."
        )

    if response.status_code >= 400:
        raise StoreAPIError(
            "LoyaltyHub returned HTTP "
            f"{response.status_code}: "
            f"{response.text[:250]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise StoreAPIError(
            "LoyaltyHub returned invalid JSON."
        ) from exc


def search_loyaltyhub_products(
    keyword: str,
    limit: int = 20,
    retailer: str = "",
):
    keyword = _safe_string(keyword)

    if not keyword:
        return []

    # The free tier caps pages at 10 rows.
    limit = max(
        1,
        min(int(limit), 10),
    )

    cache_key = (
        f"loyaltyhub:prices:"
        f"{keyword.lower()}:{limit}:"
        f"{_retailer_key(retailer) if retailer else 'all'}"
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    params = {
        "search": keyword,
        "limit": limit,
        "offset": 0,
    }

    if retailer:
        params["retailer"] = retailer

    try:
        payload = _loyaltyhub_request(params)
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    rows = payload.get("data", [])

    if not isinstance(rows, list):
        rows = []

    products = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        product = normalize_product(row)
        products.append(product)

        _cache_product(product)

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT if products else 60,
    )

    if products:
        _cache_stale_set(
            cache_key,
            products,
        )

    return products


# ============================================================
# PRICECHECK FALLBACK
# ============================================================

def _pricecheck_request(
    url: str,
    params: dict,
):
    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured for fallback."
        )

    try:
        response = SESSION.get(
            url,
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StoreAPIError(
            f"PriceCheck fallback connection failed: {exc}"
        ) from exc

    if response.status_code == 429:
        raise StoreAPIError(
            "PriceCheck fallback is rate-limited."
        )

    if response.status_code >= 400:
        raise StoreAPIError(
            f"PriceCheck fallback returned HTTP "
            f"{response.status_code}."
        )

    try:
        return response.json()
    except ValueError as exc:
        raise StoreAPIError(
            "PriceCheck fallback returned invalid JSON."
        ) from exc


def search_pricecheck_products(
    keyword: str,
    limit: int = 10,
):
    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(1, min(int(limit), 18))

    cache_key = (
        f"pricecheck:search:"
        f"{keyword.lower()}:{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    try:
        payload = _pricecheck_request(
            PRICECHECK_SEARCH_URL,
            {
                "query": keyword,
                "page": 1,
            },
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    data = payload.get("data", payload)
    rows = []

    if isinstance(data, dict):
        rows = (
            data.get("results")
            or data.get("products")
            or []
        )
    elif isinstance(data, list):
        rows = data

    products = []

    for row in rows[:limit]:
        if isinstance(row, dict):
            product = normalize_product(row)
            products.append(product)
            _cache_product(product)

    _cache_set(
        cache_key,
        products,
        CACHE_TIMEOUT if products else 60,
    )

    if products:
        _cache_stale_set(
            cache_key,
            products,
        )

    return products


# ============================================================
# PUBLIC SEARCH FUNCTION
# ============================================================

def search_products(
    keyword: str,
    limit: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
):
    """
    Main function used by products/views.py.

    API call behaviour:
        - 1 retailer API request on a cache miss.
        - 0 retailer requests on a cache hit.
        - nearby store locations use cached OSM data.
        - stale data is used when the live API is unavailable.
    """

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    radius = (
        float(radius_km)
        if radius_km is not None
        else OSM_RADIUS_KM
    )

    errors = []

    providers = []

    if API_PROVIDER == "pricecheck":
        providers = ["pricecheck"]
    elif API_PROVIDER == "loyaltyhub":
        providers = ["loyaltyhub", "pricecheck"]
    else:
        providers = ["loyaltyhub", "pricecheck"]

    products = []

    for provider in providers:
        try:
            if provider == "loyaltyhub":
                if not LOYALTYHUB_API_KEY:
                    continue

                products = search_loyaltyhub_products(
                    keyword,
                    limit=min(limit, 10),
                )

            elif provider == "pricecheck":
                if not PARSE_API_KEY:
                    continue

                products = search_pricecheck_products(
                    keyword,
                    limit=min(limit, 18),
                )

            if products:
                break

        except StoreAPIError as exc:
            errors.append(
                f"{provider.title()}: {exc}"
            )

    if not products:
        if errors:
            raise StoreAPIError(
                "No retailer results were available. "
                + " | ".join(errors[:2])
            )

        raise StoreAPIError(
            "No retailer API is configured. "
            "Add LOYALTYHUB_API_KEY to use the recommended "
            "free South African grocery API."
        )

    products = products[: max(1, int(limit))]

    if latitude is not None and longitude is not None:
        _attach_location(
            products,
            float(latitude),
            float(longitude),
            radius,
        )

    return products


def search_all_retailers(
    keyword: str,
    limit: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
):
    return search_products(
        keyword=keyword,
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


# ============================================================
# PRODUCT CACHE / DETAIL
# ============================================================

def _cache_product(product: dict):
    if not isinstance(product, dict):
        return

    product_id = (
        product.get("id")
        or product.get("product_id")
    )

    if not product_id:
        return

    key = f"product:{product_id}"

    _cache_set(
        key,
        product,
        CACHE_TIMEOUT,
    )

    _cache_stale_set(
        key,
        product,
    )


def get_product(product_id: str):
    product_id = _safe_string(product_id)

    if not product_id:
        return None

    cached = _cache_get(
        f"product:{product_id}"
    )

    if cached is not None:
        return cached

    stale = _cache_stale_get(
        f"product:{product_id}"
    )

    return stale


def _extract_store_id(product: dict) -> str:
    if not isinstance(product, dict):
        return ""

    return _safe_string(
        product.get("store_id")
        or product.get("storeId")
        or (product.get("location") or {}).get("store_id")
    )


def get_store_location(store_id: str):
    """
    Return a cached location when available.

    Product locations are populated by OSM during search.
    This avoids another retailer API call.
    """

    store_id = _safe_string(store_id)

    if not store_id:
        return None

    cached = _cache_get(
        f"store:location:{store_id}"
    )

    return cached


# ============================================================
# PRICE COMPARISON HELPERS
# ============================================================

def _normalized_match_key(product: dict) -> str:
    name = _safe_string(
        product.get("name")
        or product.get("title")
    ).lower()

    name = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*"
        r"(kg|g|l|ml|pack|pk)\b",
        "",
        name,
    )

    name = re.sub(
        r"[^a-z0-9]+",
        " ",
        name,
    ).strip()

    brand = _safe_string(
        product.get("brand")
    ).lower()

    size = _safe_string(
        product.get("size")
    ).lower()

    return f"{brand}|{name}|{size}"


def compare_products(products: list[dict]):
    if not products:
        return {
            "products": [],
            "cheapest": None,
            "most_expensive": None,
            "saving": Decimal("0"),
        }

    ordered = sorted(
        products,
        key=lambda item: _to_decimal(
            item.get("price"),
            "999999999.99",
        ),
    )

    cheapest = ordered[0]
    expensive = ordered[-1]

    return {
        "products": ordered,
        "cheapest": cheapest,
        "most_expensive": expensive,
        "saving": (
            _to_decimal(expensive.get("price"))
            - _to_decimal(cheapest.get("price"))
        ),
    }


def compare_equivalent_products(
    products: list[dict],
):
    groups = {}

    for product in products or []:
        key = _normalized_match_key(product)
        groups.setdefault(key, []).append(product)

    output = []

    for key, group in groups.items():
        if len(group) < 2:
            continue

        comparison = compare_products(group)
        comparison["match_key"] = key
        output.append(comparison)

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
        key=lambda item: _to_decimal(
            item.get("price"),
        ),
    )


# ============================================================
# COMPATIBILITY HELPERS
# ============================================================

def extract_store_locations(payload):
    if not isinstance(payload, dict):
        return []

    data = (
        payload.get("data")
        or payload.get("stores")
        or payload.get("results")
        or []
    )

    if not isinstance(data, list):
        return []

    return [
        item
        for item in data
        if isinstance(item, dict)
    ]


def extract_pnp_products(payload):
    if not isinstance(payload, dict):
        return []

    data = payload.get("data", payload)

    if isinstance(data, dict):
        data = (
            data.get("products")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        return []

    return [
        normalize_product(
            item,
            retailer="Pick n Pay",
        )
        for item in data
        if isinstance(item, dict)
    ]


def extract_price_comparisons(payload):
    if isinstance(payload, dict):
        data = payload.get("data", payload)

        if isinstance(data, dict):
            return (
                data.get("offers")
                or data.get("comparison")
                or []
            )

        if isinstance(data, list):
            return data

    if isinstance(payload, list):
        return payload

    return []


def get_store_locations_near_user(
    latitude: float,
    longitude: float,
    radius_km: float = OSM_RADIUS_KM,
):
    return find_nearby_stores(
        latitude,
        longitude,
        radius_km,
    )
