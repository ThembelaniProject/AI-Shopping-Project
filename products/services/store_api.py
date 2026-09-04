import requests
from decimal import Decimal, InvalidOperation


DUMMYJSON_BASE_URL = "https://dummyjson.com/products"
DUMMYJSON_SEARCH_URL = f"{DUMMYJSON_BASE_URL}/search"


class StoreAPIError(Exception):
    pass


def _to_decimal(value, default="0.00"):
    try:
        return Decimal(str(value))

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):
        return Decimal(default)


def _to_stock(value):
    try:
        return int(value or 0)

    except (
        ValueError,
        TypeError,
    ):
        return 0


def _normalise_product(product):

    product_id = product.get("id")

    price = _to_decimal(
        product.get("price")
    )

    shipping_cost = Decimal("0.00")

    stock = _to_stock(
        product.get("stock")
    )

    rating = _to_decimal(
        product.get("rating"),
        default="0.00",
    )

    title = (
        product.get("title")
        or "Unnamed Product"
    )

    description = (
        product.get("description")
        or ""
    )

    brand = (
        product.get("brand")
        or "Unknown"
    )

    category = (
        product.get("category")
        or "Other"
    )

    colour = (
        product.get("colour")
        or product.get("color")
        or "Not specified"
    )

    size = (
        product.get("size")
        or "Not specified"
    )

    location = (
        product.get("location")
        or "Online"
    )

    thumbnail = (
        product.get("thumbnail")
        or ""
    )

    images = (
        product.get("images", [])
        or []
    )

    # DummyJSON is not a real retailer,
    # so there is currently no real checkout URL.
    url = ""

    return {

        # Identity
        "id": product_id,

        "external_id": product_id,

        "source": "dummyjson",

        # Basic information
        "name": title,

        "title": title,

        "description": description,

        "brand": brand,

        "category": category,

        # Product attributes
        "colour": colour,

        "size": size,

        # Pricing
        "price": price,

        "shipping_cost": shipping_cost,

        "total_cost": (
            price + shipping_cost
        ),

        # Availability
        "stock": stock,

        # Rating
        "rating": rating,

        # Store information
        "store": "DummyJSON",

        "location": location,

        # Images
        "image": thumbnail,

        "thumbnail": thumbnail,

        "images": images,

        # External product page
        "url": url,
    }


def _request_json(url, params=None):

    try:

        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        response.raise_for_status()

        return response.json()

    except requests.Timeout as exc:

        raise StoreAPIError(
            "The product store took too long to respond."
        ) from exc

    except requests.ConnectionError as exc:

        raise StoreAPIError(
            "Unable to connect to the product store."
        ) from exc

    except requests.HTTPError as exc:

        raise StoreAPIError(
            "The product store returned an error."
        ) from exc

    except requests.RequestException as exc:

        raise StoreAPIError(
            f"Unable to connect to the product store: {exc}"
        ) from exc

    except ValueError as exc:

        raise StoreAPIError(
            "The product store returned invalid data."
        ) from exc


def search_products(keyword="", limit=30):

    keyword = (
        keyword or ""
    ).strip()

    if not keyword:
        return []

    # --------------------------------------
    # Validate limit
    # --------------------------------------

    try:

        limit = int(limit)

    except (
        ValueError,
        TypeError,
    ):

        limit = 30

    # Keep requests reasonable.
    limit = max(
        1,
        min(limit, 100),
    )

    # --------------------------------------
    # Search DummyJSON
    # --------------------------------------

    params = {
        "q": keyword,
        "limit": limit,
    }

    data = _request_json(
        DUMMYJSON_SEARCH_URL,
        params=params,
    )

    # IMPORTANT:
    # raw_products must ALWAYS be assigned
    # before the loop below.
    raw_products = data.get(
        "products",
        [],
    )

    if not isinstance(
        raw_products,
        list,
    ):

        raise StoreAPIError(
            "The product store returned an unexpected response."
        )

    # --------------------------------------
    # Normalise products
    # --------------------------------------

    products = []

    for raw_product in raw_products:

        if not isinstance(
            raw_product,
            dict,
        ):
            continue

        try:

            product = _normalise_product(
                raw_product
            )

            products.append(product)

        except Exception:

            # One malformed product should not
            # destroy the entire search result.
            continue

    return products


def get_product(product_id):

    if not product_id:

        raise StoreAPIError(
            "A product ID is required."
        )

    url = (
        f"{DUMMYJSON_BASE_URL}/{product_id}"
    )

    product = _request_json(url)

    if not isinstance(
        product,
        dict,
    ):

        raise StoreAPIError(
            "The product store returned an invalid product."
        )

    return _normalise_product(
        product
    )
