import requests
from decimal import Decimal


DUMMYJSON_PRODUCTS_URL = "https://dummyjson.com/products/search"


class StoreAPIError(Exception):
    """Raised when the store API cannot be reached or returns bad data."""
    pass


def search_products(keyword, limit=30):
    """
    Search DummyJSON for products.

    Returns a list of normalized dictionaries that our Django
    application can work with regardless of the external API format.
    """

    if not keyword:
        return []

    try:
        response = requests.get(
            DUMMYJSON_PRODUCTS_URL,
            params={
                "q": keyword,
                "limit": limit,
            },
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:
        raise StoreAPIError(
            f"Unable to connect to product API: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise StoreAPIError("Product API returned an invalid response.")

    products = data.get("products", [])

    return [
        normalize_product(product)
        for product in products
        if isinstance(product, dict)
    ]


def normalize_product(product):
    """
    Convert the external API product into the structure expected
    by our Django shopping application.
    """

    price = Decimal(str(product.get("price", 0) or 0))

    return {
        "external_id": product.get("id"),

        "name": product.get("title", "Unknown Product"),

        "description": product.get(
            "description",
            ""
        ),

        "price": price,

        "brand": product.get(
            "brand",
            "Unknown"
        ),

        "category": product.get(
            "category",
            "Unknown"
        ),

        # DummyJSON does not provide all of the fields
        # used by our application, so we provide safe defaults.
        "colour": "",

        "size": "",

        "store": "DummyJSON",

        "location": "Online",

        "shipping_cost": Decimal("0.00"),

        "stock": product.get(
            "stock",
            0
        ),

        "image": product.get(
            "thumbnail",
            ""
        ),

        "url": "",

        "rating": product.get(
            "rating",
            0
        ),

        "discount_percentage": product.get(
            "discountPercentage",
            0
        ),
    }
