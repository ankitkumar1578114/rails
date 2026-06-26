from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

from api.repos.db import db_connection
from api.utils.json import parse_json_string_list

STATIONS_V2_TABLE = "stationsV2"
_region_stations_trains_cache: Dict[str, Dict[str, Tuple[str, ...]]] = {}
_region_station_weights_cache: Dict[str, Dict[str, int]] = {}
_station_region_cache: Dict[str, str] = {}


def fetch_stations_by_name(name: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_name LIKE %s
        ORDER BY weight DESC
    """
    like_value = f"%{name}%"
    with db_connection() as conn:
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
    with db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()


def fetch_station_region(
    station_code: str,
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> Optional[str]:
    query = f"""
        SELECT region
        FROM {STATIONS_V2_TABLE}
        WHERE station_code = %s
        LIMIT 1
    """

    def fetch_row(connection: mysql.connector.MySQLConnection) -> Optional[str]:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(query, (station_code,))
            row = cursor.fetchone()
            if not row:
                return None
            region = row.get("region")
            return str(region).strip() if region else None

    if conn is not None:
        return fetch_row(conn)
    with db_connection() as owned_conn:
        return fetch_row(owned_conn)


def fetch_station_codes_by_region(
    region: str,
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> List[str]:
    query = f"""
        SELECT station_code
        FROM {STATIONS_V2_TABLE}
        WHERE region = %s
          AND JSON_LENGTH(trains) > 0
    """

    def fetch_rows(connection: mysql.connector.MySQLConnection) -> List[str]:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(query, (region,))
            rows = cursor.fetchall()
            return [row["station_code"] for row in rows if row.get("station_code")]

    if conn is not None:
        return fetch_rows(conn)
    with db_connection() as owned_conn:
        return fetch_rows(owned_conn)


def fetch_station_regions_batch(
    station_codes: List[str],
    conn: mysql.connector.MySQLConnection,
) -> Dict[str, str]:
    if not station_codes:
        return {}

    unique_codes = list(dict.fromkeys(station_codes))
    regions_by_station = {
        code: _station_region_cache[code]
        for code in unique_codes
        if code in _station_region_cache
    }
    missing_codes = [code for code in unique_codes if code not in regions_by_station]
    if not missing_codes:
        return regions_by_station

    placeholders = ",".join(["%s"] * len(missing_codes))
    query = f"""
        SELECT station_code, region
        FROM {STATIONS_V2_TABLE}
        WHERE station_code IN ({placeholders})
    """
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(query, tuple(missing_codes))
        for row in cursor.fetchall():
            code = row.get("station_code")
            region = row.get("region")
            if code and region:
                region_value = str(region).strip()
                regions_by_station[code] = region_value
                _station_region_cache[code] = region_value
    return regions_by_station


def _parse_region_stations_trains_rows(
    rows: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Tuple[str, ...]]], Dict[str, Dict[str, int]]]:
    regions_data: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    weights_data: Dict[str, Dict[str, int]] = {}
    for row in rows:
        region = row.get("region")
        code = row.get("station_code")
        if not region or not code:
            continue
        region_key = str(region).strip()
        trains = tuple(parse_json_string_list(row.get("trains")))
        regions_data.setdefault(region_key, {})[code] = trains
        weight_value = row.get("weight")
        weights_data.setdefault(region_key, {})[code] = (
            int(weight_value) if weight_value is not None else 0
        )
    return regions_data, weights_data


def ensure_regions_stations_trains_loaded(
    regions: List[str],
    conn: mysql.connector.MySQLConnection,
) -> None:
    missing_regions = [region for region in regions if region not in _region_stations_trains_cache]
    if not missing_regions:
        return

    placeholders = ",".join(["%s"] * len(missing_regions))
    query = f"""
        SELECT region, station_code, trains, weight
        FROM {STATIONS_V2_TABLE}
        WHERE region IN ({placeholders})
          AND JSON_LENGTH(trains) > 0
    """
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(query, tuple(missing_regions))
        rows = cursor.fetchall()

    loaded_regions, loaded_weights = _parse_region_stations_trains_rows(rows)
    for region in missing_regions:
        _region_stations_trains_cache[region] = loaded_regions.get(region, {})
        _region_station_weights_cache[region] = loaded_weights.get(region, {})


def get_region_station_weights(
    region: str,
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> Dict[str, int]:
    if region in _region_station_weights_cache:
        return _region_station_weights_cache[region]

    if conn is not None:
        ensure_regions_stations_trains_loaded([region], conn)
        return _region_station_weights_cache.get(region, {})

    with db_connection() as owned_conn:
        ensure_regions_stations_trains_loaded([region], owned_conn)
        return _region_station_weights_cache.get(region, {})


def get_combined_region_station_weights(
    from_region: Optional[str],
    to_region: Optional[str],
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> Dict[str, int]:
    weights: Dict[str, int] = {}
    if from_region:
        weights.update(get_region_station_weights(from_region, conn))
    if to_region:
        weights.update(get_region_station_weights(to_region, conn))
    return weights


def get_region_stations_trains(
    region: str,
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> Dict[str, Tuple[str, ...]]:
    if region in _region_stations_trains_cache:
        return _region_stations_trains_cache[region]

    if conn is not None:
        ensure_regions_stations_trains_loaded([region], conn)
        return _region_stations_trains_cache.get(region, {})

    with db_connection() as owned_conn:
        ensure_regions_stations_trains_loaded([region], owned_conn)
        return _region_stations_trains_cache.get(region, {})

