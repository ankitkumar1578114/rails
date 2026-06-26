from typing import Any, Dict, List, Optional, Set, Tuple

from api.repos.db import db_connection
from api.repos.stations import (
    ensure_regions_stations_trains_loaded,
    fetch_station_regions_batch,
    get_region_stations_trains,
)
from api.repos.trains import (
    fetch_trains_by_numbers,
    intersect_regional_train_numbers,
    load_station_trains_pair,
    fetch_trains_by_query,
)
from api.utils.helper import normalize_station_code
from api.utils.json import parse_json_list


def fetchTrainsByNameOrNumber(query_value: str) -> List[Dict[str, Any]]:
    return fetch_trains_by_query(query_value.strip())


def fetch_trains_between(
    from_station: str,
    to_station: str,
    conn=None,
) -> List[Dict[str, Any]]:
    def _fetch(connection) -> List[Dict[str, Any]]:
        from_trains_list, to_trains_list = load_station_trains_pair(
            from_station, to_station, connection
        )
        common_trains = set(from_trains_list).intersection(to_trains_list)
        if not common_trains:
            return []

        rows = fetch_trains_by_numbers(sorted(common_trains), connection)
        filtered_rows: List[Dict[str, Any]] = []
        for row in rows:
            schedule = parse_json_list(row.get("Schedule") or row.get("schedule"))
            if route_has_station_order(schedule, from_station, to_station):
                filtered_rows.append(row)
        return filtered_rows

    if conn is not None:
        return _fetch(conn)

    with db_connection() as connection:
        return _fetch(connection)


def fetch_trains_between_with_alternatives(
    from_station: str, to_station: str
) -> Dict[str, List[Dict[str, Any]]]:
    from_code = normalize_station_code(from_station) or from_station
    to_code = normalize_station_code(to_station) or to_station

    with db_connection() as conn:
        regions_map = fetch_station_regions_batch([from_code, to_code], conn)
        from_region = regions_map.get(from_code)
        to_region = regions_map.get(to_code)

        if from_region and to_region:
            ensure_regions_stations_trains_loaded([from_region, to_region], conn)

        from_region_data = (
            get_region_stations_trains(from_region, conn) if from_region else {}
        )
        to_region_data = (
            get_region_stations_trains(to_region, conn) if to_region else {}
        )

        direct_train_numbers = sorted(
            set(from_region_data.get(from_code, ()))
            & set(to_region_data.get(to_code, ()))
        )
        candidate_train_numbers: List[str] = []
        if (
            from_region
            and to_region
            and from_region != to_region
        ):
            candidate_train_numbers = intersect_regional_train_numbers(
                from_region_data, to_region_data
            )

        all_needed_train_numbers = sorted(
            set(direct_train_numbers) | set(candidate_train_numbers)
        )

        train_rows_by_number: Dict[str, Dict[str, Any]] = {}
        parsed_schedules: Dict[str, List[Any]] = {}
        if all_needed_train_numbers:
            for row in fetch_trains_by_numbers(all_needed_train_numbers, conn):
                train_no = str(row.get("train_no") or row.get("train_number_string"))
                train_rows_by_number[train_no] = row
                parsed_schedules[train_no] = parse_json_list(
                    row.get("Schedule") or row.get("schedule")
                )

        direct_trains: List[Dict[str, Any]] = []
        for train_no in direct_train_numbers:
            row = train_rows_by_number.get(train_no)
            schedule = parsed_schedules.get(train_no, [])
            if row and route_has_station_order(schedule, from_code, to_code):
                direct_trains.append(row)

        direct_train_number_set = {
            str(row.get("train_no") or row.get("train_number_string"))
            for row in direct_trains
            if row.get("train_no") or row.get("train_number_string")
        }

        if (
            not from_region
            or not to_region
            or from_region == to_region
        ):
            return {
                "direct_trains": sort_trains_by_searched_origin(
                    [
                        build_direct_train_response(
                            row,
                            parsed_schedules.get(
                                str(row.get("train_no") or row.get("train_number_string")),
                                [],
                            ),
                            from_code,
                            to_code,
                        )
                        for row in direct_trains
                    ],
                    from_code,
                    parsed_schedules,
                ),
                "alternative_trains": [],
            }

        from_region_code_set = {
            normalize_station_code(code) for code in from_region_data
        }
        to_region_code_set = {
            normalize_station_code(code) for code in to_region_data
        }

        alternative_trains: List[Dict[str, Any]] = []
        for train_no in candidate_train_numbers:
            if train_no in direct_train_number_set:
                continue

            row = train_rows_by_number.get(train_no)
            schedule = parsed_schedules.get(train_no, [])
            if not row:
                continue

            regional_match = find_regional_route_match(
                schedule,
                from_region_code_set,
                to_region_code_set,
                from_code,
                to_code,
            )
            if not regional_match:
                continue

            from_stop, to_stop = regional_match
            alternative_trains.append(
                enrich_alternative_train(
                    row,
                    from_stop,
                    to_stop,
                    from_region,
                    to_region,
                    schedule,
                )
            )

        return {
            "direct_trains": sort_trains_by_searched_origin(
                [
                    build_direct_train_response(
                        row,
                        parsed_schedules.get(
                            str(row.get("train_no") or row.get("train_number_string")),
                            [],
                        ),
                        from_code,
                        to_code,
                    )
                    for row in direct_trains
                ],
                from_code,
                parsed_schedules,
            ),
            "alternative_trains": sort_trains_by_searched_origin(
                alternative_trains, from_code, parsed_schedules
            ),
        }


def extract_station_code_from_route_item(station: Any) -> Optional[str]:
    if isinstance(station, dict):
        code = (
            station.get("StationCode")
            or station.get("stationCode")
            or station.get("station_code")
            or station.get("code")
        )
    else:
        code = station
    return normalize_station_code(code)


def route_contains_station(route: List[Any], station_code: str) -> bool:
    normalized = normalize_station_code(station_code)
    if not normalized:
        return False

    for station in route:
        if extract_station_code_from_route_item(station) == normalized:
            return True
    return False


def train_origin_priority(
    train_row: Dict[str, Any],
    from_station: str,
    parsed_schedules: Optional[Dict[str, List[Any]]] = None,
) -> int:
    from_code = normalize_station_code(from_station)
    if not from_code:
        return 2

    source_code = normalize_station_code(
        train_row.get("source_code") or train_row.get("SourceCode")
    )
    if source_code == from_code:
        return 0

    train_no = str(train_row.get("train_no") or train_row.get("train_number_string") or "")
    if parsed_schedules and train_no in parsed_schedules:
        schedule = parsed_schedules[train_no]
    else:
        schedule = parse_json_list(train_row.get("schedule") or train_row.get("Schedule"))

    if route_contains_station(schedule, from_code):
        return 1

    return 2


def sort_trains_by_searched_origin(
    trains: List[Dict[str, Any]],
    from_station: str,
    parsed_schedules: Optional[Dict[str, List[Any]]] = None,
) -> List[Dict[str, Any]]:
    return sorted(
        trains,
        key=lambda train: (
            train_origin_priority(train, from_station, parsed_schedules),
            str(train.get("train_no") or train.get("train_number_string") or ""),
        ),
    )


def find_station_order_indices(
    route: List[Any], from_station: str, to_station: str
) -> Tuple[Optional[int], Optional[int]]:
    source_code = normalize_station_code(from_station)
    dest_code = normalize_station_code(to_station)
    if not source_code or not dest_code or source_code == dest_code:
        return None, None

    source_index = None
    dest_index = None

    for idx, station in enumerate(route):
        normalized = extract_station_code_from_route_item(station)
        if normalized == source_code and source_index is None:
            source_index = idx
        if normalized == dest_code and dest_index is None:
            dest_index = idx
        if source_index is not None and dest_index is not None:
            break

    if (
        source_index is None
        or dest_index is None
        or source_index >= dest_index
    ):
        return None, None

    return source_index, dest_index


def count_stops_between_stations(
    route: List[Any], from_station: str, to_station: str
) -> Optional[int]:
    source_index, dest_index = find_station_order_indices(
        route, from_station, to_station
    )
    if source_index is None or dest_index is None:
        return None
    return dest_index - source_index - 1


def route_has_station_order(route: List[Any], from_station: str, to_station: str) -> bool:
    source_index, dest_index = find_station_order_indices(
        route, from_station, to_station
    )
    return source_index is not None and dest_index is not None


def build_response_train_row(
    train_row: Dict[str, Any],
    stops_between_stations: Optional[int] = None,
) -> Dict[str, Any]:
    response = {
        "train_no": train_row.get("train_no"),
        "train_number_string": train_row.get("train_number_string"),
        "train_name": train_row.get("train_name"),
        "train_type": train_row.get("train_type"),
        "source": train_row.get("source"),
        "destination": train_row.get("destination"),
        "source_code": train_row.get("source_code"),
        "destination_code": train_row.get("destination_code"),
        "days_of_run": train_row.get("days_of_run"),
        "classes": train_row.get("classes"),
        "total_duration": train_row.get("total_duration"),
        "total_distance": train_row.get("total_distance"),
        "total_number_of_stops": train_row.get("total_number_of_stops"),
    }
    if stops_between_stations is not None:
        response["stops_between_stations"] = stops_between_stations
    return response


def build_direct_train_response(
    train_row: Dict[str, Any],
    schedule: List[Any],
    from_station: str,
    to_station: str,
) -> Dict[str, Any]:
    return build_response_train_row(
        train_row,
        stops_between_stations=count_stops_between_stations(
            schedule, from_station, to_station
        ),
    )


def extract_station_name(station: Any) -> Optional[str]:
    if not isinstance(station, dict):
        return None
    name = (
        station.get("stationName")
        or station.get("station_name")
        or station.get("StationName")
    )
    return str(name).strip() if name else None


def get_scheduled_departure_time(station: Dict[str, Any]) -> Optional[str]:
    value = (
        station.get("scheduledDepartureTime")
        or station.get("scheduled_departure_time")
        or station.get("departureTime")
        or station.get("departure_time")
    )
    if value in (None, "SOURCE", "DESTINATION"):
        return None
    return str(value).strip() if value else None


def get_scheduled_arrival_time(station: Dict[str, Any]) -> Optional[str]:
    value = (
        station.get("scheduledArrivalTime")
        or station.get("scheduled_arrival_time")
        or station.get("arrivalTime")
        or station.get("arrival_time")
    )
    if value in (None, "DESTINATION"):
        return None
    return str(value).strip() if value else None


def build_alternative_to_station_details(
    station: Dict[str, Any], region: Optional[str]
) -> Dict[str, Any]:
    return {
        "station_code": extract_station_code_from_route_item(station),
        "station_name": extract_station_name(station),
        "region": region,
        "scheduled_arrival_time": get_scheduled_arrival_time(station),
        "platform": station.get("platform"),
        "distance": station.get("distance")
        if station.get("distance") is not None
        else station.get("distance_from_origin"),
        "day_count": station.get("dayCount") or station.get("day_count"),
        "scheduled_departure_time": get_scheduled_departure_time(station),
    }


def build_alternative_from_station_details(
    station: Dict[str, Any], region: Optional[str]
) -> Dict[str, Any]:
    return {
        "station_code": extract_station_code_from_route_item(station),
        "station_name": extract_station_name(station),
        "region": region,
        "scheduled_departure_time": get_scheduled_departure_time(station),
        "platform": station.get("platform"),
        "distance": station.get("distance")
        if station.get("distance") is not None
        else station.get("distance_from_origin"),
        "day_count": station.get("dayCount") or station.get("day_count"),
    }


def enrich_alternative_train(
    train_row: Dict[str, Any],
    from_stop: Dict[str, Any],
    to_stop: Dict[str, Any],
    from_region: Optional[str],
    to_region: Optional[str],
    schedule: List[Any],
) -> Dict[str, Any]:
    from_stop_code = extract_station_code_from_route_item(from_stop)
    to_stop_code = extract_station_code_from_route_item(to_stop)
    enriched = build_response_train_row(
        train_row,
        stops_between_stations=count_stops_between_stations(
            schedule, from_stop_code, to_stop_code
        )
        if from_stop_code and to_stop_code
        else None,
    )
    enriched["alternative_from_station"] = build_alternative_from_station_details(
        from_stop, from_region
    )
    enriched["alternative_to_station"] = build_alternative_to_station_details(
        to_stop, to_region
    )
    return enriched


def find_last_region_station_after(
    route: List[Any],
    start_idx: int,
    region_codes: Set[str],
) -> Optional[Dict[str, Any]]:
    last_match: Optional[Dict[str, Any]] = None
    for idx in range(start_idx + 1, len(route)):
        station = route[idx]
        if not isinstance(station, dict):
            continue
        if extract_station_code_from_route_item(station) in region_codes:
            last_match = station
    return last_match


def find_regional_route_match(
    route: List[Any],
    from_region_codes: Set[str],
    to_region_codes: Set[str],
    preferred_from_station: Optional[str] = None,
    preferred_to_station: Optional[str] = None,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if not route or not from_region_codes or not to_region_codes:
        return None

    preferred_from = normalize_station_code(preferred_from_station)
    preferred_to = normalize_station_code(preferred_to_station)

    if preferred_from and preferred_to:
        from_stop: Optional[Dict[str, Any]] = None
        from_idx: Optional[int] = None
        for idx, station in enumerate(route):
            if not isinstance(station, dict):
                continue
            code = extract_station_code_from_route_item(station)
            if code == preferred_from and from_idx is None:
                from_idx = idx
                from_stop = station
            if (
                from_idx is not None
                and code == preferred_to
                and idx > from_idx
                and isinstance(station, dict)
            ):
                return from_stop, station

    if preferred_from:
        for from_idx, station in enumerate(route):
            if not isinstance(station, dict):
                continue
            if extract_station_code_from_route_item(station) != preferred_from:
                continue
            if preferred_to:
                for to_idx in range(from_idx + 1, len(route)):
                    to_station = route[to_idx]
                    if not isinstance(to_station, dict):
                        continue
                    if extract_station_code_from_route_item(to_station) == preferred_to:
                        return station, to_station
            to_station = find_last_region_station_after(
                route, from_idx, to_region_codes
            )
            if to_station:
                return station, to_station

    if preferred_to:
        for from_idx, station in enumerate(route):
            if not isinstance(station, dict):
                continue
            if extract_station_code_from_route_item(station) not in from_region_codes:
                continue
            for to_idx in range(from_idx + 1, len(route)):
                to_station = route[to_idx]
                if not isinstance(to_station, dict):
                    continue
                if extract_station_code_from_route_item(to_station) == preferred_to:
                    return station, to_station

    for from_idx, station in enumerate(route):
        if not isinstance(station, dict):
            continue
        if extract_station_code_from_route_item(station) not in from_region_codes:
            continue
        to_station = find_last_region_station_after(route, from_idx, to_region_codes)
        if to_station:
            return station, to_station

    return None


def route_has_region_order(
    route: List[Any],
    from_region_codes: Set[str],
    to_region_codes: Set[str],
) -> bool:
    return (
        find_regional_route_match(route, from_region_codes, to_region_codes)
        is not None
    )
