"""
Multi-provider South African retail integration for AI Shopping.

Provider order:
1. Parse retailer APIs - primary live retailer catalogue for Checkers + Pick n Pay.
2. AZ Labs Grocery API - fallback live catalogue for Pick n Pay + Checkers.
3. LoyaltyHub - broad South African refreshed-price fallback.

All providers are normalized into one product shape so products/views.py
does not need to know which API supplied the result.

Important:
- Never put API keys in this file.
- Configure AZLABS_API_KEY, PARSE_API_KEY and LOYALTYHUB_API_KEY as
  environment variables.
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
# CONFIGURATION
# ============================================================

AZLABS_API_KEY = (
    getattr(settings, "AZLABS_API_KEY", None)
    or os.getenv("AZLABS_API_KEY", "")
).strip()

PARSE_API_KEY = (
    getattr(settings, "PARSE_API_KEY", None)
    or os.getenv("PARSE_API_KEY", "")
).strip()

LOYALTYHUB_API_KEY = (
    getattr(settings, "LOYALTYHUB_API_KEY", None)
    or os.getenv("LOYALTYHUB_API_KEY", "")
).strip()

API_PROVIDER = os.getenv(
    "RETAILER_API_PROVIDER",
    "parse",
).strip().lower()

AZLABS_BASE_URL = "https://azlabs.ai/api/v1"
AZLABS_SEARCH_URL = f"{AZLABS_BASE_URL}/grocery/search"

PARSE_BASE_URL = "https://api.parse.bot/scraper"

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
    int(os.getenv("PNP_MAX_BRANCHES_TO_TRY", "1")),
)

LOYALTYHUB_BASE_URL = "https://loyaltyhub.co.za/api/v1"
LOYALTYHUB_PRICES_URL = f"{LOYALTYHUB_BASE_URL}/prices"

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

CACHE_TIMEOUT = int(
    os.getenv("PRODUCT_CACHE_TIMEOUT", "60")
)  # 60 seconds when live mode is disabled

STALE_CACHE_TIMEOUT = int(
    os.getenv("PRODUCT_STALE_CACHE_TIMEOUT", "172800")
)  # 48 hours

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

def _safe_string(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default
    return str(value).strip()


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
    AZ Labs, Parse and LoyaltyHub.
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
    Convert AZ Labs, Checkers, PnP and LoyaltyHub records into
    one stable shape consumed by products/views.py.
    """

    raw = raw if isinstance(raw, dict) else {}

    source_retailer = _normalise_retailer(
        retailer
        or _first_value(
            raw,
            "retailer",
            "store",
            "merchant",
            "storeName",
        )
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
        raw.get("primaryImage"),
        raw.get("primary_image"),
        raw.get("media"),
        raw.get("images"),
        raw.get("imageUrls"),
        raw.get("image_urls"),
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
    )

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

    barcode = _safe_string(
        _first_value(
            raw,
            "barcode",
            "ean",
            "gtin",
            "ean13",
        )
    )

    size = _safe_string(
        _first_value(
            raw,
            "size",
            "pack_size",
            "packSize",
        )
    )

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
        "colour": _safe_string(
            raw.get("colour")
            or raw.get("color")
        ),
        "size": size,
        "barcode": barcode,
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
        "distance_km": None,
        "distance": None,
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
        raise StoreAPIError(
            f"{provider} API key is invalid."
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
        raise StoreAPIError(
            f"{provider} rate limit reached. "
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
# AZ LABS
# ============================================================

def search_azlabs_products(
    keyword: str,
    limit: int = 20,
    store: str = "all",
) -> list[dict]:
    if not AZLABS_API_KEY:
        raise StoreAPIError(
            "AZLABS_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(
        1,
        min(int(limit), 20),
    )

    cache_key = (
        f"azlabs:search:"
        f"{keyword.lower()}:"
        f"{store}:{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None and not LIVE_PRICE_MODE:
        return cached

    payload = _request_json(
        "GET",
        AZLABS_SEARCH_URL,
        headers={
            "Authorization": (
                f"Bearer {AZLABS_API_KEY}"
            ),
            "Accept": "application/json",
        },
        params={
            "q": keyword,
            "store": store,
        },
        provider="AZ Labs",
    )

    rows = _extract_rows(payload)

    products = []

    for row in rows[:limit]:
        product = normalize_product(row)
        product["price_source"] = "AZ Labs live grocery catalogue"
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
        f"checkers:search:"
        f"{keyword.lower()}:{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None and not LIVE_PRICE_MODE:
        return cached

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

    rows = _extract_rows(payload)

    products = []

    for row in rows[:limit]:
        row = dict(row)

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

        if (
            row.get("regular_price") in (None, "")
            and row.get("oldPrice") not in (None, "")
        ):
            old_price = row.get("oldPrice")
            # Checkers can expose oldPrice as cents as well.
            if row.get("oldPriceWithoutDecimal") not in (None, ""):
                old_price = (
                    Decimal(str(row["oldPriceWithoutDecimal"]))
                    / Decimal("100")
                )
            row["regular_price"] = old_price

        product = normalize_product(
            row,
            retailer="Checkers",
        )
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

        address = _safe_string(
            raw.get("address")
            or raw.get("storeAddress")
            or location.get("address")
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
                f"store:location:{store['store_id']}",
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

    cache_key = "pnp:stores:all"

    stores = _cache_get(cache_key)

    if stores is None:
        payload = _request_json(
            "GET",
            PNP_STORES_URL,
            headers={
                "X-API-Key": PARSE_API_KEY,
                "Accept": "application/json",
            },
            provider="Pick n Pay stores",
        )

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

        address = _safe_string(
            store.get("storeAddress")
            or store.get("address")
        )

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

    if cached is not None and not LIVE_PRICE_MODE:
        return cached

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

    Only the nearest branch is queried by default to control Parse
    credits. Set PNP_MAX_BRANCHES_TO_TRY > 1 if comparison across
    multiple nearby PnP branches is required.
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

    if cached is not None and not LIVE_PRICE_MODE:
        return cached

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
# LOYALTYHUB
# ============================================================

def search_loyaltyhub_products(
    keyword: str,
    limit: int = 20,
    retailer: str = "",
) -> list[dict]:
    if not LOYALTYHUB_API_KEY:
        raise StoreAPIError(
            "LOYALTYHUB_API_KEY is not configured."
        )

    keyword = _safe_string(keyword)

    if not keyword:
        return []

    limit = max(
        1,
        min(int(limit), 20),
    )

    cache_key = (
        f"loyaltyhub:prices:"
        f"{keyword.lower()}:"
        f"{_retailer_key(retailer) if retailer else 'all'}:"
        f"{limit}"
    )

    cached = _cache_get(cache_key)

    if cached is not None and not LIVE_PRICE_MODE:
        return cached

    params = {
        "search": keyword,
        "limit": limit,
        "offset": 0,
    }

    if retailer:
        params["retailer"] = retailer

    try:
        payload = _request_json(
            "GET",
            LOYALTYHUB_PRICES_URL,
            headers={
                "Authorization": (
                    f"Bearer {LOYALTYHUB_API_KEY}"
                ),
                "Accept": "application/json",
            },
            params=params,
            provider="LoyaltyHub",
        )
    except StoreAPIError:
        stale = _cache_stale_get(cache_key)
        if stale is not None:
            return stale
        raise

    rows = _extract_rows(payload)

    freshness = ""
    if isinstance(payload, dict):
        meta = payload.get("meta") or {}
        if isinstance(meta, dict):
            freshness = _safe_string(
                meta.get("updated_at")
                or meta.get("updatedAt")
            )

    products = []

    for row in rows[:limit]:
        if freshness and not row.get("updated_at"):
            row = dict(row)
            row["updated_at"] = freshness

        product = normalize_product(row)
        product["price_source"] = "LoyaltyHub price feed"
        product["price_is_live"] = False
        product["price_freshness"] = "refreshed feed"
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
                errors.append(f"{retailer_name}: {exc}")
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

    return _deduplicate_products(merged)[:limit]


# ============================================================
# PROVIDER SELECTION
# ============================================================

def _provider_order() -> list[str]:
    if API_PROVIDER in {
        "parse",
        "azlabs",
        "checkers",
        "pnp",
        "loyaltyhub",
    }:
        preferred = API_PROVIDER
    else:
        preferred = "azlabs"

    default_order = [
        "parse",
        "checkers",
        "pnp",
        "azlabs",
        "loyaltyhub",
    ]

    return [
        preferred,
        *[
            provider
            for provider in default_order
            if provider != preferred
        ],
    ]


def _search_provider(
    provider: str,
    keyword: str,
    limit: int,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
) -> list[dict]:
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

    if provider == "azlabs":
        return search_azlabs_products(
            keyword,
            limit=limit,
            store="all",
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

    if provider == "loyaltyhub":
        return search_loyaltyhub_products(
            keyword,
            limit=limit,
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
        Parse retailer APIs (Checkers + Pick n Pay)
            -> AZ Labs live fallback
            -> LoyaltyHub refreshed-price fallback

    Cache flow:
        live mode -> retailer API is queried on every search
        provider failure -> stale cache if available
        live mode disabled -> normal short cache is used
        successful result -> retained as a stale/outage fallback

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

    provider_limit = min(
        requested_limit,
        20,
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
                products.extend(results)

                # Stop after the first successful provider tier. The
                # primary Parse tier already queries both live retailers.
                break

        except StoreAPIError as exc:
            errors.append(
                f"{provider.title()}: {exc}"
            )

    products = _deduplicate_products(
        products
    )

    if not products:
        if errors:
            raise StoreAPIError(
                "No retailer results were available. "
                + " | ".join(errors[:3])
            )

        raise StoreAPIError(
            "No retailer API is configured. "
            "Set PARSE_API_KEY, AZLABS_API_KEY or "
            "LOYALTYHUB_API_KEY."
        )

    products = products[:requested_limit]

    # If AZ Labs or another provider returned PnP products, upgrade
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
            # Do not break a successful AZ Labs/Checkers search just
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
        f"store:location:{store_id}"
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
    One cached OSM query per retailer/area, not one request per product.
    """

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
        if (
            latitude is None
            or longitude is None
        ):
            continue

        # Use retailer-specific branch data first. This gives the UI
        # an actual branch address/coordinates instead of an arbitrary
        # supermarket found by OpenStreetMap.
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

        # Retailer API branch lookup can fail or return no branch. Fall
        # back to OSM rather than losing the product completely.
        if not stores_by_retailer[retailer]:
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

        location = (
            product.get("location")
            or {}
        )

        if not location:
            nearest = _nearest_store(
                stores_by_retailer.get(
                    retailer,
                    [],
                ),
                latitude,
                longitude,
            )

            if nearest:
                product["location"] = nearest
                product["store_id"] = (
                    product.get(
                        "store_id"
                    )
                    or nearest.get(
                        "store_id"
                    )
                )

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