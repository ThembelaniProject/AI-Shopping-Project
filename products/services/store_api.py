"""
Multi-provider South African retail integration for AI Shopping.

Provider order:
1. PriceCheck via Parse - broad South African product/retailer discovery.
2. AZ Labs - live grocery search when configured.
3. Parse retailer APIs - live Checkers + Pick n Pay catalogue data.

All providers are normalized into one product shape so products/views.py
does not need to know which API supplied the result.

Important:
- Never put API keys in this file.
- Configure PARSE_API_KEY and AZLABS_API_KEY as environment variables.
- PriceCheck uses the same PARSE_API_KEY; no separate PriceCheck key is required.
- Product responses are cached to reduce API usage.
- Store distance is calculated with OpenStreetMap/Overpass and cached.
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
# BASIC VALUE HELPERS
# ============================================================

def _safe_string(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default
    return str(value).strip()



def _format_address(value: Any) -> str:
    """Convert retailer address objects into a readable address."""
    if isinstance(value, str):
        return value.strip()

    if not isinstance(value, dict):
        return ""

    parts = []
    for key in (
        "address", "streetAddress", "street", "houseNumber",
        "housenumber", "suburb", "town", "city", "province",
        "state", "postalCode", "postcode",
    ):
        item = value.get(key)
        if item not in (None, ""):
            item = _safe_string(item)
            if item and item not in parts:
                parts.append(item)

    return ", ".join(parts)


# ============================================================
# CONFIGURATION
# ============================================================

def _clean_secret(value: Any) -> str:
    """Normalize secrets copied into .env/Vercel without exposing them."""
    value = _safe_string(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        value = value[1:-1].strip()
    return value


PARSE_API_KEY = _clean_secret(
    getattr(settings, "PARSE_API_KEY", None)
    or os.getenv("PARSE_API_KEY", "")
    or os.getenv("PARSE_BOT_API_KEY", "")
)

AZLABS_API_KEY = _clean_secret(
    getattr(settings, "AZLABS_API_KEY", None)
    or os.getenv("AZLABS_API_KEY", "")
)

API_PROVIDER = _clean_secret(
    getattr(settings, "RETAILER_API_PROVIDER", None)
    or os.getenv("RETAILER_API_PROVIDER", "azlabs")
).lower()

AZLABS_BASE_URL = "https://azlabs.ai/api/v1"
AZLABS_SEARCH_URL = f"{AZLABS_BASE_URL}/grocery/search"
AZLABS_COMPARE_URL = f"{AZLABS_BASE_URL}/grocery/compare"

PARSE_BASE_URL = _clean_secret(
    getattr(settings, "PARSE_BASE_URL", None)
    or os.getenv("PARSE_BASE_URL", "https://api.parse.bot/scraper")
).rstrip("/")

PRICECHECK_SCRAPER_ID = _clean_secret(
    getattr(settings, "PRICECHECK_SCRAPER_ID", None)
    or os.getenv("PRICECHECK_SCRAPER_ID", "6de3452a-00ab-44bc-b023-4f6c36b1e64e")
)
PRICECHECK_SEARCH_URL = f"{PARSE_BASE_URL}/{PRICECHECK_SCRAPER_ID}/search_products"
PRICECHECK_OFFERS_URL = f"{PARSE_BASE_URL}/{PRICECHECK_SCRAPER_ID}/get_product_offers"
PRICECHECK_MAX_PRODUCTS = max(1, min(int(os.getenv("PRICECHECK_MAX_PRODUCTS", "2")), 2))
PRICECHECK_MAX_OFFERS = max(1, min(int(os.getenv("PRICECHECK_MAX_OFFERS", "50")), 50))

CHECKERS_SCRAPER_ID = "a7a3a4ba-dfb7-4476-9712-8753b2fb3140"
CHECKERS_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/search_products"
)
CHECKERS_STORES_URL = (
    f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/find_stores"
)

PNP_SCRAPER_ID = "b87810bc-903f-41b8-b38d-c5c911cab324"
PNP_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/search_products"
)
PNP_STORES_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/get_stores"
)
PNP_STORE_SEARCH_URL = (
    f"{PARSE_BASE_URL}/{PNP_SCRAPER_ID}/search_store_products"
)

# Branch-aware Pick n Pay pricing is enabled by default. It is only
# used when the caller supplies latitude + longitude.
PNP_BRANCH_LOOKUP_ENABLED = (
    os.getenv("PNP_BRANCH_LOOKUP_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

PNP_MAX_BRANCHES_TO_TRY = max(
    1,
    int(os.getenv("PNP_MAX_BRANCHES_TO_TRY", "5")),
)

# Retailer search results must not be held for hours when the UI is
# explicitly showing "live" prices. LIVE_PRICE_MODE bypasses the normal
# product cache and queries the retailer on every search. The stale cache
# remains available only as an outage/rate-limit fallback.
LIVE_PRICE_MODE = (
    os.getenv("RETAILER_LIVE_PRICE_MODE", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

CACHE_TIMEOUT = int(os.getenv("PRODUCT_CACHE_TIMEOUT", "900"))
STALE_CACHE_TIMEOUT = int(os.getenv("PRODUCT_STALE_CACHE_TIMEOUT", "604800"))
SEARCH_CACHE_VERSION = "v11"
COOLDOWN_CACHE_TIMEOUT = int(os.getenv("RETAILER_COOLDOWN_CACHE_TIMEOUT", "900"))

STORE_CACHE_TIMEOUT = int(
    os.getenv("STORE_CACHE_TIMEOUT", "86400")
)  # 24 hours

REQUEST_TIMEOUT = int(
    os.getenv("RETAILER_REQUEST_TIMEOUT", "15")
)

OSM_RADIUS_KM = float(
    os.getenv("OSM_RADIUS_KM", "25")
)

OVERPASS_URL = os.getenv(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
)

OSM_USER_AGENT = os.getenv(
    "OSM_USER_AGENT",
    "AIShoppingProject/2.0 (DUT student project)",
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": OSM_USER_AGENT,
    }
)


class StoreAPIError(Exception):
    """Raised when retailer integration fails."""


# ============================================================
# CACHE
# ============================================================

def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(
    key: str,
    value: Any,
    timeout: int = CACHE_TIMEOUT,
):
    try:
        cache.set(key, value, timeout)
    except Exception:
        pass


def _stale_key(key: str) -> str:
    return f"{key}:stale"


def _search_cache_key(
    keyword: str,
    limit: int,
    latitude: float | None,
    longitude: float | None,
    radius_km: float | None,
) -> str:
    """Build one deterministic Redis key for the complete search response."""
    raw = "|".join(
        [
            SEARCH_CACHE_VERSION,
            _safe_string(keyword).lower(),
            str(int(limit)),
            "" if latitude is None else f"{float(latitude):.5f}",
            "" if longitude is None else f"{float(longitude):.5f}",
            "" if radius_km is None else f"{float(radius_km):.2f}",
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"retailer:search:{digest}"


def _mark_cached_products(
    products: list[dict],
    freshness: str,
    is_live: bool,
) -> list[dict]:
    """Return copies with an honest cache freshness indicator."""
    output = []
    for product in products or []:
        if not isinstance(product, dict):
            continue
        item = dict(product)
        item["price_freshness"] = freshness
        item["price_is_live"] = is_live
        output.append(item)
    return output


def _cache_stale_get(key: str):
    return _cache_get(_stale_key(key))


def _cache_stale_set(key: str, value: Any):
    _cache_set(
        _stale_key(key),
        value,
        STALE_CACHE_TIMEOUT,
    )


# ============================================================
# BASIC HELPERS
# ============================================================

def _to_decimal(
    value: Any,
    default: str = "0",
) -> Decimal:
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
                return _to_decimal(
                    value[key],
                    default,
                )
        return Decimal(default)

    text = str(value).strip()

    if not text:
        return Decimal(default)

    text = re.sub(
        r"[^0-9,.-]",
        "",
        text,
    )

    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _safe_bool(
    value: Any,
    default: bool = False,
) -> bool:
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


def _retailer_key(value: str) -> str:
    return (
        _safe_string(value, "Retailer")
        .lower()
        .replace("&", "and")
        .replace(" ", "_")
    )


def _normalise_retailer(value: str) -> str:
    # Retailer fields can be nested store objects in live Checkers/PnP feeds.
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("storeName")
            or value.get("store_name")
            or value.get("brand")
            or value.get("retailer")
            or ""
        )
    text = _safe_string(value).lower()

    if "pick n pay" in text or "picknpay" in text or text == "pnp":
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

    return _safe_string(
        value,
        "Retailer",
    )


def _stable_product_id(
    retailer: str,
    product: dict,
) -> str:
    raw = (
        product.get("barcode")
        or product.get("product_id")
        or product.get("productId")
        or product.get("sku")
        or product.get("code")
        or product.get("id")
    )

    if raw:
        return (
            f"{_retailer_key(retailer)}_"
            f"{_safe_string(raw)}"
        )

    seed = "|".join(
        [
            retailer,
            _safe_string(
                product.get("name")
                or product.get("title")
            ).lower(),
            _safe_string(
                product.get("size")
            ).lower(),
            _safe_string(
                product.get("price")
            ),
        ]
    )

    digest = hashlib.sha256(
        seed.encode("utf-8")
    ).hexdigest()[:20]

    return (
        f"{_retailer_key(retailer)}_"
        f"{digest}"
    )


def _first_value(
    data: dict,
    *keys: str,
):
    for key in keys:
        if key in data and data[key] not in (
            None,
            "",
        ):
            return data[key]
    return None



def _fallback_product_image(
    name: str,
    brand: str = "",
    barcode: str = "",
) -> str:
    """
    Find a public product image when a retailer feed omits one.

    Retailer images always take priority. Open Food Facts is used only
    when the retailer response has no usable image URL.
    """
    name = _safe_string(name)
    brand = _safe_string(brand)
    barcode = _safe_string(barcode)

    if not name and not barcode:
        return ""

    cache_key = (
        "product:image:fallback:"
        + hashlib.sha256(
            f"{barcode}|{brand}|{name}".lower().encode("utf-8")
        ).hexdigest()
    )

    cached = _cache_get(cache_key)
    if cached:
        return cached

    queries = []
    if barcode:
        queries.append(barcode)

    text_query = " ".join(
        part for part in (brand, name) if part
    ).strip()

    if text_query:
        queries.append(text_query)

    for query in queries:
        try:
            response = SESSION.get(
                "https://world.openfoodfacts.org/cgi/search.pl",
                params={
                    "search_terms": query,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "page_size": 1,
                },
                headers={"Accept": "application/json"},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()

            products = payload.get("products", [])
            if not isinstance(products, list):
                continue

            for item in products:
                if not isinstance(item, dict):
                    continue

                image = (
                    item.get("image_front_url")
                    or item.get("image_url")
                    or item.get("image_small_url")
                )

                if isinstance(image, str) and image.startswith("http"):
                    _cache_set(cache_key, image, 86400)
                    return image

        except (requests.RequestException, ValueError):
            continue

    return ""

def _extract_rows(payload: Any) -> list[dict]:
    """
    Handle the slightly different response envelopes used by
    , Parse and LoyaltyHub.
    """
    if isinstance(payload, list):
        return [
            row for row in payload
            if isinstance(row, dict)
        ]

    if not isinstance(payload, dict):
        return []

    candidates = [
        payload.get("products"),
        payload.get("results"),
        payload.get("items"),
        payload.get("offers"),
        payload.get("matches"),
        payload.get("data"),
    ]

    for candidate in candidates:
        if isinstance(candidate, list):
            return [
                row for row in candidate
                if isinstance(row, dict)
            ]

        if isinstance(candidate, dict):
            nested = (
                candidate.get("products")
                or candidate.get("results")
                or candidate.get("items")
                or candidate.get("offers")
            )

            if isinstance(nested, list):
                return [
                    row for row in nested
                    if isinstance(row, dict)
                ]

    return []


# ============================================================
# PRODUCT NORMALISATION
# ============================================================

def normalize_product(
    raw: dict,
    retailer: str | None = None,
    location: dict | None = None,
) -> dict:
    """
    Convert , Checkers, PnP and LoyaltyHub records into
    one stable shape consumed by products/views.py.
    """

    raw = raw if isinstance(raw, dict) else {}

    # Retailer APIs can return branch metadata as a nested store object.
    # Keep that metadata structured instead of rendering the raw dict.
    raw_store = raw.get("store")
    if not isinstance(raw_store, dict):
        raw_store = raw.get("storeInfo") or raw.get("store_info") or {}
    if not isinstance(raw_store, dict):
        raw_store = {}

    store_label = _first_value(
        raw_store,
        "name", "storeName", "store_name", "displayName", "brand", "retailer",
    )

    source_retailer = _normalise_retailer(
        retailer
        or _first_value(
            raw,
            "retailer",
            "merchant",
            "storeName",
        )
        or store_label
        or "Retailer"
    )

    name = _safe_string(
        _first_value(
            raw,
            "name",
            "title",
            "product_name",
            "productName",
        )
        or "Unnamed product"
    )

    description = _safe_string(
        _first_value(
            raw,
            "description",
            "short_description",
            "shortDescription",
        )
    )

    barcode = _safe_string(
        _first_value(
            raw,
            "barcode",
            "ean",
            "gtin",
            "ean13",
        )
    )

    price = _to_decimal(
        _first_value(
            raw,
            "price",
            "current_price",
            "currentPrice",
            "sale_price",
            "salePrice",
            "best_price",
            "bestPrice",
        )
        or 0
    )

    regular_price = _to_decimal(
        _first_value(
            raw,
            "regular_price",
            "regularPrice",
            "original_price",
            "originalPrice",
            "old_price",
            "oldPrice",
            "was_price",
            "wasPrice",
        )
        or 0
    )

    sale_price_raw = _first_value(
        raw,
        "sale_price",
        "salePrice",
        "current_price",
        "currentPrice",
    )

    sale_price = (
        _to_decimal(sale_price_raw)
        if sale_price_raw is not None
        else Decimal("0")
    )

    # The retailer's current/sale price must win over the regular price.
    # Some live feeds return both fields even when the sale price is the
    # actual amount charged at checkout.
    final_price = price

    if sale_price > 0 and (
        final_price <= 0 or sale_price < final_price
    ):
        final_price = sale_price

    if final_price <= 0 and sale_price > 0:
        final_price = sale_price

    if regular_price <= 0:
        regular_price = final_price

    if (
        regular_price > 0
        and final_price > 0
        and regular_price > final_price
    ):
        discount_amount = (
            regular_price - final_price
        )
    else:
        discount_amount = Decimal("0")

    discount_percentage = Decimal("0")

    if regular_price > 0 and discount_amount > 0:
        discount_percentage = (
            discount_amount
            / regular_price
            * Decimal("100")
        )

    promotion = _safe_string(
        _first_value(
            raw,
            "promotion",
            "promotion_text",
            "promotionText",
            "promotion_description",
            "promotionDescription",
            "deal",
            "badge",
            "badges",
        )
    )

    on_sale = (
        _safe_bool(
            _first_value(
                raw,
                "on_sale",
                "onSale",
                "is_on_sale",
                "isOnSale",
                "isOnPromotion",
                "onPromotion",
            ),
            False,
        )
        or discount_amount > 0
        or bool(promotion)
    )

    # --------------------------------------------------------
    # PRODUCT IMAGES
    # --------------------------------------------------------
    # Retailer APIs do not always use one consistent image field.
    # Some return a URL, some return a list, and some return
    # objects such as {"url": "..."} or {"src": "..."}.
    # Normalize all of those formats into real browser URLs.
    def _image_url(value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("//"):
                return "https:" + value
            if value.startswith("http://"):
                return "https://" + value[7:]
            if value.startswith("https://"):
                return value
            return value

        if isinstance(value, dict):
            nested = _first_value(
                value,
                "url",
                "src",
                "image",
                "imageUrl",
                "image_url",
                "thumbnail",
                "thumbnailUrl",
                "imageId",
                "image_id",
            )
            return _image_url(nested)

        return ""

    image_candidates = [
        raw.get("image_url"),
        raw.get("imageUrl"),
        raw.get("image"),
        raw.get("thumbnail"),
        raw.get("thumbnail_url"),
        raw.get("thumbnailUrl"),
        raw.get("productImage"),
        raw.get("product_image"),
        raw.get("productImageUrl"),
        raw.get("product_image_url"),
        raw.get("primaryImage"),
        raw.get("primary_image"),
        raw.get("heroImage"),
        raw.get("hero_image"),
        raw.get("imageSrc"),
        raw.get("image_src"),
        raw.get("imageLink"),
        raw.get("image_link"),
        raw.get("photo"),
        raw.get("photoUrl"),
        raw.get("picture"),
        raw.get("media"),
        raw.get("images"),
        raw.get("imageUrls"),
        raw.get("image_urls"),
        raw.get("imageId"),
        raw.get("image_id"),
        raw.get("imageIds"),
        raw.get("image_ids"),
    ]

    clean_images = []

    def _collect_images(value):
        if isinstance(value, (list, tuple)):
            for item in value:
                _collect_images(item)
            return

        url = _image_url(value)

        if url and url not in clean_images:
            clean_images.append(url)

    for candidate in image_candidates:
        _collect_images(candidate)

    image = clean_images[0] if clean_images else ""

    # Keep retailer images when available. If a retailer omitted the
    # image, use a public product-image fallback.
    if not image:
        image = _fallback_product_image(
            name=name,
            brand=_safe_string(raw.get("brand")),
            barcode=barcode,
        )
        if image and image not in clean_images:
            clean_images.append(image)

    stock_raw = _first_value(
        raw,
        "stock",
        "stockLevel",
        "stock_level",
    )

    if isinstance(stock_raw, (int, float)):
        stock = int(stock_raw)
        in_stock = stock > 0
    else:
        in_stock = _safe_bool(
            _first_value(
                raw,
                "in_stock",
                "inStock",
                "available",
                "isStockAvailable",
            ),
            True,
        )
        stock = 1 if in_stock else 0

    store = _normalise_retailer(
        _first_value(
            raw,
            "store",
            "retailer",
            "merchant",
            "storeName",
        )
        or source_retailer
    )

    # Retailer feeds use several different names for colour.
    # Keep the value when it exists instead of always returning blank.
    colour = _safe_string(
        _first_value(
            raw,
            "colour",
            "color",
            "colourName",
            "colorName",
            "variant_colour",
            "variantColor",
        )
    )

    # Some feeds put colour inside a variant/attributes object.
    if not colour:
        attributes = raw.get("attributes") or raw.get("variant") or {}
        if isinstance(attributes, dict):
            colour = _safe_string(
                _first_value(
                    attributes,
                    "colour",
                    "color",
                    "colourName",
                    "colorName",
                )
            )

    # A product feed may include its branch directly.
    raw_location = raw.get("location")
    if not isinstance(raw_location, dict):
        raw_location = {}

    raw_lat = (
        raw.get("latitude")
        or raw.get("lat")
        or raw_location.get("latitude")
        or raw_location.get("lat")
        or raw_store.get("latitude")
        or raw_store.get("lat")
    )
    raw_lon = (
        raw.get("longitude")
        or raw.get("lon")
        or raw.get("lng")
        or raw_location.get("longitude")
        or raw_location.get("lon")
        or raw_location.get("lng")
        or raw_store.get("longitude")
        or raw_store.get("lon")
        or raw_store.get("lng")
    )

    product_location = (
        location
        or raw.get("location")
        or {}
    )

    if not isinstance(
        product_location,
        dict,
    ):
        product_location = {}

    # Preserve branch coordinates/address supplied directly by a retailer.
    if raw_lat is not None and raw_lon is not None:
        product_location = {
            **product_location,
            "latitude": raw_lat,
            "longitude": raw_lon,
        }

    raw_address = _safe_string(
        raw.get("address")
        or raw.get("storeAddress")
        or raw_store.get("address")
        or raw_store.get("storeAddress")
        or raw_store.get("streetAddress")
        or product_location.get("address")
    )
    if raw_address and not product_location.get("address"):
        product_location["address"] = raw_address

    raw_store_name = _safe_string(
        raw.get("storeName")
        or raw.get("store_name")
        or store_label
        or product_location.get("name")
        or source_retailer
    )
    if raw_store_name and not product_location.get("name"):
        product_location["name"] = raw_store_name

    store_id = _safe_string(
        _first_value(
            raw,
            "store_id",
            "storeId",
            "storeID",
        )
        or product_location.get(
            "store_id"
        )
        or product_location.get("storeId")
        or product_location.get("id")
        or raw_store.get("store_id")
        or raw_store.get("storeId")
        or raw_store.get("id")
    )

    # Some live feeds already calculate customer distance.
    distance_from_customer = _first_value(
        raw,
        "distanceFromCustomer", "distance_from_customer", "distance_km", "distance",
    )
    if distance_from_customer is None:
        distance_from_customer = _first_value(
            raw_store,
            "distanceFromCustomer", "distance_from_customer", "distance_km", "distance",
        )
    try:
        distance_from_customer = float(distance_from_customer) if distance_from_customer is not None else None
    except (TypeError, ValueError):
        distance_from_customer = None

    service_option_ids = _first_value(raw, "serviceOptionIds", "service_option_ids")
    if service_option_ids is None:
        service_option_ids = _first_value(raw_store, "serviceOptionIds", "service_option_ids")
    if not isinstance(service_option_ids, list):
        service_option_ids = []

    service_labels = {
        "sixty-min-delivery": "60-minute delivery",
        "one-day-delivery": "1-day delivery",
        "one-day-collection": "1-day collection",
    }
    shipping_options = [
        service_labels.get(_safe_string(option), _safe_string(option).replace("-", " ").title())
        for option in service_option_ids
        if _safe_string(option)
    ]

    product_id = _stable_product_id(
        source_retailer,
        raw,
    )

    url = _safe_string(
        _first_value(
            raw,
            "url",
            "product_url",
            "productUrl",
            "link",
        )
    )

    size = _safe_string(
        _first_value(
            raw,
            "size",
            "pack_size",
            "packSize",
            "weight",
            "volume",
            "netWeight",
            "net_weight",
        )
    )

    if size.lower() in {"0", "0.0", "0.00", "none", "null"}:
        size = ""

    if not size:
        size_match = re.search(
            r"(?<![A-Za-z0-9])([0-9]+(?:[.,][0-9]+)?\s*"
            r"(?:kg|g|l|ml|cl|mg|pack|pk|ea))\b",
            name,
            flags=re.IGNORECASE,
        )
        if size_match:
            size = re.sub(r"\s+", " ", size_match.group(1)).strip()

    updated_at = _safe_string(
        _first_value(
            raw,
            "updated_at",
            "updatedAt",
            "last_updated",
            "lastUpdated",
        )
    )

    return {
        "id": product_id,
        "product_id": product_id,
        "source": source_retailer,
        "retailer": source_retailer,
        "name": name,
        "title": name,
        "description": description,
        "brand": _safe_string(
            raw.get("brand")
        ),
        "category": _safe_string(
            raw.get("category")
        ),
        "colour": colour,
        "size": size,
        "barcode": barcode,
        "article_number": _safe_string(
            raw.get("articleNumber")
            or raw.get("article_number")
        ),
        "checkers_slug": _safe_string(
            raw.get("checkers_slug")
            or raw.get("slug")
        ),
        "price": final_price,
        "regular_price": regular_price,
        "sale_price": (
            final_price
            if on_sale and final_price > 0
            else None
        ),
        "on_sale": on_sale,
        "promotion": promotion,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "deal_expiry": _safe_string(
            raw.get("deal_expiry")
            or raw.get("dealExpiry")
        ),
        "shipping_cost": Decimal("0"),
        "shipping_options": shipping_options,
        "shipping_available": bool(shipping_options),
        "total_cost": final_price,
        "stock": stock,
        "in_stock": in_stock,
        "rating": _to_decimal(
            raw.get("rating"),
            "0",
        ),
        "store": store,
        "store_id": store_id,
        "location": product_location,
        "branch_price": final_price,
        "branch_store_id": store_id,
        "branch_specific": bool(store_id and product_location),
        "image": image,
        "thumbnail": image,
        "images": clean_images,
        "url": url,
        "updated_at": updated_at,
        # Set by each provider after its price format has been normalized.
        "price_source": source_retailer,
        "price_is_live": False,
        "price_freshness": "unknown",
        "recommendation_score": Decimal("0"),
        "matched_preferences": [],
        "distance_km": distance_from_customer,
        "distance": distance_from_customer,
    }


# ============================================================
# HTTP HELPERS
# ============================================================

def _request_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json: dict | None = None,
    provider: str,
) -> Any:
    provider_key = _retailer_key(provider)
    parse_backed = provider_key in {
        "pricecheck_search",
        "checkers",
        "pick_n_pay",
        "pick_n_pay_stores",
        "pnp",
    }

    # PriceCheck, Checkers and Pick n Pay all consume the same Parse.bot
    # API key/quota. A 429 from one must therefore pause the whole Parse
    # provider family instead of making three more requests that will also
    # return 429.
    cooldown_keys = (
        ["retailer:cooldown:parse"]
        if parse_backed
        else [f"retailer:cooldown:{provider_key}"]
    )

    for cooldown_key in cooldown_keys:
        if _cache_get(cooldown_key):
            raise StoreAPIError(
                f"{provider} is temporarily rate-limited. "
                "Using cached data when available."
            )

    try:
        response = SESSION.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise StoreAPIError(
            f"{provider} request timed out."
        ) from exc
    except requests.RequestException as exc:
        raise StoreAPIError(
            f"{provider} connection failed: {exc}"
        ) from exc

    if response.status_code == 401:
        # Keep the provider name in the error, but do not imply the
        # retailer itself is unavailable. A 401 is an integration-key
        # problem and the caller can safely try the next provider.
        raise StoreAPIError(
            f"{provider} authentication failed (HTTP 401). "
            "Check the API key configured in the deployment environment."
        )

    if response.status_code == 403:
        raise StoreAPIError(
            f"{provider} access is denied or inactive."
        )

    if response.status_code == 429:
        retry_after = response.headers.get(
            "Retry-After",
            "later",
        )
        try:
            cooldown = max(
                30,
                min(int(retry_after), 86400),
            )
        except (TypeError, ValueError):
            cooldown = COOLDOWN_CACHE_TIMEOUT

        cooldown_key = (
            "retailer:cooldown:parse"
            if parse_backed
            else f"retailer:cooldown:{provider_key}"
        )
        _cache_set(
            cooldown_key,
            True,
            cooldown,
        )

        raise StoreAPIError(
            f"{provider} is temporarily rate-limited. "
            f"Retry after {retry_after}."
        )

    if response.status_code >= 400:
        text = response.text[:300]
        raise StoreAPIError(
            f"{provider} returned HTTP "
            f"{response.status_code}: {text}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise StoreAPIError(
            f"{provider} returned invalid JSON."
        ) from exc


# ============================================================
# CHECKERS IMAGE RESOLUTION
# ============================================================

def _extract_checkers_image_ids(raw: dict) -> list[str]:
    """
    Extract Checkers image IDs or direct image URLs from all common
    response shapes returned by Parse.
    """
    if not isinstance(raw, dict):
        return []

    found: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return

        if isinstance(value, str):
            value = value.strip()
            if value and value not in found:
                found.append(value)
            return

        if isinstance(value, dict):
            for key in (
                "url", "imageUrl", "image_url",
                "cdnUrl", "cdn_url", "src", "href",
            ):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if item not in found:
                        found.append(item)
                    return

            for key in ("imageId", "image_id", "id"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if item not in found:
                        found.append(item)
                    return

            for key in (
                "image", "images", "media",
                "productImage", "product_image",
                "data", "result",
            ):
                if key in value:
                    add(value.get(key))
            return

        if isinstance(value, (list, tuple)):
            for item in value:
                add(item)

    for key in (
        "imageId", "image_id", "imageIds", "image_ids",
        "image", "images", "productImage", "product_image",
        "productImageUrl", "product_image_url", "media",
        "thumbnail", "thumbnailUrl", "thumbnail_url",
    ):
        if key in raw:
            add(raw.get(key))

    return found


def _image_to_https(value: str) -> str:
    value = _safe_string(value)

    if value.startswith("//"):
        return "https:" + value

    if value.startswith("http://"):
        return "https://" + value[7:]

    return value


def _resolve_checkers_image(image_id: str) -> str:
    """
    Resolve a Checkers image ID/reference to its real CDN URL.
    Direct URLs are returned immediately.
    """
    image_id = _safe_string(image_id)

    if not image_id:
        return ""

    if image_id.startswith(("http://", "https://", "//")):
        return _image_to_https(image_id)

    if not PARSE_API_KEY:
        return ""

    cache_key = (
        "checkers:image-url:"
        + hashlib.sha256(image_id.encode("utf-8")).hexdigest()
    )

    cached = _cache_get(cache_key)
    if cached:
        return _image_to_https(_safe_string(cached))

    try:
        payload = _request_json(
            "GET",
            f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/get_image_url",
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            params={"image_id": image_id},
            provider="Checkers image",
        )
    except StoreAPIError:
        return ""

    candidates: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith(("http://", "https://", "//")):
                candidates.append(value)
            return

        if isinstance(value, dict):
            for key in (
                "url", "imageUrl", "image_url",
                "cdnUrl", "cdn_url", "href", "src",
            ):
                item = value.get(key)
                if item is not None:
                    collect(item)
            collect(value.get("data"))
            collect(value.get("result"))
            return

        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(payload)

    if not candidates:
        return ""

    url = _image_to_https(candidates[0])
    _cache_set(cache_key, url, 86400)
    return url


def _get_checkers_detail_images(slug: str) -> list[str]:
    """Fetch and resolve Checkers imageIds from get_product_details."""
    slug = _safe_string(slug)
    if not slug or not PARSE_API_KEY:
        return []

    cache_key = (
        "checkers:detail-images:"
        + hashlib.sha256(slug.encode("utf-8")).hexdigest()
    )
    cached = _cache_get(cache_key)
    if cached:
        return list(cached)

    try:
        payload = _request_json(
            "GET",
            f"{PARSE_BASE_URL}/{CHECKERS_SCRAPER_ID}/get_product_details",
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            params={"slug": slug},
            provider="Checkers details",
        )
    except StoreAPIError:
        return []

    raw_images = []
    if isinstance(payload, dict):
        raw_images.extend([
            payload.get("imageIds"),
            payload.get("image_ids"),
            payload.get("images"),
            payload.get("imageId"),
            payload.get("image_id"),
            payload.get("image"),
            (payload.get("data") or {}).get("imageIds")
            if isinstance(payload.get("data"), dict) else None,
            (payload.get("data") or {}).get("imageIds")
            if isinstance(payload.get("data"), dict) else None,
        ])

    resolved = []
    for reference in raw_images:
        for image_reference in _extract_checkers_image_ids(
            {"images": reference}
        ):
            url = _resolve_checkers_image(image_reference)
            if url and url not in resolved:
                resolved.append(url)

    if resolved:
        _cache_set(cache_key, resolved, 86400)
    return resolved


# ============================================================
# AZ LABS LIVE GROCERY API
# ============================================================

def search_azlabs_products(
    keyword: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search AZ Labs' live grocery comparison endpoint.

    /grocery/compare returns size-normalized matches containing offers
    from Pick n Pay and Checkers. Each offer is exposed as an individual
    product so the existing SmartSpend result cards can show the exact
    retailer price and stock state.
    """
    if not AZLABS_API_KEY:
        raise StoreAPIError(
            "AZLABS_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)
    if not keyword:
        return []

    limit = max(1, min(int(limit), 20))
    cache_key = f"azlabs:compare:{keyword.lower()}:{limit}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return _mark_cached_products(
            cached,
            "cached",
            False,
        )

    try:
        payload = _request_json(
            "GET",
            AZLABS_COMPARE_URL,
            headers={
                "Authorization": f"Bearer {AZLABS_API_KEY}",
                "Accept": "application/json",
            },
            params={
                "q": keyword,
                "limit": limit,
            },
            provider="AZ Labs",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return _mark_cached_products(
                stale,
                "stale",
                False,
            )
        raise

    matches = payload.get("matches", []) if isinstance(payload, dict) else []
    if not isinstance(matches, list):
        matches = []

    products = []

    for match in matches[:limit]:
        if not isinstance(match, dict):
            continue

        match_name = _safe_string(
            match.get("name")
            or match.get("title")
            or keyword
        )
        match_size = _safe_string(
            match.get("size")
        )
        match_saving = _to_decimal(
            match.get("saving"),
            "0",
        )

        offers = match.get("offers", [])
        if not isinstance(offers, list):
            offers = []

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            store = _safe_string(
                offer.get("store")
                or offer.get("retailer")
                or offer.get("merchant")
            )
            offer_name = _safe_string(
                offer.get("name")
                or match_name
            )

            if not store or not offer_name:
                continue

            price = _to_decimal(
                offer.get("price"),
                "0",
            )
            if price <= 0:
                continue

            retailer = _normalise_retailer(store)

            raw_offer = dict(offer)
            raw_offer["name"] = offer_name
            raw_offer["price"] = price
            raw_offer["size"] = (
                _safe_string(offer.get("size"))
                or match_size
            )
            raw_offer["retailer"] = retailer
            raw_offer["store"] = store
            raw_offer["inStock"] = offer.get(
                "inStock",
                offer.get("in_stock"),
            )

            product = normalize_product(
                raw_offer,
                retailer=retailer,
            )

            # AZ Labs returns live comparison data. Do not convert the
            # match-level saving into a product discount: it is the
            # difference between retailer offers, not necessarily a sale.
            product["price_source"] = (
                "AZ Labs live grocery comparison API"
            )
            product["price_is_live"] = True
            product["price_freshness"] = "live"
            product["stock_available"] = _safe_bool(
                raw_offer.get("inStock"),
                False,
            )
            product["azlabs_match_name"] = match_name
            product["azlabs_match_size"] = match_size
            product["azlabs_cheapest_stores"] = (
                match.get("cheapestStores")
                if isinstance(match.get("cheapestStores"), list)
                else []
            )
            product["azlabs_comparison_saving"] = (
                match_saving
            )

            products.append(product)

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
# CHECKERS THROUGH PARSE
# ============================================================

def search_checkers_products(
    keyword: str,
    limit: int = 20,
) -> list[dict]:
    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(
        1,
        min(int(limit), 20),
    )

    cache_key = (
        f"checkers:search:v3:"
        f"{keyword.lower()}:{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return _mark_cached_products(cached, "live", True)

    try:
        payload = _request_json(
            "POST",
            CHECKERS_SEARCH_URL,
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "query": keyword,
                "page": 0,
                "limit": limit,
            },
            provider="Checkers",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return _mark_cached_products(stale, "stale", False)
        raise

    rows = _extract_rows(payload)

    products = []

    for row in rows[:limit]:
        row = dict(row)

        # Do not resolve every Checkers image during search.
        # Parse's free tier is rate-limited, so resolve the selected
        # product image on the detail page instead.
        article_number = _safe_string(
            row.get("articleNumber")
            or row.get("article_number")
        )
        row["articleNumber"] = article_number

        details_slug = _safe_string(
            row.get("slug")
            or row.get("productSlug")
            or row.get("product_slug")
            or row.get("urlSlug")
            or row.get("url_slug")
        )

        if not details_slug and article_number:
            row_name = _safe_string(
                row.get("name")
                or row.get("title")
            )
            if row_name:
                slug_name = re.sub(
                    r"[^a-z0-9]+",
                    "-",
                    row_name.lower(),
                ).strip("-")
                details_slug = f"{slug_name}-{article_number}EA"

        if details_slug:
            row["checkers_slug"] = details_slug

        # Parse's Checkers API documents priceWithoutDecimal as ZAR
        # cents. It is the authoritative numeric retailer price when
        # present, even if the response also contains a "price" field.
        # Always convert it before normalisation so cents can never be
        # rendered as Rand (for example 499 -> R4.99).
        if row.get("priceWithoutDecimal") not in (None, ""):
            try:
                row["price"] = (
                    Decimal(str(row["priceWithoutDecimal"]))
                    / Decimal("100")
                )
            except (InvalidOperation, ValueError, TypeError):
                pass

        # Checkers uses "priceWithoutDecimal" for the live price in
        # cents. The corresponding "oldPrice"/"oldPriceWithoutDecimal"
        # fields are also retailer values and must be converted using the
        # same cents -> Rand rule. Never let the raw cents value become a
        # bogus regular price such as R4,999.00.
        if row.get("priceWithoutDecimal") not in (None, ""):
            live_price = (
                Decimal(str(row["priceWithoutDecimal"]))
                / Decimal("100")
            )
            row["price"] = live_price

            regular_candidate = None

            if row.get("oldPriceWithoutDecimal") not in (None, ""):
                try:
                    regular_candidate = (
                        Decimal(str(row["oldPriceWithoutDecimal"]))
                        / Decimal("100")
                    )
                except (InvalidOperation, ValueError, TypeError):
                    regular_candidate = None

            elif row.get("oldPrice") not in (None, ""):
                try:
                    raw_old = Decimal(str(row["oldPrice"]))
                    # Parse's Checkers oldPrice is normally cents when the
                    # cents field is present/represented as an integer.
                    # If it already contains a decimal Rand amount, keep it.
                    if (
                        raw_old == raw_old.to_integral_value()
                        and raw_old >= Decimal("100")
                    ):
                        regular_candidate = raw_old / Decimal("100")
                    else:
                        regular_candidate = raw_old
                except (InvalidOperation, ValueError, TypeError):
                    regular_candidate = None

            if (
                regular_candidate is not None
                and regular_candidate > live_price
            ):
                row["regular_price"] = regular_candidate
            else:
                # No genuine "was" price means this is not a sale.
                row["regular_price"] = live_price
                row.pop("oldPrice", None)
                row.pop("oldPriceWithoutDecimal", None)

        product = normalize_product(
            row,
            retailer="Checkers",
        )

        # Checkers search responses can contain an image_id rather than a
        # browser-ready URL. Resolve it once and cache the CDN URL so the
        # template never receives the raw Parse image ID.
        checkers_image = _safe_string(product.get("image"))
        if not checkers_image.startswith(("http://", "https://", "//")):
            image_references = _extract_checkers_image_ids(row)
            for image_reference in image_references:
                resolved_image = _resolve_checkers_image(image_reference)
                if resolved_image:
                    product["image"] = resolved_image
                    product["thumbnail"] = resolved_image
                    product["images"] = [resolved_image]
                    break

        product["price_source"] = "Checkers live catalogue"
        product["price_is_live"] = True
        product["price_freshness"] = "live"
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
# CHECKERS LIVE STORE LOCATIONS
# ============================================================

def get_checkers_stores(
    latitude: float,
    longitude: float,
    radius_km: float = OSM_RADIUS_KM,
) -> list[dict]:
    """
    Resolve real Checkers branches from Parse using the user's
    coordinates. This is preferred over guessing a branch from OSM.
    """
    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured."
        )

    try:
        latitude = float(latitude)
        longitude = float(longitude)
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        return []

    cache_key = (
        f"checkers:stores:"
        f"{round(latitude, 3)}:"
        f"{round(longitude, 3)}:"
        f"{round(radius_km, 1)}"
    )

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    payload = _request_json(
        "POST",
        CHECKERS_STORES_URL,
        headers={
            "X-API-Key": PARSE_API_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "lat": latitude,
            "lng": longitude,
        },
        provider="Checkers stores",
    )

    if isinstance(payload, dict):
        stores = (
            payload.get("stores")
            or payload.get("data")
            or payload.get("results")
            or []
        )
    elif isinstance(payload, list):
        stores = payload
    else:
        stores = []

    if isinstance(stores, dict):
        stores = stores.get("stores") or stores.get("results") or []

    output = []

    for raw in stores:
        if not isinstance(raw, dict):
            continue

        location = raw.get("location")
        if not isinstance(location, dict):
            location = {}

        lat = (
            raw.get("latitude")
            or raw.get("lat")
            or location.get("latitude")
            or location.get("lat")
        )
        lon = (
            raw.get("longitude")
            or raw.get("lng")
            or raw.get("lon")
            or location.get("longitude")
            or location.get("lng")
            or location.get("lon")
        )

        if lat is None or lon is None:
            continue

        try:
            distance = _haversine_km(
                latitude,
                longitude,
                float(lat),
                float(lon),
            )
        except (TypeError, ValueError):
            continue

        if distance > radius_km:
            continue

        address = _format_address(
            raw.get("address")
            or raw.get("storeAddress")
            or raw.get("streetAddress")
            or location.get("address")
            or location.get("streetAddress")
        )

        store = {
            "store_id": _safe_string(
                raw.get("storeId")
                or raw.get("store_id")
                or raw.get("id")
            ),
            "name": _safe_string(
                raw.get("name")
                or raw.get("storeName")
                or raw.get("brand")
                or "Checkers"
            ),
            "retailer": "Checkers",
            "address": address,
            "city": _safe_string(
                raw.get("city")
                or location.get("city")
            ),
            "province": _safe_string(
                raw.get("province")
                or raw.get("state")
                or location.get("province")
                or location.get("state")
            ),
            "latitude": float(lat),
            "longitude": float(lon),
            "distance_km": round(distance, 2),
            "distance": round(distance, 2),
            "source": "Parse Checkers",
        }

        output.append(store)

        if store["store_id"]:
            _cache_set(
                f"store:location:v2:{store['store_id']}",
                store,
                STORE_CACHE_TIMEOUT,
            )

    output.sort(key=lambda item: item["distance_km"])
    _cache_set(
        cache_key,
        output,
        STORE_CACHE_TIMEOUT if output else 60,
    )
    return output


# ============================================================
# PICK N PAY BRANCH DISCOVERY / BRANCH PRICING
# ============================================================

def _pnp_store_distance(
    store: dict,
    latitude: float,
    longitude: float,
) -> float | None:
    lat = store.get("latitude") or store.get("lat")
    lon = (
        store.get("longitude")
        or store.get("lon")
        or store.get("lng")
    )

    if lat is None or lon is None:
        return None

    try:
        return _haversine_km(
            latitude,
            longitude,
            float(lat),
            float(lon),
        )
    except (TypeError, ValueError):
        return None


def get_pnp_stores(
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict]:
    """
    Get Pick n Pay branches from Parse.

    The result is cached for 24 hours because branch addresses and
    coordinates change much less frequently than prices.
    """

    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured."
        )

    cache_key = "pnp:stores:all:v2"

    stores = _cache_get(cache_key)

    if stores is None:
        try:
            payload = _request_json(
                "GET",
                PNP_STORES_URL,
                headers={
                    "X-API-Key": PARSE_API_KEY,
                    "Accept": "application/json",
                },
                provider="Pick n Pay stores",
            )
        except StoreAPIError:
            # Branch coordinates change infrequently. Reuse the last
            # successful branch catalogue during a Parse rate limit/outage.
            stale_stores = _cache_stale_get(cache_key)
            if stale_stores is not None:
                stores = stale_stores
            else:
                raise

        if isinstance(payload, dict):
            stores = payload.get("stores") or payload.get("data") or []
        elif isinstance(payload, list):
            stores = payload
        else:
            stores = []

        stores = [
            item
            for item in stores
            if isinstance(item, dict)
        ]

        _cache_set(
            cache_key,
            stores,
            STORE_CACHE_TIMEOUT,
        )
        _cache_stale_set(
            cache_key,
            stores,
        )

    if latitude is None or longitude is None:
        return stores

    nearby = []

    for store in stores:
        distance = _pnp_store_distance(
            store,
            float(latitude),
            float(longitude),
        )

        if distance is None:
            continue

        item = dict(store)
        item["distance_km"] = round(distance, 2)
        item["distance"] = round(distance, 2)
        item["store_id"] = _safe_string(
            store.get("storeId")
            or store.get("store_id")
            or store.get("id")
        )
        item["name"] = _safe_string(
            store.get("storeName")
            or store.get("name")
            or store.get("store_name")
        )
        item["retailer"] = "Pick n Pay"

        raw_address = (
            store.get("storeAddress")
            or store.get("store_address")
            or store.get("address")
            or store.get("location")
        )

        if isinstance(raw_address, dict):
            address_parts = [
                raw_address.get("address"),
                raw_address.get("streetAddress"),
                raw_address.get("street"),
                raw_address.get("suburb"),
                raw_address.get("city"),
                raw_address.get("province"),
                raw_address.get("postalCode"),
            ]
            address = ", ".join(
                _safe_string(part)
                for part in address_parts
                if _safe_string(part)
            )
        else:
            address = _safe_string(raw_address)

        location_data = store.get("location")
        if isinstance(location_data, dict):
            store_lat = (
                store.get("latitude")
                or store.get("lat")
                or location_data.get("latitude")
                or location_data.get("lat")
            )
            store_lon = (
                store.get("longitude")
                or store.get("lon")
                or store.get("lng")
                or location_data.get("longitude")
                or location_data.get("lon")
                or location_data.get("lng")
            )
        else:
            store_lat = store.get("latitude") or store.get("lat")
            store_lon = (
                store.get("longitude")
                or store.get("lon")
                or store.get("lng")
            )

        if store_lat is not None and store_lon is not None:
            item["latitude"] = store_lat
            item["longitude"] = store_lon

        item["address"] = address
        nearby.append(item)

    nearby.sort(
        key=lambda item: item["distance_km"]
    )

    return nearby


def search_pnp_store_products(
    keyword: str,
    store_id: str,
    limit: int = 20,
    store_location: dict | None = None,
) -> list[dict]:
    """
    Search Pick n Pay using a specific branch store_id.

    Unlike the generic PnP catalogue endpoint, this endpoint returns
    branch-specific price, oldPrice, savings, promotion and stock.
    """

    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)
    store_id = _safe_string(store_id)

    if not keyword or not store_id:
        return []

    limit = max(1, min(int(limit), 20))

    cache_key = (
        f"pnp:branch-search:"
        f"{store_id}:"
        f"{keyword.lower()}:"
        f"{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return _mark_cached_products(cached, "live", True)

    try:
        payload = _request_json(
            "GET",
            PNP_STORE_SEARCH_URL,
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            params={
                "store_id": store_id,
                "query": keyword,
                "page": 0,
                "page_size": limit,
            },
            provider="Pick n Pay branch",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return _mark_cached_products(stale, "stale", False)
        raise

    rows = _extract_rows(payload)

    # Some responses wrap products inside data.products.
    if not rows and isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            rows = _extract_rows(data)

    products = []

    for row in rows[:limit]:
        row = dict(row)

        # Preserve the branch context even if the upstream row
        # omits storeId.
        row["storeId"] = (
            row.get("storeId")
            or row.get("store_id")
            or store_id
        )

        if store_location:
            row["location"] = store_location

        product = normalize_product(
            row,
            retailer="Pick n Pay",
            location=store_location,
        )
        product["price_source"] = "Pick n Pay live branch catalogue"
        product["price_is_live"] = True
        product["price_freshness"] = "live"

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


def search_nearest_pnp_branch_products(
    keyword: str,
    latitude: float,
    longitude: float,
    radius_km: float = OSM_RADIUS_KM,
    limit: int = 20,
) -> list[dict]:
    """
    Find the nearest online-shopping PnP branch and retrieve prices
    scoped to that branch.

    The nearest 5 branches are queried by default so the search can show
    multiple nearby Pick n Pay stores. Set PNP_MAX_BRANCHES_TO_TRY to a
    different value when you want to control API usage.
    """

    if not PNP_BRANCH_LOOKUP_ENABLED:
        return []

    stores = get_pnp_stores(
        latitude=latitude,
        longitude=longitude,
    )

    nearby = [
        store
        for store in stores
        if store.get("distance_km") is not None
        and store["distance_km"] <= float(radius_km)
        and store.get("store_id")
    ]

    if not nearby:
        return []

    products = []

    for store in nearby[:PNP_MAX_BRANCHES_TO_TRY]:
        branch_products = search_pnp_store_products(
            keyword=keyword,
            store_id=store["store_id"],
            limit=limit,
            store_location=store,
        )

        products.extend(branch_products)

        # One branch is the default to keep API usage low.
        if branch_products and PNP_MAX_BRANCHES_TO_TRY == 1:
            break

    return products


# ============================================================
# PICK N PAY THROUGH PARSE
# ============================================================

def search_pnp_products(
    keyword: str,
    limit: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = OSM_RADIUS_KM,
) -> list[dict]:
    if not PARSE_API_KEY:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(
        1,
        min(int(limit), 20),
    )

    # If the student supplied a location, use the branch-specific
    # endpoint first. This gives the UI the actual PnP branch price
    # and stock rather than a generic online catalogue price.
    if (
        latitude is not None
        and longitude is not None
        and PNP_BRANCH_LOOKUP_ENABLED
    ):
        branch_products = search_nearest_pnp_branch_products(
            keyword=keyword,
            latitude=float(latitude),
            longitude=float(longitude),
            radius_km=float(radius_km),
            limit=limit,
        )

        if branch_products:
            return branch_products

    cache_key = (
        f"pnp:search:"
        f"{keyword.lower()}:{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return _mark_cached_products(cached, "live", True)

    try:
        payload = _request_json(
            "GET",
            PNP_SEARCH_URL,
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            params={
                "page": 0,
                "sort": "relevance",
                "query": keyword,
                "page_size": limit,
            },
            provider="Pick n Pay",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return _mark_cached_products(stale, "stale", False)
        raise

    rows = _extract_rows(payload)

    products = []

    for row in rows[:limit]:
        product = normalize_product(
            row,
            retailer="Pick n Pay",
        )
        product["price_source"] = "Pick n Pay live catalogue"
        product["price_is_live"] = True
        product["price_freshness"] = "live"
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
# PRICECHECK SOUTH AFRICA - BROAD RETAIL DISCOVERY
# ============================================================

def search_pricecheck_products(
    keyword: str,
    limit: int = 20,
) -> list[dict]:
    """Search PriceCheck and expand matched products into store offers."""
    if not PARSE_API_KEY:
        raise StoreAPIError("PARSE_API_KEY is not configured.")

    keyword = _safe_string(keyword)
    if not keyword:
        return []

    product_limit = min(max(1, int(limit)), PRICECHECK_MAX_PRODUCTS)
    cache_key = f"pricecheck:search:v3:{keyword.lower()}:{product_limit}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return _mark_cached_products(cached, "live", True)

    try:
        search_payload = _request_json(
            "GET",
            PRICECHECK_SEARCH_URL,
            headers={"X-API-Key": PARSE_API_KEY, "Accept": "application/json"},
            params={"query": keyword, "page": 1},
            provider="PriceCheck search",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return _mark_cached_products(stale, "stale", False)
        raise

    summaries = _extract_rows(search_payload)
    products = []
    errors = []

    for summary in summaries[:product_limit]:
        if not isinstance(summary, dict):
            continue

        pc_id = _safe_string(
            summary.get("product_id")
            or summary.get("productId")
            or summary.get("id")
        )
        if not pc_id:
            continue

        detail_key = f"pricecheck:offers:v3:{pc_id}"
        detail = _cache_get(detail_key)

        if detail is None:
            try:
                detail = _request_json(
                    "GET",
                    PRICECHECK_OFFERS_URL,
                    headers={"X-API-Key": PARSE_API_KEY, "Accept": "application/json"},
                    params={"product_id": pc_id},
                    provider="PriceCheck offers",
                )
                _cache_set(detail_key, detail, CACHE_TIMEOUT)
                _cache_stale_set(detail_key, detail)
            except StoreAPIError as exc:
                errors.append(str(exc))
                detail = _cache_stale_get(detail_key)
                if detail is None:
                    continue

        data = detail.get("data") if isinstance(detail, dict) else {}
        if not isinstance(data, dict):
            data = detail if isinstance(detail, dict) else {}

        offers = data.get("offers") or []
        if not isinstance(offers, list):
            offers = []

        # PriceCheck returns images from get_product_offers, but the
        # search summary can use a different field name. Keep every
        # supported image field and let normalize_product() select the
        # first browser-usable URL.
        pricecheck_images = (
            data.get("images")
            or data.get("image_urls")
            or data.get("imageUrls")
            or data.get("image")
            or summary.get("images")
            or summary.get("image_urls")
            or summary.get("imageUrls")
            or summary.get("image")
            or summary.get("image_url")
            or summary.get("imageUrl")
            or []
        )

        common = {
            "name": data.get("name") or summary.get("name") or "Unnamed product",
            "description": data.get("description") or summary.get("description") or "",
            "brand": data.get("brand") or summary.get("brand") or "",
            "category": data.get("category") or summary.get("category") or "",
            "images": pricecheck_images,
            "image": pricecheck_images,
            "url": summary.get("url") or summary.get("product_url") or summary.get("productUrl") or "",
            "product_id": pc_id,
        }

        for offer in offers[:PRICECHECK_MAX_OFFERS]:
            if not isinstance(offer, dict):
                continue

            store_name = _safe_string(
                offer.get("store")
                or offer.get("store_name")
                or offer.get("retailer")
                or summary.get("store")
                or "Retailer"
            )

            address = offer.get("address")
            if isinstance(address, dict):
                address = ", ".join(
                    _safe_string(v)
                    for v in (
                        address.get("address"),
                        address.get("streetAddress"),
                        address.get("street"),
                        address.get("suburb"),
                        address.get("city"),
                        address.get("province"),
                        address.get("postalCode"),
                    )
                    if _safe_string(v)
                )
            else:
                address = _safe_string(address)

            row = {
                **common,
                "barcode": (
                    summary.get("barcode")
                    or summary.get("ean")
                    or summary.get("gtin")
                    or data.get("barcode")
                    or data.get("ean")
                    or data.get("gtin")
                    or ""
                ),
                "store": store_name,
                "retailer": store_name,
                "store_id": offer.get("store_id") or offer.get("storeId") or "",
                "offer_id": offer.get("offer_id") or offer.get("offerId") or "",
                "address": address,
                "price": (
                    offer.get("price")
                    or offer.get("total_price")
                    or offer.get("totalPrice")
                    or summary.get("price")
                    or 0
                ),
                "in_stock": offer.get("in_stock", summary.get("in_stock", False)),
                "on_sale": _safe_bool(offer.get("on_special"), False),
                "url": (
                    offer.get("url")
                    or offer.get("product_url")
                    or offer.get("productUrl")
                    or summary.get("url")
                    or ""
                ),
            }

            product = normalize_product(row, retailer=store_name)
            offer_id = _safe_string(row.get("offer_id"))

            if offer_id:
                product["id"] = f"pricecheck_{pc_id}_{offer_id}"
                product["product_id"] = product["id"]

            product["price_source"] = "PriceCheck South Africa live offers"
            product["price_is_live"] = True
            product["price_freshness"] = "live"
            product["pricecheck_product_id"] = pc_id
            product["offer_id"] = offer_id
            product["store_address"] = address
            product["store"] = store_name

            products.append(product)
            _cache_product(product)

    products = _deduplicate_products(products)
    _cache_set(cache_key, products, CACHE_TIMEOUT if products else 60)

    if products:
        _cache_stale_set(cache_key, products)

    if not products and errors:
        raise StoreAPIError(
            "PriceCheck returned no usable offers. "
            + " | ".join(errors[:3])
        )

    return _mark_cached_products(products, "live", True)


# ============================================================
# PARSE RETAILER API - LIVE SHOP PRICES
# ============================================================

def search_parse_retailer_products(
    keyword: str,
    limit: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = OSM_RADIUS_KM,
) -> list[dict]:
    """
    Search every live Parse retailer independently.

    A failure or empty response from one retailer must never hide the
    products returned by another retailer. Search variants are tried
    because retailer indexes can treat spaces and hyphens differently.
    """
    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(1, min(int(limit), 20))
    errors: list[str] = []

    def query_variants(value: str) -> list[str]:
        variants = [value]
        normalised = re.sub(r"[-_]+", " ", value).strip()

        if normalised and normalised.lower() not in {
            item.lower() for item in variants
        }:
            variants.append(normalised)

        hyphenated = re.sub(r"\s+", "-", normalised).strip()

        if hyphenated and hyphenated.lower() not in {
            item.lower() for item in variants
        }:
            variants.append(hyphenated)

        return variants[:3]

    def search_retailer(search_fn, retailer_name: str) -> list[dict]:
        collected: list[dict] = []
        seen = set()

        for query in query_variants(keyword):
            try:
                rows = search_fn(query)
            except StoreAPIError as exc:
                message = str(exc)
                errors.append(f"{retailer_name}: {message}")
                # A 401 will fail every spelling variant; stop retrying
                # the same provider and let the outer provider fallback run.
                if "authentication failed (HTTP 401)" in message:
                    break
                continue

            for product in rows:
                if not isinstance(product, dict):
                    continue

                product_key = (
                    product.get("barcode")
                    or product.get("product_id")
                    or (
                        product.get("retailer"),
                        product.get("name"),
                        product.get("price"),
                    )
                )

                if product_key in seen:
                    continue

                seen.add(product_key)
                collected.append(product)

                if len(collected) >= limit:
                    return collected[:limit]

        return collected[:limit]

    # Both retailers are always queried.
    checkers = search_retailer(
        lambda query: search_checkers_products(
            query,
            limit=limit,
        ),
        "Checkers",
    )

    pnp = search_retailer(
        lambda query: search_pnp_products(
            query,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
        ),
        "Pick n Pay",
    )

    # Interleave retailers so one store does not fill the whole page.
    merged: list[dict] = []
    index = 0

    while (
        len(merged) < limit
        and (
            index < len(checkers)
            or index < len(pnp)
        )
    ):
        if index < len(checkers):
            merged.append(checkers[index])

        if len(merged) >= limit:
            break

        if index < len(pnp):
            merged.append(pnp[index])

        index += 1

    if not merged and errors:
        raise StoreAPIError(
            "No retailer results were available. "
            + " | ".join(errors[:4])
        )

    if not merged and not PARSE_API_KEY and not AZLABS_API_KEY:
        raise StoreAPIError(
            "No retailer API credentials are configured. "
            "Set AZLABS_API_KEY or PARSE_API_KEY in the deployment environment."
        )

    return _deduplicate_products(merged)[:limit]


# ============================================================
# PROVIDER SELECTION
# ============================================================

def _provider_order() -> list[str]:
    """Return configured live providers, skipping providers without keys."""
    available = []

    if AZLABS_API_KEY:
        available.append("azlabs")

    if PARSE_API_KEY:
        available.append("pricecheck")
        # Query Checkers and Pick n Pay as independent providers.
        # The old aggregated "parse" provider could return successfully
        # while a retailer-specific result was hidden by another source.
        available.append("checkers")
        available.append("pnp")

    # Preferred provider controls ordering only. Every configured provider
    # must still be queried so live search always aggregates all sources.
    preferred = API_PROVIDER if API_PROVIDER in {
        "azlabs",
        "pricecheck",
        "parse",
        "checkers",
        "pnp",
    } else "pricecheck"

    # "parse" remains accepted for backwards compatibility with .env,
    # but its retailer search is now represented by the two explicit
    # Checkers/PnP providers so each retailer can surface independently.
    if preferred == "parse":
        preferred_order = ["checkers", "pnp"]
        return preferred_order + [
            p for p in available if p not in preferred_order
        ]

    if preferred in {"checkers", "pnp"}:
        return [preferred] + [
            p for p in available if p != preferred
        ]

    return [preferred] + [p for p in available if p != preferred]


def _search_provider(
    provider: str,
    keyword: str,
    limit: int,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
) -> list[dict]:
    if provider == "azlabs":
        return search_azlabs_products(
            keyword,
            limit=limit,
        )

    if provider == "pricecheck":
        return search_pricecheck_products(
            keyword,
            limit=limit,
        )

    if provider == "parse":
        return search_parse_retailer_products(
            keyword,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
            radius_km=(
                float(radius_km)
                if radius_km is not None
                else OSM_RADIUS_KM
            ),
        )

    if provider == "checkers":
        return search_checkers_products(
            keyword,
            limit=limit,
        )

    if provider == "pnp":
        return search_pnp_products(
            keyword,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
            radius_km=(
                float(radius_km)
                if radius_km is not None
                else OSM_RADIUS_KM
            ),
        )

    return []


def _deduplicate_products(
    products: list[dict],
) -> list[dict]:
    seen = set()
    output = []

    for product in products:
        key = (
            product.get("retailer"),
            product.get("barcode")
            or product.get("product_id"),
            product.get("name"),
            str(product.get("price")),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(product)

    return output


def _interleave_retailer_products(
    products: list[dict],
) -> list[dict]:
    """
    Keep the aggregated search balanced across live retailers.

    Previously the providers were all queried, but the first provider
    could fill the requested page before Checkers/PnP rows reached the UI.
    This made Checkers appear to be unavailable even when its API returned
    valid products. Interleave the live retailer groups so configured
    sources remain visible on the same search page.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []

    for product in products:
        retailer = _normalise_retailer(
            product.get("retailer")
            or product.get("store")
            or "Retailer"
        )

        if retailer not in groups:
            groups[retailer] = []
            order.append(retailer)

        groups[retailer].append(product)

    if len(order) <= 1:
        return products

    # Prefer the two retailer APIs that provide direct live catalogue data,
    # then continue with every other configured provider.
    preferred = [
        retailer
        for retailer in ("Checkers", "Pick n Pay")
        if retailer in groups
    ]
    remaining = [
        retailer
        for retailer in order
        if retailer not in preferred
    ]
    ordered_groups = preferred + remaining

    output: list[dict] = []
    index = 0

    while True:
        added = False

        for retailer in ordered_groups:
            rows = groups[retailer]
            if index < len(rows):
                output.append(rows[index])
                added = True

        if not added:
            break

        index += 1

    return output


# ============================================================
# PUBLIC SEARCH
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

    Provider flow:
        Aggregate every configured provider:
            PriceCheck -> AZ Labs -> Checkers -> Pick n Pay
        (providers without API keys are skipped)

    Cache flow:
        fresh Redis cache -> return the same aggregated live result
        cache miss -> query every configured provider
        individual provider failure/rate limit -> continue with other providers
        complete outage -> use stale Redis data when available
        successful result -> store both fresh and 48-hour stale copies
        final search response -> cached with location data included

    The function keeps the same signature used by the existing
    products/views.py, so no view change is required.
    """

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    try:
        requested_limit = max(
            1,
            int(limit),
        )
    except (TypeError, ValueError):
        requested_limit = 20

    # Query every configured provider with the full requested page size.
    # The previous 20-item cap meant an aggregator search could silently
    # miss products from later providers.
    provider_limit = min(
        requested_limit,
        100,
    )

    # One short-lived Redis entry covers the complete search, including
    # branch pricing and distance/location data. This is the main protection
    # against repeated Parse.bot calls from page refreshes or repeated searches.
    final_cache_key = _search_cache_key(
        keyword,
        requested_limit,
        latitude,
        longitude,
        radius_km,
    )

    cached_results = _cache_get(final_cache_key)
    if cached_results is not None:
        return _mark_cached_products(
            cached_results,
            "cached",
            False,
        )

    errors = []
    products = []

    for provider in _provider_order():
        try:
            results = _search_provider(
                provider,
                keyword,
                provider_limit,
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
            )

            if results:
                # Aggregator mode: keep searching the remaining providers
                # instead of stopping at the first successful API.
                # _deduplicate_products() removes overlapping retailer
                # records after all configured sources have responded.
                products.extend(results)

        except StoreAPIError as exc:
            errors.append(
                f"{provider.title()}: {exc}"
            )

    products = _deduplicate_products(
        products
    )

    # If every live provider is temporarily unavailable, the complete-search
    # stale cache is the last-resort production fallback.
    # It is intentionally checked before raising an outage error.
    if not products:
        stale_results = _cache_stale_get(final_cache_key)
        if stale_results is not None:
            return _mark_cached_products(
                stale_results,
                "stale",
                False,
            )

    # Do not let AZ Labs or PriceCheck consume the entire requested page.
    # The providers are aggregated, then deliberately interleaved so
    # Checkers/PnP live catalogue results are visible when they are available.
    products = _interleave_retailer_products(products)

    if not products:
        stale_results = _cache_stale_get(final_cache_key)
        if stale_results is not None:
            return _mark_cached_products(
                stale_results,
                "stale",
                False,
            )

        if errors:
            raise StoreAPIError(
                "No retailer results were available. "
                + " | ".join(errors[:3])
            )

        raise StoreAPIError(
            "No retailer API is configured. "
            "Set PARSE_API_KEY or AZLABS_API_KEY."
        )

    products = products[:requested_limit]

    # If a provider returned PnP products, upgrade
    # those PnP rows to branch-specific PnP pricing when possible.
    if (
        latitude is not None
        and longitude is not None
        and PNP_BRANCH_LOOKUP_ENABLED
        and any(
            product.get("retailer") == "Pick n Pay"
            for product in products
        )
    ):
        try:
            branch_products = search_nearest_pnp_branch_products(
                keyword=keyword,
                latitude=float(latitude),
                longitude=float(longitude),
                radius_km=(
                    float(radius_km)
                    if radius_km is not None
                    else OSM_RADIUS_KM
                ),
                limit=provider_limit,
            )

            if branch_products:
                products = [
                    product
                    for product in products
                    if product.get("retailer") != "Pick n Pay"
                ]
                products.extend(branch_products)
                products = _deduplicate_products(products)
                products = products[:requested_limit]

        except StoreAPIError:
            # Do not break a successful retailer search just
            # because branch-level PnP lookup is unavailable.
            pass

    if (
        latitude is not None
        and longitude is not None
    ):
        radius = (
            float(radius_km)
            if radius_km is not None
            else OSM_RADIUS_KM
        )

        _attach_location(
            products,
            float(latitude),
            float(longitude),
            radius,
        )

    # Cache the complete response after branch pricing and location have
    # been attached. The stale copy is retained for API outages/rate limits.
    _cache_set(
        final_cache_key,
        products,
        CACHE_TIMEOUT,
    )
    _cache_stale_set(
        final_cache_key,
        products,
    )

    return _mark_cached_products(
        products,
        "live",
        True,
    )


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
    product_id = _safe_string(
        product_id
    )

    if not product_id:
        return None

    cached = _cache_get(
        f"product:{product_id}"
    )

    if cached is not None:
        return cached

    return _cache_stale_get(
        f"product:{product_id}"
    )


def _extract_store_id(
    product: dict,
) -> str:
    if not isinstance(product, dict):
        return ""

    location = product.get(
        "location"
    ) or {}

    if not isinstance(location, dict):
        location = {}

    return _safe_string(
        product.get("store_id")
        or product.get("storeId")
        or location.get("store_id")
        or location.get("storeId")
    )


def get_store_location(
    store_id: str,
):
    """
    Product locations are normally attached during search from
    OpenStreetMap and cached. This avoids spending a Parse credit
    for every product detail page.
    """

    store_id = _safe_string(
        store_id
    )

    if not store_id:
        return None

    return _cache_get(
        f"store:location:v2:{store_id}"
    )


# ============================================================
# OPENSTREETMAP / DISTANCE
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

    delta_lat = math.radians(
        latitude2 - latitude1
    )
    delta_lon = math.radians(
        longitude2 - longitude1
    )

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return (
        radius
        * 2
        * math.asin(math.sqrt(a))
    )


def _osm_query(
    latitude: float,
    longitude: float,
    radius_km: float,
) -> str:
    radius_m = int(
        max(
            500,
            min(
                radius_km * 1000,
                50000,
            ),
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

    retailer_filter = (
        _safe_string(retailer)
        .lower()
    )

    cache_key = (
        f"osm:stores:"
        f"{round(latitude, 3)}:"
        f"{round(longitude, 3)}:"
        f"{round(radius_km, 1)}:"
        f"{retailer_filter}"
    )

    cached = _cache_get(
        cache_key
    )

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

    except (
        requests.RequestException,
        ValueError,
    ):
        return []

    stores = []

    for element in payload.get(
        "elements",
        [],
    ):
        tags = (
            element.get("tags")
            or {}
        )
        center = (
            element.get("center")
            or {}
        )

        lat = (
            element.get("lat")
            or center.get("lat")
        )
        lon = (
            element.get("lon")
            or center.get("lon")
        )

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
            if (
                retailer_filter == "checkers"
                and "checkers" not in name_lower
            ):
                continue

            if (
                retailer_filter
                in {"pick n pay", "pnp"}
                and not (
                    "pick n pay" in name_lower
                    or "pnp" in name_lower
                )
            ):
                continue

            if (
                retailer_filter == "shoprite"
                and "shoprite" not in name_lower
            ):
                continue

            if (
                retailer_filter == "woolworths"
                and "woolworth" not in name_lower
            ):
                continue

            if (
                retailer_filter == "clicks"
                and "clicks" not in name_lower
            ):
                continue

            if (
                retailer_filter == "makro"
                and "makro" not in name_lower
            ):
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
            tags.get(
                "addr:housenumber"
            ),
            tags.get(
                "addr:street"
            ),
            tags.get(
                "addr:suburb"
            ),
            tags.get(
                "addr:city"
            ),
        ]

        store = {
            "store_id": _safe_string(
                element.get("id")
            ),
            "name": name,
            "retailer": _normalise_retailer(
                name
            ),
            "address": ", ".join(
                _safe_string(value)
                for value in address_parts
                if value
            ),
            "city": _safe_string(
                tags.get("addr:city")
            ),
            "province": _safe_string(
                tags.get("addr:state")
            ),
            "latitude": float(lat),
            "longitude": float(lon),
            "distance_km": round(
                distance,
                2,
            ),
            "distance": round(
                distance,
                2,
            ),
            "source": "OpenStreetMap",
        }

        stores.append(store)

        _cache_set(
            f"store:location:{store['store_id']}",
            store,
            STORE_CACHE_TIMEOUT,
        )

    stores.sort(
        key=lambda item: item[
            "distance_km"
        ]
    )

    _cache_set(
        cache_key,
        stores,
        STORE_CACHE_TIMEOUT
        if stores
        else 60,
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
            distance = _haversine_km(
                latitude,
                longitude,
                float(
                    store["latitude"]
                ),
                float(
                    store["longitude"]
                ),
            )

            item = dict(store)

            item["distance_km"] = round(
                distance,
                2,
            )
            item["distance"] = round(
                distance,
                2,
            )

            valid.append(item)

        except Exception:
            continue

    if not valid:
        return None

    return min(
        valid,
        key=lambda item: item[
            "distance_km"
        ],
    )


def _add_distance(
    product: dict,
    latitude: float | None,
    longitude: float | None,
):
    location = (
        product.get("location")
        or {}
    )

    if not isinstance(
        location,
        dict,
    ):
        location = {}

    store_lat = (
        location.get("latitude")
        or location.get("lat")
    )
    store_lon = (
        location.get("longitude")
        or location.get("lon")
        or location.get("lng")
    )

    if (
        latitude is None
        or longitude is None
        or store_lat is None
        or store_lon is None
    ):
        product["distance_km"] = None
        product["distance"] = None
        return

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

    except Exception:
        product["distance_km"] = None
        product["distance"] = None


def _attach_location(
    products: list[dict],
    latitude: float | None,
    longitude: float | None,
    radius_km: float,
):
    """
    Attach branch/store location and distance to product offers.

    Retailer-specific APIs are preferred for Checkers/PnP. PriceCheck can
    return many other South African retailers with an address but no
    coordinates, so those offers are matched against nearby OSM stores by
    store name/address when possible.
    """
    if latitude is None or longitude is None:
        return products

    retailer_names = sorted(
        {
            _safe_string(
                product.get("retailer")
                or product.get("store")
            )
            for product in products
            if (
                product.get("retailer")
                or product.get("store")
            )
        }
    )

    stores_by_retailer = {}

    for retailer in retailer_names:
        if retailer == "Checkers":
            try:
                stores_by_retailer[retailer] = get_checkers_stores(
                    latitude,
                    longitude,
                    radius_km,
                )
            except StoreAPIError:
                stores_by_retailer[retailer] = []
        elif retailer == "Pick n Pay":
            try:
                stores_by_retailer[retailer] = get_pnp_stores(
                    latitude,
                    longitude,
                )
                stores_by_retailer[retailer] = [
                    store
                    for store in stores_by_retailer[retailer]
                    if store.get("distance_km") is not None
                    and store.get("distance_km") <= radius_km
                ]
            except StoreAPIError:
                stores_by_retailer[retailer] = []
        else:
            stores_by_retailer[retailer] = find_nearby_stores(
                latitude,
                longitude,
                radius_km,
                retailer=retailer,
            )

        if not stores_by_retailer[retailer]:
            stores_by_retailer[retailer] = find_nearby_stores(
                latitude,
                longitude,
                radius_km,
                retailer=retailer,
            )

    # PriceCheck offers often contain a registered/physical address but
    # no coordinates. Search nearby OSM supermarkets once and match those
    # offers by store name/address so distance can still be calculated.
    address_products = [
        product
        for product in products
        if isinstance(product.get("location"), dict)
        and product.get("location", {}).get("address")
        and not (
            product.get("location", {}).get("latitude")
            or product.get("location", {}).get("lat")
        )
    ]

    all_nearby_stores = []
    if address_products:
        all_nearby_stores = find_nearby_stores(
            latitude,
            longitude,
            radius_km,
            retailer="",
        )

    def compact(value: Any) -> str:
        return re.sub(
            r"[^a-z0-9]+",
            "",
            _safe_string(value).lower(),
        )

    for product in products:
        retailer = _normalise_retailer(
            product.get("retailer")
            or product.get("store")
            or ""
        )

        location = product.get("location") or {}
        if not isinstance(location, dict):
            location = {}

        # First try the address/name supplied by PriceCheck against nearby
        # physical stores. This is deliberately a best-effort match; if no
        # physical match exists, the product keeps its registered address
        # and distance remains unavailable rather than being invented.
        if (
            location.get("address")
            and not (
                location.get("latitude")
                or location.get("lat")
            )
            and all_nearby_stores
        ):
            product_name = compact(
                location.get("name")
                or product.get("store")
                or product.get("retailer")
            )
            product_address = compact(
                location.get("address")
            )

            matches = []
            for store in all_nearby_stores:
                store_name = compact(store.get("name"))
                store_address = compact(store.get("address"))

                name_match = bool(
                    product_name
                    and store_name
                    and (
                        product_name in store_name
                        or store_name in product_name
                    )
                )

                address_tokens = [
                    token
                    for token in re.findall(
                        r"[a-z0-9]{4,}",
                        product_address,
                    )
                ]
                address_match = bool(
                    address_tokens
                    and store_address
                    and sum(
                        1
                        for token in address_tokens
                        if token in store_address
                    ) >= min(2, len(address_tokens))
                )

                if name_match or address_match:
                    matches.append(store)

            nearest_match = _nearest_store(
                matches,
                latitude,
                longitude,
            )

            if nearest_match:
                location = {
                    **location,
                    **nearest_match,
                    "address": (
                        location.get("address")
                        or nearest_match.get("address")
                    ),
                }
                product["location"] = location
                product["store_id"] = (
                    product.get("store_id")
                    or nearest_match.get("store_id")
                )

        # A product may already contain a small Checkers store object
        # (storeId/serviceOptionIds/distanceFromCustomer) without address or
        # coordinates. Replace/merge it with the real branch returned by
        # find_stores so the UI gets a proper name, address and distance.
        retailer_stores = stores_by_retailer.get(retailer, [])
        current_store_id = _safe_string(
            product.get("store_id")
            or location.get("store_id")
            or location.get("storeId")
            or location.get("id")
        )
        nearest = None
        if current_store_id and retailer_stores:
            nearest = next(
                (
                    store for store in retailer_stores
                    if _safe_string(store.get("store_id")) == current_store_id
                ),
                None,
            )
        if nearest is None:
            nearest = _nearest_store(
                retailer_stores,
                latitude,
                longitude,
            )

        if nearest:
            existing_location = product.get("location") or {}
            if not isinstance(existing_location, dict):
                existing_location = {}
            product["location"] = {
                **existing_location,
                **nearest,
            }
            product["store_id"] = (
                product.get("store_id")
                or nearest.get("store_id")
            )
            product["store"] = nearest.get("name") or product.get("store")

        _add_distance(
            product,
            latitude,
            longitude,
        )

    return products


# ============================================================
# PRICE COMPARISON
# ============================================================

def _normalized_match_key(
    product: dict,
) -> str:
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

    return (
        f"{brand}|{name}|{size}"
    )


def compare_products(
    products: list[dict],
):
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
            _to_decimal(
                expensive.get("price")
            )
            - _to_decimal(
                cheapest.get("price")
            )
        ),
    }


def compare_equivalent_products(
    products: list[dict],
):
    groups = {}

    for product in products or []:
        key = _normalized_match_key(
            product
        )
        groups.setdefault(
            key,
            [],
        ).append(product)

    output = []

    for key, group in groups.items():
        if len(group) < 2:
            continue

        comparison = compare_products(
            group
        )
        comparison["match_key"] = key
        output.append(comparison)

    return output


def get_cheapest_product(
    products,
):
    if not products:
        return None

    return min(
        products,
        key=lambda item: _to_decimal(
            item.get("price"),
            "999999999.99",
        ),
    )


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
# COMPATIBILITY HELPERS
# ============================================================

def extract_store_locations(
    payload,
):
    if not isinstance(
        payload,
        dict,
    ):
        return []

    data = (
        payload.get("data")
        or payload.get("stores")
        or payload.get("results")
        or []
    )

    if not isinstance(
        data,
        list,
    ):
        return []

    return [
        item
        for item in data
        if isinstance(
            item,
            dict,
        )
    ]


def extract_pnp_products(
    payload,
):
    rows = _extract_rows(
        payload
    )

    return [
        normalize_product(
            item,
            retailer="Pick n Pay",
        )
        for item in rows
    ]


def extract_price_comparisons(
    payload,
):
    if isinstance(
        payload,
        dict,
    ):
        data = payload.get(
            "data",
            payload,
        )

        if isinstance(
            data,
            dict,
        ):
            return (
                data.get("offers")
                or data.get(
                    "comparison"
                )
                or data.get(
                    "matches"
                )
                or []
            )

        if isinstance(
            data,
            list,
        ):
            return data

    if isinstance(
        payload,
        list,
    ):
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