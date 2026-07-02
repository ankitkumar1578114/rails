import json
from typing import Any, Dict, List, Optional, Set, Tuple

from api.repos.db import db_connection
from api.repos.stations import (
    ensure_regions_stations_trains_loaded,
    fetch_station_coordinates_batch,
    fetch_station_regions_batch,
    get_combined_region_station_weights,
    get_region_stations_trains,
)
from api.repos.trains import (
    fetch_trains_by_numbers,
    intersect_regional_train_numbers,
    load_station_trains_pair,
    fetch_trains_by_query,
)
from api.utils.geo import geographic_distance_km
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
            if not train_runs_on_any_day(row):
                continue
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
            if (
                row
                and train_runs_on_any_day(row)
                and route_has_station_order(schedule, from_code, to_code)
            ):
                direct_trains.append(row)

        direct_train_number_set = {
            str(row.get("train_no") or row.get("train_number_string"))
            for row in direct_trains
            if row.get("train_no") or row.get("train_number_string")
        }

        station_coordinates: Dict[str, Tuple[float, float]] = (
            fetch_station_coordinates_batch([from_code, to_code], conn)
        )

        if (
            not from_region
            or not to_region
            or from_region == to_region
        ):
            return {
                "direct_trains": sort_direct_trains_by_scheduled_departure_time(
                    [
                        build_direct_train_response(
                            row,
                            parsed_schedules.get(
                                str(row.get("train_no") or row.get("train_number_string")),
                                [],
                            ),
                            from_code,
                            to_code,
                            from_region,
                            to_region,
                            station_coordinates,
                        )
                        for row in direct_trains
                    ],
                ),
                "alternative_trains": [],
            }

        from_region_code_set = {
            normalize_station_code(code) for code in from_region_data
        }
        to_region_code_set = {
            normalize_station_code(code) for code in to_region_data
        }
        station_weights = get_combined_region_station_weights(
            from_region, to_region, conn
        )

        alternative_trains: List[Dict[str, Any]] = []
        for train_no in candidate_train_numbers:
            if train_no in direct_train_number_set:
                continue

            row = train_rows_by_number.get(train_no)
            schedule = parsed_schedules.get(train_no, [])
            if not row or not train_runs_on_any_day(row):
                continue

            regional_match = find_regional_route_match(
                schedule,
                from_region_code_set,
                to_region_code_set,
                from_code,
                to_code,
                station_weights,
            )
            if not regional_match:
                continue

            from_stop, to_stop = regional_match
            from_stop_code = extract_station_code_from_route_item(from_stop)
            to_stop_code = extract_station_code_from_route_item(to_stop)
            needed_codes = [
                code
                for code in (from_stop_code, to_stop_code)
                if code and code not in station_coordinates
            ]
            if needed_codes:
                station_coordinates.update(
                    fetch_station_coordinates_batch(needed_codes, conn)
                )

            alternative_trains.append(
                enrich_alternative_train(
                    row,
                    from_stop,
                    to_stop,
                    from_region,
                    to_region,
                    schedule,
                    from_code,
                    to_code,
                    station_coordinates,
                )
            )

        return {
            "direct_trains": sort_direct_trains_by_scheduled_departure_time(
                [
                    build_direct_train_response(
                        row,
                        parsed_schedules.get(
                            str(row.get("train_no") or row.get("train_number_string")),
                            [],
                        ),
                        from_code,
                        to_code,
                        from_region,
                        to_region,
                        station_coordinates,
                    )
                    for row in direct_trains
                ],
            ),
            "alternative_trains": sort_alternative_trains_by_approx_distance(
                alternative_trains
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


def get_direct_train_departure_sort_key(train: Dict[str, Any]) -> Tuple[float, str]:
    from_station = train.get("from_station") or {}
    departure_minutes = parse_time_to_minutes(
        from_station.get("scheduled_departure_time")
    )
    train_no = str(train.get("train_no") or train.get("train_number_string") or "")
    if departure_minutes is None:
        return float("inf"), train_no

    return float(departure_minutes), train_no


def sort_direct_trains_by_scheduled_departure_time(
    trains: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return sorted(trains, key=get_direct_train_departure_sort_key)


def get_station_approx_distance(
    station_details: Optional[Dict[str, Any]],
) -> float:
    if not station_details:
        return 0.0
    approx_distance = station_details.get("approx_distance")
    if approx_distance is None:
        return float("inf")
    return float(approx_distance)


def get_alternative_train_total_approx_distance(train: Dict[str, Any]) -> float:
    from_station = train.get("from_station") or train.get("alternative_from_station")
    to_station = train.get("to_station") or train.get("alternative_to_station")
    return get_station_approx_distance(from_station) + get_station_approx_distance(
        to_station
    )


def sort_alternative_trains_by_approx_distance(
    trains: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return sorted(
        trains,
        key=lambda train: (
            get_alternative_train_total_approx_distance(train),
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
    distance_between_stations: Optional[float] = None,
    scheduled_travel_time: Optional[str] = None,
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
    if distance_between_stations is not None:
        response["distance_between_stations"] = distance_between_stations
    if scheduled_travel_time is not None:
        response["scheduled_travel_time"] = scheduled_travel_time
    return response


def build_station_coordinate_fields(
    station_code: Optional[str],
    station_coordinates: Optional[Dict[str, Tuple[float, float]]],
) -> Dict[str, float]:
    if not station_code or not station_coordinates:
        return {}
    coords = station_coordinates.get(station_code)
    if not coords:
        return {}
    lat, lon = coords
    return {"lat": lat, "lon": lon}


def build_direct_train_response(
    train_row: Dict[str, Any],
    schedule: List[Any],
    from_station: str,
    to_station: str,
    from_region: Optional[str] = None,
    to_region: Optional[str] = None,
    station_coordinates: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    from_stop, to_stop = get_route_stops_for_segment(schedule, from_station, to_station)
    journey_metrics = build_journey_segment_metrics(from_stop, to_stop)
    response = build_response_train_row(
        train_row,
        stops_between_stations=count_stops_between_stations(
            schedule, from_station, to_station
        ),
        distance_between_stations=journey_metrics.get("distance_between_stations"),
        scheduled_travel_time=journey_metrics.get("scheduled_travel_time"),
    )
    if from_stop:
        response["from_station"] = build_alternative_from_station_details(
            from_stop,
            from_region,
            approx_distance=0.0,
            station_coordinates=station_coordinates,
        )
    if to_stop:
        response["to_station"] = build_alternative_to_station_details(
            to_stop,
            to_region,
            approx_distance=0.0,
            station_coordinates=station_coordinates,
        )
    return response


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


def parse_time_to_minutes(time_value: Optional[str]) -> Optional[int]:
    if not time_value or time_value in ("SOURCE", "DESTINATION"):
        return None

    parts = str(time_value).strip().split(":")
    if len(parts) < 2:
        return None

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None

    if hours < 0 or minutes < 0 or minutes >= 60:
        return None

    return hours * 60 + minutes


def get_station_day_count(station: Dict[str, Any]) -> int:
    day_count = station.get("dayCount") or station.get("day_count") or 1
    try:
        return max(1, int(day_count))
    except (TypeError, ValueError):
        return 1


def parse_days_of_run(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def is_active_run_day(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "y", "yes"}
    return False


def train_runs_on_any_day(train_row: Dict[str, Any]) -> bool:
    days_of_run = parse_days_of_run(
        train_row.get("days_of_run") or train_row.get("DaysOfRun")
    )
    if not days_of_run:
        return False
    return any(is_active_run_day(day_value) for day_value in days_of_run.values())


def parse_distance_value(distance: Any) -> Optional[float]:
    if distance is None:
        return None
    if isinstance(distance, (int, float)):
        return float(distance)

    digits = "".join(ch for ch in str(distance) if ch.isdigit() or ch == ".")
    if not digits:
        return None

    try:
        return float(digits)
    except ValueError:
        return None


def get_station_distance(station: Dict[str, Any]) -> Optional[float]:
    for key in (
        "distance",
        "distance_from_origin",
        "origin_dst",
        "originDst",
        "distanceFromOrigin",
    ):
        parsed = parse_distance_value(station.get(key))
        if parsed is not None:
            return parsed
    return None


def format_travel_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def calculate_distance_between_stations(
    from_stop: Dict[str, Any], to_stop: Dict[str, Any]
) -> Optional[float]:
    from_distance = get_station_distance(from_stop)
    to_distance = get_station_distance(to_stop)
    if from_distance is None or to_distance is None:
        return None

    distance = to_distance - from_distance
    if distance < 0:
        return None
    return round(distance, 1)


def calculate_scheduled_travel_time(
    from_stop: Dict[str, Any], to_stop: Dict[str, Any]
) -> Optional[str]:
    departure_minutes = parse_time_to_minutes(get_scheduled_departure_time(from_stop))
    arrival_minutes = parse_time_to_minutes(get_scheduled_arrival_time(to_stop))
    if departure_minutes is None or arrival_minutes is None:
        return None

    from_day = get_station_day_count(from_stop)
    to_day = get_station_day_count(to_stop)
    day_diff = max(0, to_day - from_day)
    total_minutes = day_diff * 24 * 60 + arrival_minutes - departure_minutes

    if day_diff == 0 and arrival_minutes < departure_minutes:
        total_minutes += 24 * 60

    if total_minutes < 0:
        return None

    return format_travel_duration(total_minutes)


def build_journey_segment_metrics(
    from_stop: Optional[Dict[str, Any]],
    to_stop: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not from_stop or not to_stop:
        return {}

    metrics: Dict[str, Any] = {}
    distance = calculate_distance_between_stations(from_stop, to_stop)
    travel_time = calculate_scheduled_travel_time(from_stop, to_stop)

    if distance is not None:
        metrics["distance_between_stations"] = distance
    if travel_time is not None:
        metrics["scheduled_travel_time"] = travel_time
    return metrics


def get_route_stops_for_segment(
    route: List[Any], from_station: str, to_station: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    source_index, dest_index = find_station_order_indices(
        route, from_station, to_station
    )
    if source_index is None or dest_index is None:
        return None, None

    from_stop = route[source_index]
    to_stop = route[dest_index]
    if not isinstance(from_stop, dict) or not isinstance(to_stop, dict):
        return None, None

    return from_stop, to_stop


def build_alternative_to_station_details(
    station: Dict[str, Any],
    region: Optional[str],
    approx_distance: Optional[float] = None,
    station_coordinates: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    station_code = extract_station_code_from_route_item(station)
    details = {
        "station_code": station_code,
        "station_name": extract_station_name(station),
        "region": region,
        "scheduled_arrival_time": get_scheduled_arrival_time(station),
        "platform": station.get("platform"),
        "distance": get_station_distance(station),
        "day_count": station.get("dayCount") or station.get("day_count"),
        "scheduled_departure_time": get_scheduled_departure_time(station),
    }
    details.update(
        build_station_coordinate_fields(station_code, station_coordinates)
    )
    if approx_distance is not None:
        details["approx_distance"] = approx_distance
    return details


def build_alternative_from_station_details(
    station: Dict[str, Any],
    region: Optional[str],
    approx_distance: Optional[float] = None,
    station_coordinates: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    station_code = extract_station_code_from_route_item(station)
    details = {
        "station_code": station_code,
        "station_name": extract_station_name(station),
        "region": region,
        "scheduled_departure_time": get_scheduled_departure_time(station),
        "platform": station.get("platform"),
        "distance": get_station_distance(station),
        "day_count": station.get("dayCount") or station.get("day_count"),
    }
    details.update(
        build_station_coordinate_fields(station_code, station_coordinates)
    )
    if approx_distance is not None:
        details["approx_distance"] = approx_distance
    return details


def enrich_alternative_train(
    train_row: Dict[str, Any],
    from_stop: Dict[str, Any],
    to_stop: Dict[str, Any],
    from_region: Optional[str],
    to_region: Optional[str],
    schedule: List[Any],
    searched_from_station: str,
    searched_to_station: str,
    station_coordinates: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    from_stop_code = extract_station_code_from_route_item(from_stop)
    to_stop_code = extract_station_code_from_route_item(to_stop)
    searched_from_code = normalize_station_code(searched_from_station)
    searched_to_code = normalize_station_code(searched_to_station)
    coords = station_coordinates or {}
    journey_metrics = build_journey_segment_metrics(from_stop, to_stop)
    enriched = build_response_train_row(
        train_row,
        stops_between_stations=count_stops_between_stations(
            schedule, from_stop_code, to_stop_code
        )
        if from_stop_code and to_stop_code
        else None,
        distance_between_stations=journey_metrics.get("distance_between_stations"),
        scheduled_travel_time=journey_metrics.get("scheduled_travel_time"),
    )

    if from_stop_code != searched_from_code:
        from_approx_distance = geographic_distance_km(
            coords.get(searched_from_code),
            coords.get(from_stop_code),
        )
    else:
        from_approx_distance = 0.0

    if to_stop_code != searched_to_code:
        to_approx_distance = geographic_distance_km(
            coords.get(searched_to_code),
            coords.get(to_stop_code),
        )
    else:
        to_approx_distance = 0.0

    from_station_details = build_alternative_from_station_details(
        from_stop, from_region, from_approx_distance, coords
    )
    to_station_details = build_alternative_to_station_details(
        to_stop, to_region, to_approx_distance, coords
    )

    if from_stop_code == searched_from_code:
        enriched["from_station"] = from_station_details
    else:
        enriched["alternative_from_station"] = from_station_details

    if to_stop_code == searched_to_code:
        enriched["to_station"] = to_station_details
    else:
        enriched["alternative_to_station"] = to_station_details

    return enriched


def get_station_weight(
    station_code: Optional[str], station_weights: Dict[str, int]
) -> int:
    if not station_code:
        return 0
    return station_weights.get(station_code, 0)


def find_best_weight_region_station_in_range(
    route: List[Any],
    start_idx: int,
    end_idx: int,
    region_codes: Set[str],
    station_weights: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    best_station: Optional[Dict[str, Any]] = None
    best_weight = -1

    for idx in range(start_idx, end_idx):
        station = route[idx]
        if not isinstance(station, dict):
            continue
        code = extract_station_code_from_route_item(station)
        if code not in region_codes:
            continue
        weight = get_station_weight(code, station_weights)
        if weight > best_weight:
            best_weight = weight
            best_station = station

    return best_station


def find_regional_route_match(
    route: List[Any],
    from_region_codes: Set[str],
    to_region_codes: Set[str],
    preferred_from_station: Optional[str] = None,
    preferred_to_station: Optional[str] = None,
    station_weights: Optional[Dict[str, int]] = None,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if not route or not from_region_codes or not to_region_codes:
        return None

    weights = station_weights or {}
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
            to_station = find_best_weight_region_station_in_range(
                route,
                from_idx + 1,
                len(route),
                to_region_codes,
                weights,
            )
            if to_station:
                return station, to_station

    if preferred_to:
        for to_idx, station in enumerate(route):
            if not isinstance(station, dict):
                continue
            if extract_station_code_from_route_item(station) != preferred_to:
                continue
            from_station = find_best_weight_region_station_in_range(
                route,
                0,
                to_idx,
                from_region_codes,
                weights,
            )
            if from_station:
                return from_station, station

    best_match: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
    best_score = (-1, -1)

    for from_idx, station in enumerate(route):
        if not isinstance(station, dict):
            continue
        from_code = extract_station_code_from_route_item(station)
        if from_code not in from_region_codes:
            continue

        to_station = find_best_weight_region_station_in_range(
            route,
            from_idx + 1,
            len(route),
            to_region_codes,
            weights,
        )
        if not to_station:
            continue

        to_code = extract_station_code_from_route_item(to_station)
        score = (
            get_station_weight(to_code, weights),
            get_station_weight(from_code, weights),
        )
        if score > best_score:
            best_score = score
            best_match = (station, to_station)

    return best_match


def route_has_region_order(
    route: List[Any],
    from_region_codes: Set[str],
    to_region_codes: Set[str],
    station_weights: Optional[Dict[str, int]] = None,
) -> bool:
    return (
        find_regional_route_match(
            route,
            from_region_codes,
            to_region_codes,
            station_weights=station_weights,
        )
        is not None
    )
