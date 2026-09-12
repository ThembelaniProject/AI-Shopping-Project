from flask.templating import _render
import requests

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

        price = _extract_price(
            product.get(field)
        )

        if price is None:
            continue

        if "WithoutDecimal" in field:
            price = price / Decimal("100")

        return price

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

        price = _extract_price(
            product.get(field)
        )

        if price is None:
            continue

        if "WithoutDecimal" in field:
            price = price / Decimal("100")

        return price

    return None


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
        ).quantize(
            Decimal("0.01")
        )

    discount_fields = [
        "discountAmount",
        "discount_amount",
        "saving",
        "savings",
        "saveAmount",
        "save_amount",
        "promotionDiscount",
        "promotion_discount",
    ]

    for field in discount_fields:

        value = product.get(field)

        discount = _extract_price(value)

        if discount is not None:

            if "WithoutDecimal" in field:
                discount = discount / Decimal("100")

            return discount.quantize(
                Decimal("0.01")
            )

    return Decimal("0.00")


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
        "onSale",
        "isOnSale",
        "isPromotion",
        "promotion",
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

    return False


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

def search_products(keyword="", limit=30):

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
                raw_product
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


# ==========================================================
# NORMALIZE PRODUCT
# ==========================================================

def normalize_product(product):

    # ======================================================
    # PRODUCT ID
    # ======================================================

    product_id = _extract_product_id(
        product
    )

    raw_id = product.get("id")

    raw_product_id = product.get(
        "productId"
    )

    raw_product_id_underscore = product.get(
        "product_id"
    )

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
    # PRICE
    # ======================================================

    sale_price = _extract_sale_price(
        product
    )

    regular_price = _extract_regular_price(
        product
    )

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
    # SALE
    # ======================================================

    on_sale = _extract_on_sale(
        product,
        regular_price=regular_price,
        sale_price=sale_price,
    )

    if on_sale and regular_price <= sale_price:
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

    # ======================================================
    # EXPIRY
    # ======================================================

    deal_expiry = _extract_deal_expiry(
        product
    )

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

    category = (
        product.get("category")
        or product.get("categoryName")
        or "Other"
    )

    # ======================================================
    # COLOUR
    # ======================================================

    colour = (
        product.get("colour")
        or product.get("color")
        or product.get("colourName")
        or product.get("colorName")
        or "Not specified"
    )

    # ======================================================
    # SIZE
    # ======================================================

    size = (
        product.get("size")
        or product.get("sizeName")
        or "Not specified"
    )

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

        except (
            ValueError,
            TypeError,
        ):

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

    image = _extract_image(
        product
    )

    images = _extract_images(
        product
    )

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

    shipping_cost = Decimal(
        "0.00"
    )

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

        "raw_product_id":
            raw_product_id,

        "raw_product_id_underscore":
            raw_product_id_underscore,

        "raw_sku":
            raw_sku,

        "raw_code":
            raw_code,

        "source":
            "checkers",

        "name":
            name,

        "title":
            name,

        "description":
            description,

        "brand":
            brand,

        "category":
            category,

        "colour":
            colour,

        "size":
            size,

        "price":
            current_price,

        "regular_price":
            regular_price,

        "sale_price":
            (
                current_price
                if on_sale
                else None
            ),

        "on_sale":
            on_sale,

        "discount_amount":
            discount_amount,

        "discount_percentage":
            discount_percentage,

        "deal_expiry":
            deal_expiry,

        "shipping_cost":
            shipping_cost,

        "total_cost":
            (
                current_price
                + shipping_cost
            ),

        "stock":
            stock,

        "rating":
            Decimal("0.00"),

        "store":
            "Checkers",

        "location":
            "South Africa",

        "image":
            image,

        "thumbnail":
            image,

        "images":
            images,

        "url":
            url,
    }

    print(
        "PRODUCT:",
        name,
        "| ID:",
        product_id,
        "| REGULAR:",
        regular_price,
        "| SALE:",
        sale_price,
        "| ON SALE:",
        on_sale,
        "| SAVING:",
        discount_amount,
        "| EXPIRY:",
        deal_expiry,
    )

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

        return _render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error": "No product ID was provided.",
            },
        )
        
    # ------------------------------------------------------
    # CHECK CACHE
    # ------------------------------------------------------

    cache_key = f"checkers_product_{product_id}"

    product = cache.get(cache_key)

    if product:
        return product


    try:

        # --------------------------------------------------
        # GET EXACT PRODUCT
        # --------------------------------------------------

        product = get_product(
            product_id
        )

        # --------------------------------------------------
        # IMAGE
        # --------------------------------------------------

        product["image"] = get_product_image( # type: ignore
            product
        )

        # --------------------------------------------------
        # PRICE
        # --------------------------------------------------

        try:

            product["price"] = Decimal(
                str(
                    product.get(
                        "price",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["price"] = Decimal(
                "0.00"
            )

        # --------------------------------------------------
        # REGULAR PRICE
        # --------------------------------------------------

        try:

            product["regular_price"] = Decimal(
                str(
                    product.get(
                        "regular_price",
                        product["price"],
                    )
                    or product["price"]
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["regular_price"] = (
                product["price"]
            )

        # --------------------------------------------------
        # SALE PRICE
        # --------------------------------------------------

        sale_price = product.get(
            "sale_price"
        )

        if sale_price is not None:

            try:

                product["sale_price"] = Decimal(
                    str(sale_price)
                )

            except (
                ValueError,
                TypeError,
                InvalidOperation,
            ):

                product["sale_price"] = None

        # --------------------------------------------------
        # SHIPPING
        # --------------------------------------------------

        try:

            product["shipping_cost"] = Decimal(
                str(
                    product.get(
                        "shipping_cost",
                        0,
                    )
                    or 0
                )
            )

        except (
            ValueError,
            TypeError,
            InvalidOperation,
        ):

            product["shipping_cost"] = Decimal(
                "0.00"
            )

        # --------------------------------------------------
        # TOTAL
        # --------------------------------------------------

        product["total_cost"] = (
            product["price"]
            + product["shipping_cost"]
        )

        # --------------------------------------------------
        # DEBUG
        # --------------------------------------------------

        print("\n========================================")
        print("PRODUCT DETAIL")
        print("URL product_id:", product_id)
        print("Returned id:", product.get("id"))
        print("Returned external_id:", product.get("external_id"))
        print("Product name:", product.get("name"))
        print("========================================\n")

        # --------------------------------------------------
        # RENDER
        # --------------------------------------------------

        return _render(
            request,
            "products/detail.html",
            {
                "product": product,
            },
        )

    except StoreAPIError as exc:

        return _render(
            request,
            "products/detail.html",
            {
                "product": None,
                "api_error": str(exc),
            },
        )
