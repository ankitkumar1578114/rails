from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

from api.repos.db import get_db_connection
from api.utils.json import parse_json_string_list


def fetch_trains_by_query(query_value: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM trains
        WHERE train_number_string LIKE %s
           OR train_name LIKE %s
        LIMIT 5
    """
    like_value = f"%{query_value}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value, like_value))
            return cursor.fetchall()
        

def load_station_trains(station_code: str) -> List[str]:
    with get_db_connection() as conn:
        trains_by_station = load_station_trains_batch([station_code], conn)
        return trains_by_station.get(station_code, [])


def load_station_trains_batch(
    station_codes: List[str],
    conn: Optional[mysql.connector.MySQLConnection] = None,
) -> Dict[str, List[str]]:
    if not station_codes:
        return {}

    unique_codes = list(dict.fromkeys(station_codes))
    placeholders = ",".join(["%s"] * len(unique_codes))
    query = f"""
        SELECT station_code, trains
        FROM stations
        WHERE station_code IN ({placeholders})
    """

    def fetch_rows(connection: mysql.connector.MySQLConnection) -> List[Dict[str, Any]]:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(unique_codes))
            return cursor.fetchall()

    if conn is not None:
        rows = fetch_rows(conn)
    else:
        with get_db_connection() as owned_conn:
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
