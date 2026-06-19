from utils.helper import normalize_station_code
from repos.trains import fetch_trains_by_query, load_station_trains
from typing import Any, Dict, List
from repos.db import get_db_connection
from utils.json import parse_json_list


def fetchTrainsByNameOrNumber(query_value: str) -> List[Dict[str, Any]]:
    return fetch_trains_by_query(query_value.strip())

def fetch_trains_between(from_station: str, to_station: str) -> List[Dict[str, Any]]:
    from_trains = set(load_station_trains(from_station))
    to_trains = set(load_station_trains(to_station))
    common_trains = from_trains.intersection(to_trains)
    if not common_trains:
        return []

    placeholders = ",".join(["%s"] * len(common_trains))
    query = f"SELECT * FROM trains WHERE train_number_string IN ({placeholders})"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(common_trains))
            rows = cursor.fetchall()

    filtered_rows: List[Dict[str, Any]] = []
    for row in rows:
        schedule = parse_json_list(row.get("Schedule") or row.get("schedule"))
        if route_has_station_order(schedule, from_station, to_station):
            filtered_rows.append(row)

    return filtered_rows


def route_has_station_order(route: List[Any], from_station: str, to_station: str) -> bool:
    if not route:
        return False

    source_code = normalize_station_code(from_station)
    dest_code = normalize_station_code(to_station)
    if not source_code or not dest_code or source_code == dest_code:
        return False

    source_index = None
    dest_index = None

    for idx, station in enumerate(route):
        if isinstance(station, dict):
            code = (
                station.get("StationCode")
                or station.get("stationCode")
                or station.get("station_code")
                or station.get("code")
            )
        else:
            code = station
        normalized = normalize_station_code(code)
        if normalized == source_code and source_index is None:
            source_index = idx
        if normalized == dest_code and dest_index is None:
            dest_index = idx
        if source_index is not None and dest_index is not None:
            break

    return source_index is not None and dest_index is not None and source_index < dest_index

