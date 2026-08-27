import math


# =========================================================
# DISTANCE CALCULATOR
# =========================================================

def calculate_distance(
    latitude1,
    longitude1,
    latitude2,
    longitude2
):
    """
    Calculate the distance between two coordinates
    using the Haversine formula.

    Returns distance in kilometres.
    """

    earth_radius = 6371.0

    lat1 = math.radians(latitude1)
    lat2 = math.radians(latitude2)

    difference_latitude = math.radians(
        latitude2 - latitude1
    )

    difference_longitude = math.radians(
        longitude2 - longitude1
    )

    a = (
        math.sin(difference_latitude / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(difference_longitude / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return earth_radius * c


# =========================================================
# TEXT MATCHING
# =========================================================

def text_matches(
    search_text,
    product_text
):
    """
    Check whether the search text matches
    the product information.
    """

    if not search_text:
        return False

    if not product_text:
        return False

    search_text = search_text.lower().strip()

    product_text = product_text.lower().strip()

    return search_text in product_text


# =========================================================
# AI RECOMMENDATION SCORE
# =========================================================

def calculate_recommendation_score(
    product,
    keyword="",
    budget=None,
    colour="",
    size="",
    store="",
    user_preferences=None,
    distance=None
):
    """
    Calculate a recommendation score from 0 to 100.

    Higher score = better recommendation.
    """

    score = 0.0

    # -----------------------------------------------------
    # Keyword match
    # -----------------------------------------------------

    if keyword:

        keyword = keyword.lower().strip()

        product_information = " ".join([
            str(product.name or ""),
            str(product.brand or ""),
            str(product.category or ""),
            str(product.description or "")
        ]).lower()

        if keyword in product_information:

            score += 25

    # -----------------------------------------------------
    # Budget
    # -----------------------------------------------------

    if budget is not None:

        try:

            budget = float(budget)

            total_cost = float(
                product.price +
                product.shipping_cost
            )

            if total_cost <= budget:

                score += 20

                # Extra points when comfortably
                # inside the budget.

                if budget > 0:

                    percentage = (
                        total_cost / budget
                    )

                    if percentage <= 0.70:

                        score += 5

        except (
            ValueError,
            TypeError
        ):

            pass

    # -----------------------------------------------------
    # Colour
    # -----------------------------------------------------

    if colour:

        if text_matches(
            colour,
            product.colour
        ):

            score += 10

    # -----------------------------------------------------
    # Size
    # -----------------------------------------------------

    if size:

        if text_matches(
            size,
            product.size
        ):

            score += 10

    # -----------------------------------------------------
    # Store
    # -----------------------------------------------------

    if store:

        if text_matches(
            store,
            product.store
        ):

            score += 5

    # -----------------------------------------------------
    # Shipping
    # -----------------------------------------------------

    shipping_cost = float(
        product.shipping_cost or 0
    )

    if shipping_cost <= 100:

        score += 5

    elif shipping_cost <= 250:

        score += 3

    # -----------------------------------------------------
    # Distance
    # -----------------------------------------------------

    if distance is not None:

        if distance <= 5:

            score += 10

        elif distance <= 10:

            score += 8

        elif distance <= 25:

            score += 5

        elif distance <= 50:

            score += 2

    # -----------------------------------------------------
    # User preferences
    # -----------------------------------------------------

    if user_preferences:

        preferred_styles = (
            user_preferences.get(
                "styles",
                ""
            )
        )

        preferred_colours = (
            user_preferences.get(
                "colours",
                ""
            )
        )

        preferred_stores = (
            user_preferences.get(
                "stores",
                ""
            )
        )

        hobbies = (
            user_preferences.get(
                "hobbies",
                ""
            )
        )

        # Style

        if preferred_styles:

            if text_matches(
                preferred_styles,
                product.category
            ):

                score += 5

        # Colour preference

        if preferred_colours:

            if text_matches(
                preferred_colours,
                product.colour
            ):

                score += 5

        # Store preference

        if preferred_stores:

            if text_matches(
                preferred_stores,
                product.store
            ):

                score += 3

        # Hobby / interest

        if hobbies:

            product_information = " ".join([
                str(product.name or ""),
                str(product.category or ""),
                str(product.description or "")
            ])

            if text_matches(
                hobbies,
                product_information
            ):

                score += 2

    # -----------------------------------------------------
    # Stock availability
    # -----------------------------------------------------

    if product.stock is not None:

        if product.stock > 0:

            score += 5

    # -----------------------------------------------------
    # Maximum score
    # -----------------------------------------------------

    if score > 100:

        score = 100

    return round(
        score,
        2
    )