import math
from typing import Any, Optional, Tuple

EARTH_RADIUS_KM = 6371.0


def parse_coordinate(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(EARTH_RADIUS_KM * c, 1)


def geographic_distance_km(
    point_a: Optional[Tuple[float, float]],
    point_b: Optional[Tuple[float, float]],
) -> Optional[float]:
    if not point_a or not point_b:
        return None

    lat1, lon1 = point_a
    lat2, lon2 = point_b
    if None in (lat1, lon1, lat2, lon2):
        return None

    return haversine_distance_km(lat1, lon1, lat2, lon2)
