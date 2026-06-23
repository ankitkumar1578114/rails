from api.repos.db import get_db_connection
from typing import Any, Dict, List, Optional


def normalize_lookup_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def fetch_stations_by_name(name: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_name LIKE %s
        ORDER BY weight DESC
    """
    like_value = f"%{name}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()
        
def fetch_stations_by_code(code: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_code LIKE %s
        ORDER By weight desc

    """
    like_value = f"%{code}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()


def fetch_station_region(station_code: str) -> Optional[str]:
    normalized_code = normalize_lookup_code(station_code)
    if not normalized_code:
        return None

    query = """
        SELECT *
        FROM stationsV2
        WHERE UPPER(TRIM(station_code)) = %s
        LIMIT 1
    """
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (normalized_code,))
            row = cursor.fetchone()
            if not row:
                return None

            for key in ("region", "region_code", "Region", "RegionCode"):
                value = row.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip().upper()
    return None

