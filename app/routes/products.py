from flask import Blueprint, render_template, request
from flask_login import (
    login_required,
    current_user
)

from app import db

from app.models import (
    Product,
    Preference
)

from app.services.recommender import (
    calculate_distance,
    calculate_recommendation_score
)


# =========================================================
# PRODUCTS BLUEPRINT
# =========================================================

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
    # GET SEARCH VALUES
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
    ).strip()

    # =====================================================
    # START DATABASE QUERY
    # =====================================================

    query = Product.query

    # =====================================================
    # KEYWORD FILTER
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
    # BUDGET FILTER
    # =====================================================

    if budget:

        try:

            budget_filter = float(
                budget
            )

            query = query.filter(
                (
                    Product.price +
                    Product.shipping_cost
                ) <= budget_filter
            )

        except ValueError:

            pass

    # =====================================================
    # COLOUR FILTER
    # =====================================================

    if colour:

        query = query.filter(
            Product.colour.ilike(
                f"%{colour}%"
            )
        )

    # =====================================================
    # SIZE FILTER
    # =====================================================

    if size:

        query = query.filter(
            Product.size.ilike(
                f"%{size}%"
            )
        )

    # =====================================================
    # STORE FILTER
    # =====================================================

    if store:

        query = query.filter(
            Product.store.ilike(
                f"%{store}%"
            )
        )

    # =====================================================
    # LOCATION FILTER
    # =====================================================

    if location:

        query = query.filter(
            Product.location.ilike(
                f"%{location}%"
            )
        )

    # =====================================================
    # MAXIMUM SHIPPING FILTER
    # =====================================================

    if max_shipping:

        try:

            shipping_filter = float(
                max_shipping
            )

            query = query.filter(
                Product.shipping_cost
                <= shipping_filter
            )

        except ValueError:

            pass

    # =====================================================
    # DATABASE SORTING
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
    # GET PRODUCTS
    # =====================================================

    products = query.all()

    # =====================================================
    # PREPARE DISTANCE CALCULATION
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
    # CALCULATE PRODUCT DISTANCES
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
    # MAXIMUM DISTANCE FILTER
    # =====================================================

    if max_distance:

        try:

            distance_filter = float(
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
                        and item["distance"]
                        <= distance_filter
                    )
                ]

        except ValueError:

            pass

    # =====================================================
    # SORT BY DISTANCE
    # =====================================================

    if sort == "distance_asc":

        products_with_distance.sort(
            key=lambda item:
                item["distance"]
                if item["distance"] is not None
                else float("inf")
        )

    # =====================================================
    # PREPARE BUDGET FOR AI
    # =====================================================

    recommendation_budget = None

    if budget:

        try:

            recommendation_budget = float(
                budget
            )

        except ValueError:

            recommendation_budget = None

    # =====================================================
    # GET USER PREFERENCES
    # =====================================================

    preference = Preference.query.filter_by(
        user_id=current_user.id
    ).first()

    user_preferences = None

    if preference:

        user_preferences = {

            "styles": (
                preference.styles
                if preference.styles
                else ""
            ),

            "colours": (
                preference.colours
                if preference.colours
                else ""
            ),

            "stores": (
                preference.stores
                if preference.stores
                else ""
            ),

            "hobbies": (
                preference.hobbies
                if preference.hobbies
                else ""
            )

        }

    # =====================================================
    # CALCULATE AI RECOMMENDATION SCORE
    # =====================================================

    for item in products_with_distance:

        product = item["product"]

        distance = item["distance"]

        recommendation_score = (
            calculate_recommendation_score(

                product=product,

                keyword=keyword,

                budget=recommendation_budget,

                colour=colour,

                size=size,

                store=store,

                user_preferences=user_preferences,

                distance=distance

            )
        )

        item["recommendation_score"] = (
            recommendation_score
        )

    # =====================================================
    # SORT BY AI RECOMMENDATION
    # =====================================================

    if sort == "recommendation":

        products_with_distance.sort(
            key=lambda item:
                item["recommendation_score"],
            reverse=True
        )

    # =====================================================
    # DISPLAY SEARCH PAGE
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

@products_bp.route(
    "/<int:product_id>"
)
@login_required
def detail(product_id):

    product = Product.query.get_or_404(
        product_id
    )

    return render_template(

        "products/detail.html",

        product=product

    )