from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

from api.repos.db import db_connection
from api.repos.stations import STATIONS_V2_TABLE
from api.utils.json import parse_json_string_list

TRAIN_DETAIL_COLUMNS = """
    train_no, train_number_string, train_name, train_type,
    source, destination, source_code, destination_code,
    days_of_run, classes, schedule, total_duration,
    total_distance, total_number_of_stops
"""

_train_details_cache: Dict[str, Dict[str, Any]] = {}


def fetch_trains_by_query(query_value: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM trains
        WHERE train_number_string LIKE %s
           OR train_name LIKE %s
        LIMIT 5
    """
    like_value = f"%{query_value}%"
    with db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value, like_value))
            return cursor.fetchall()
        

def load_station_trains(station_code: str) -> List[str]:
    with db_connection() as conn:
        trains_by_station = load_station_trains_batch([station_code], conn)
        return trains_by_station.get(station_code, [])


def load_station_trains_batch(
    station_codes: List[str],
    conn: Optional[mysql.connector.MySQLConnection] = None,
    table_name: str = "stations",
) -> Dict[str, List[str]]:
    if not station_codes:
        return {}

    unique_codes = list(dict.fromkeys(station_codes))
    placeholders = ",".join(["%s"] * len(unique_codes))
    query = f"""
        SELECT station_code, trains
        FROM {table_name}
        WHERE station_code IN ({placeholders})
    """

    def fetch_rows(connection: mysql.connector.MySQLConnection) -> List[Dict[str, Any]]:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(unique_codes))
            return cursor.fetchall()

    if conn is not None:
        rows = fetch_rows(conn)
    else:
        with db_connection() as owned_conn:
            rows = fetch_rows(owned_conn)

    trains_by_station = {code: [] for code in unique_codes}
    for row in rows:
        code = row.get("station_code")
        if code in trains_by_station:
            trains_by_station[code] = parse_json_string_list(row.get("trains"))

    return trains_by_station


def load_station_trains_pair(
    from_station: str,
    to_station: str,
    conn: mysql.connector.MySQLConnection,
) -> Tuple[List[str], List[str]]:
    trains_by_station = load_station_trains_batch([from_station, to_station], conn)
    return trains_by_station.get(from_station, []), trains_by_station.get(to_station, [])


def fetch_trains_by_numbers(
    train_numbers: List[str],
    conn: mysql.connector.MySQLConnection,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    if not train_numbers:
        return []

    unique_numbers = list(dict.fromkeys(train_numbers))
    if use_cache:
        missing_numbers = [
            train_no
            for train_no in unique_numbers
            if train_no not in _train_details_cache
        ]
    else:
        missing_numbers = unique_numbers

    if missing_numbers:
        placeholders = ",".join(["%s"] * len(missing_numbers))
        query = f"""
            SELECT {TRAIN_DETAIL_COLUMNS}
            FROM trains
            WHERE train_no IN ({placeholders})
        """
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(missing_numbers))
            for row in cursor.fetchall():
                train_no = str(row.get("train_no") or row.get("train_number_string"))
                if train_no:
                    _train_details_cache[train_no] = row

    if use_cache:
        return [
            _train_details_cache[train_no]
            for train_no in unique_numbers
            if train_no in _train_details_cache
        ]

    placeholders = ",".join(["%s"] * len(unique_numbers))
    query = f"""
        SELECT {TRAIN_DETAIL_COLUMNS}
        FROM trains
        WHERE train_no IN ({placeholders})
    """
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(query, tuple(unique_numbers))
        return cursor.fetchall()


def intersect_regional_train_numbers(
    from_region_data: Dict[str, Tuple[str, ...]],
    to_region_data: Dict[str, Tuple[str, ...]],
) -> List[str]:
    from_trains: set[str] = set()
    for trains in from_region_data.values():
        from_trains.update(trains)

    to_trains: set[str] = set()
    for trains in to_region_data.values():
        to_trains.update(trains)

    return sorted(from_trains.intersection(to_trains))


def load_regional_train_candidates(
    from_region_codes: List[str],
    to_region_codes: List[str],
    conn: mysql.connector.MySQLConnection,
) -> List[str]:
    all_codes = list(dict.fromkeys(from_region_codes + to_region_codes))
    trains_by_station = load_station_trains_batch(
        all_codes, conn, table_name=STATIONS_V2_TABLE
    )

    from_trains: set[str] = set()
    for code in from_region_codes:
        from_trains.update(trains_by_station.get(code, []))

    to_trains: set[str] = set()
    for code in to_region_codes:
        to_trains.update(trains_by_station.get(code, []))

    return sorted(from_trains.intersection(to_trains))
