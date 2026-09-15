import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings


# ==========================================================
# CHECKERS / PARSE API
# ==========================================================

CHECKERS_SEARCH_URL = (
    "https://api.parse.bot/scraper/"
    "a7a3a4ba-dfb7-4476-9712-8753b2fb3140/"
    "search_products"
)


# ==========================================================
# API ERROR
# ==========================================================

class StoreAPIError(Exception):
    """
    Raised when the Checkers/Parse API fails.
    """
    pass


# ==========================================================
# SEARCH PRODUCTS
# ==========================================================

def search_products(keyword, limit=30):
    """
    Search real Checkers products through the Parse API.

    Returns normalized product dictionaries.
    """

    if not keyword:
        return []

    # ------------------------------------------------------
    # Check API key
    # ------------------------------------------------------

    api_key = getattr(
        settings,
        "PARSE_API_KEY",
        ""
    )

    if not api_key:
        raise StoreAPIError(
            "PARSE_API_KEY is not configured in Django settings."
        )

    # ------------------------------------------------------
    # API request
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

            timeout=15,
        )

        # Raise an error for HTTP 400/401/403/404/500 etc.
        response.raise_for_status()

    except requests.RequestException as exc:

        raise StoreAPIError(
            f"Unable to connect to Checkers API: {exc}"
        ) from exc

    # ------------------------------------------------------
    # Decode JSON
    # ------------------------------------------------------

    try:

        data = response.json()

    except ValueError as exc:

        raise StoreAPIError(
            "Checkers API did not return valid JSON."
        ) from exc

    # ------------------------------------------------------
    # Validate response
    # ------------------------------------------------------

    if not isinstance(data, dict):

        raise StoreAPIError(
            "Checkers API returned invalid data."
        )

    # ------------------------------------------------------
    # Get products
    # ------------------------------------------------------

    products = data.get(
        "products",
        []
    )

    if products is None:
        products = []

    if not isinstance(products, list):

        raise StoreAPIError(
            "Checkers API returned an unexpected products format."
        )

    # ------------------------------------------------------
    # Normalize products
    # ------------------------------------------------------

    return [
        normalize_product(product)
        for product in products
        if isinstance(product, dict)
    ]


# ==========================================================
# NORMALIZE PRODUCT
# ==========================================================

def normalize_product(product):
    """
    Convert Checkers/Parse product data into the
    structure expected by SmartSpend.
    """

    # ------------------------------------------------------
    # PRICE
    # ------------------------------------------------------

    price_cents = (
        product.get(
            "priceWithoutDecimal",
            0
        )
        or 0
    )

    try:

        price = (
            Decimal(str(price_cents))
            / Decimal("100")
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):

        price = Decimal("0.00")

    # ------------------------------------------------------
    # PROMOTION
    # ------------------------------------------------------

    on_sale = bool(
        product.get(
            "isOnPromotion",
            False
        )
    )

    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

    stock_available = bool(
        product.get(
            "isStockAvailable",
            False
        )
    )

    stock =500 if stock_available else 0

    # ------------------------------------------------------
    # IMAGE
    # ------------------------------------------------------

    image = (
        product.get(
            "image",
            ""
        )
        or product.get(
            "thumbnail",
            ""
        )
        or ""
    )

    # ------------------------------------------------------
    # PRODUCT URL
    # ------------------------------------------------------

    product_url = (
        product.get(
            "url",
            ""
        )
        or product.get(
            "productUrl",
            ""
        )
        or ""
    )

    # ------------------------------------------------------
    # SALE PRICE
    # ------------------------------------------------------

    sale_price = None

    if on_sale:
        sale_price = price

    # ------------------------------------------------------
    # RETURN NORMALIZED PRODUCT
    # ------------------------------------------------------

    return {

        # External API ID
        "external_id": product.get(
            "id"
        ),

        # Basic information
        "name": product.get(
            "name",
            "Unknown Product"
        ),

        "description": product.get(
            "description",
            ""
        ),

        # Pricing
        "price": price,

        "regular_price": price,

        "sale_price": sale_price,

        "on_sale": on_sale,

        # Brand/category
        "brand": product.get(
            "brand",
            "Unknown"
        ),

        "category": product.get(
            "category",
            "Unknown"
        ),

        # Optional filters
        "colour": product.get(
            "colour",
            product.get(
                "color",
                ""
            )
        ),

        "size": product.get(
            "size",
            ""
        ),

        # Store information
        "store": "Checkers",

        "location": "South Africa",

        # Shipping
        "shipping_cost": Decimal(
            "0.00"
        ),

        # Stock
        "stock": stock,

        # Images
        "image": image,

        # Product link
        "url": product_url,

        # Rating
        "rating": Decimal(
            "0"
        ),

        # Discount
        "discount_percentage": Decimal(
            "0"
        ),
    }