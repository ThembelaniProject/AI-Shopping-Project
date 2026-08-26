import math


# =========================================================
# Calculate distance between two coordinates
# =========================================================

def calculate_distance(
    latitude1,
    longitude1,
    latitude2,
    longitude2
):
    """
    Calculate the distance between two points
    on Earth using the Haversine formula.

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

    distance = earth_radius * c

    return distance