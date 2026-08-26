from flask import Blueprint, render_template, request
from flask_login import login_required

from app import db
from app.models import Product
from app.services.recommender import calculate_distance


products_bp = Blueprint(
    "products",
    __name__,
    url_prefix="/products"
)


# =========================================================
# PRODUCT SEARCH
# =========================================================

@products_bp.route("/search")
@login_required
def search():

    # =====================================================
    # Get search values
    # =====================================================

    keyword = request.args.get(
        "keyword",
        ""
    ).strip()

    budget = request.args.get(
        "budget",
        ""
    ).strip()

    colour = request.args.get(
        "colour",
        ""
    ).strip()

    size = request.args.get(
        "size",
        ""
    ).strip()

    store = request.args.get(
        "store",
        ""
    ).strip()

    location = request.args.get(
        "location",
        ""
    ).strip()

    max_shipping = request.args.get(
        "max_shipping",
        ""
    ).strip()

    max_distance = request.args.get(
        "max_distance",
        ""
    ).strip()

    user_latitude = request.args.get(
        "user_latitude",
        ""
    ).strip()

    user_longitude = request.args.get(
        "user_longitude",
        ""
    ).strip()

    sort = request.args.get(
        "sort",
        "price_asc"
    )

    # =====================================================
    # Start database query
    # =====================================================

    query = Product.query

    # =====================================================
    # Keyword filter
    # =====================================================

    if keyword:

        search_pattern = f"%{keyword}%"

        query = query.filter(
            db.or_(
                Product.name.ilike(search_pattern),
                Product.brand.ilike(search_pattern),
                Product.category.ilike(search_pattern),
                Product.description.ilike(search_pattern)
            )
        )

    # =====================================================
    # Budget filter
    # =====================================================

    if budget:

        try:

            budget_value = float(budget)

            query = query.filter(
                (
                    Product.price +
                    Product.shipping_cost
                ) <= budget_value
            )

        except ValueError:

            pass

    # =====================================================
    # Colour filter
    # =====================================================

    if colour:

        query = query.filter(
            Product.colour.ilike(
                f"%{colour}%"
            )
        )

    # =====================================================
    # Size filter
    # =====================================================

    if size:

        query = query.filter(
            Product.size.ilike(
                f"%{size}%"
            )
        )

    # =====================================================
    # Store filter
    # =====================================================

    if store:

        query = query.filter(
            Product.store.ilike(
                f"%{store}%"
            )
        )

    # =====================================================
    # Location filter
    # =====================================================

    if location:

        query = query.filter(
            Product.location.ilike(
                f"%{location}%"
            )
        )

    # =====================================================
    # Maximum shipping filter
    # =====================================================

    if max_shipping:

        try:

            shipping_value = float(
                max_shipping
            )

            query = query.filter(
                Product.shipping_cost <= shipping_value
            )

        except ValueError:

            pass

    # =====================================================
    # Database sorting
    # =====================================================

    if sort == "price_desc":

        query = query.order_by(
            Product.price.desc()
        )

    elif sort == "shipping_asc":

        query = query.order_by(
            Product.shipping_cost.asc()
        )

    elif sort == "name_asc":

        query = query.order_by(
            Product.name.asc()
        )

    else:

        query = query.order_by(
            Product.price.asc()
        )

    # =====================================================
    # Get products
    # =====================================================

    products = query.all()

    # =====================================================
    # Prepare distance calculation
    # =====================================================

    products_with_distance = []

    latitude = None
    longitude = None

    try:

        if user_latitude and user_longitude:

            latitude = float(
                user_latitude
            )

            longitude = float(
                user_longitude
            )

    except ValueError:

        latitude = None
        longitude = None

    # =====================================================
    # Calculate distances
    # =====================================================

    for product in products:

        distance = None

        if (
            latitude is not None
            and longitude is not None
            and product.latitude is not None
            and product.longitude is not None
        ):

            distance = calculate_distance(
                latitude,
                longitude,
                product.latitude,
                product.longitude
            )

        products_with_distance.append(
            {
                "product": product,
                "distance": distance
            }
        )

    # =====================================================
    # Maximum distance filter
    # =====================================================

    if max_distance:

        try:

            distance_value = float(
                max_distance
            )

            if (
                latitude is not None
                and longitude is not None
            ):

                products_with_distance = [
                    item
                    for item in products_with_distance
                    if (
                        item["distance"] is not None
                        and item["distance"] <= distance_value
                    )
                ]

        except ValueError:

            pass

    # =====================================================
    # Sort by distance
    # =====================================================

    if sort == "distance_asc":

        products_with_distance.sort(
            key=lambda item:
                item["distance"]
                if item["distance"] is not None
                else float("inf")
        )

    # =====================================================
    # Display search page
    # =====================================================

    return render_template(
        "products/search.html",

        products=products_with_distance,

        keyword=keyword,

        budget=budget,

        colour=colour,

        size=size,

        store=store,

        location=location,

        max_shipping=max_shipping,

        max_distance=max_distance,

        user_latitude=user_latitude,

        user_longitude=user_longitude,

        sort=sort
    )


# =========================================================
# PRODUCT DETAIL
# =========================================================

@products_bp.route("/<int:product_id>")
@login_required
def detail(product_id):

    product = Product.query.get_or_404(
        product_id
    )

    return render_template(
        "products/detail.html",
        product=product
    )