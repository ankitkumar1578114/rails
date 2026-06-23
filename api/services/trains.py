from api.repos.stations import fetch_station_region
from api.repos.trains import fetch_trains_by_query, load_region_trains, load_station_trains
from api.utils.helper import normalize_station_code
from api.utils.json import parse_json_list
from api.repos.db import get_db_connection
from typing import Any, Dict, List, Optional, Tuple


def fetchTrainsByNameOrNumber(query_value: str) -> List[Dict[str, Any]]:
    return fetch_trains_by_query(query_value.strip())


def fetch_trains_between(from_station: str, to_station: str) -> List[Dict[str, Any]]:
    _, rows = fetch_matching_train_rows(from_station, to_station)
    return rows


def fetch_trains_between_v2(from_station: str, to_station: str) -> Dict[str, Any]:
    search_meta, rows = fetch_matching_train_rows(from_station, to_station)
    from_code = search_meta["from_station"]
    to_code = search_meta["to_station"]

    exact_match_trains: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in rows:
        origin_code, destination_code, origin_name, destination_name = get_train_endpoints(row)

        if origin_code == from_code and destination_code == to_code:
            exact_match_trains.append(row)
            continue

        group_key = (origin_code or "", destination_code or "")
        if group_key not in grouped:
            grouped[group_key] = {
                "origin_code": origin_code,
                "origin_name": origin_name,
                "destination_code": destination_code,
                "destination_name": destination_name,
                "trains": [],
            }
        grouped[group_key]["trains"].append(row)

    route_groups = sorted(
        grouped.values(),
        key=lambda group: (
            group["origin_code"] or "",
            group["destination_code"] or "",
        ),
    )

    return {
        "search": search_meta,
        "exact_match": {
            "origin_code": from_code,
            "destination_code": to_code,
            "count": len(exact_match_trains),
            "trains": exact_match_trains,
        },
        "other_routes": [
            {
                **group,
                "count": len(group["trains"]),
            }
            for group in route_groups
        ],
        "total": len(rows),
    }


def fetch_matching_train_rows(
    from_station: str,
    to_station: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from_code = normalize_station_code(from_station)
    to_code = normalize_station_code(to_station)
    search_meta = {
        "from_station": from_code,
        "to_station": to_code,
        "from_region": None,
        "to_region": None,
    }

    if not from_code or not to_code or from_code == to_code:
        return search_meta, []

    from_region = fetch_station_region(from_code)
    to_region = fetch_station_region(to_code)
    search_meta["from_region"] = from_region
    search_meta["to_region"] = to_region

    if not from_region or not to_region:
        return search_meta, []

    station_common = set(load_station_trains(from_code)) & set(load_station_trains(to_code))
    region_common = set(load_region_trains(from_region)) & set(load_region_trains(to_region))
    common_trains = station_common if station_common else region_common
    if not common_trains:
        return search_meta, []

    placeholders = ",".join(["%s"] * len(common_trains))
    query = f"SELECT * FROM trains WHERE train_number_string IN ({placeholders})"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(common_trains))
            rows = cursor.fetchall()

    filtered_rows: List[Dict[str, Any]] = []
    for row in rows:
        schedule = parse_json_list(row.get("Schedule") or row.get("schedule"))
        if route_has_correct_direction(
            schedule,
            from_code,
            to_code,
            from_region,
            to_region,
        ):
            filtered_rows.append(row)

    return search_meta, filtered_rows


def get_train_endpoints(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    origin_code = normalize_station_code(
        row.get("source_code")
        or row.get("SourceCode")
        or row.get("src_stn_code")
        or row.get("from_station_code")
    )
    destination_code = normalize_station_code(
        row.get("destination_code")
        or row.get("DestinationCode")
        or row.get("dstn_stn_code")
        or row.get("to_station_code")
    )
    origin_name = (
        row.get("source")
        or row.get("Source")
        or row.get("src_stn_name")
        or row.get("from_station_name")
    )
    destination_name = (
        row.get("destination")
        or row.get("Destination")
        or row.get("dstn_stn_name")
        or row.get("to_station_name")
    )

    if not origin_code or not destination_code:
        schedule = parse_json_list(row.get("Schedule") or row.get("schedule"))
        stops = extract_route_stops(schedule)
        if stops:
            if not origin_code:
                origin_code = stops[0]["station_code"]
            if not destination_code:
                destination_code = stops[-1]["station_code"]

    return origin_code, destination_code, origin_name, destination_name


def get_region_code(station: Dict[str, Any]) -> Optional[str]:
    for key in ("region_code", "regionCode", "RegionCode", "region"):
        value = station.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().upper()
    return None


def extract_route_stops(route: List[Any]) -> List[Dict[str, Optional[str]]]:
    stops: List[Dict[str, Optional[str]]] = []

    for item in route:
        if not isinstance(item, dict):
            continue

        code = normalize_station_code(
            item.get("station_code")
            or item.get("stationCode")
            or item.get("StationCode")
            or item.get("code")
        )
        region = get_region_code(item)
        if code or region:
            stops.append({"station_code": code, "region_code": region})

        intermediate = (
            item.get("intermediate_stations")
            or item.get("intermediateStations")
            or item.get("intermediateStationsList")
            or []
        )
        if not isinstance(intermediate, list):
            continue

        for nested in intermediate:
            if not isinstance(nested, dict):
                continue
            nested_code = normalize_station_code(
                nested.get("station_code")
                or nested.get("stationCode")
                or nested.get("StationCode")
                or nested.get("code")
            )
            nested_region = get_region_code(nested)
            if nested_code or nested_region:
                stops.append(
                    {"station_code": nested_code, "region_code": nested_region}
                )

    return stops


def route_has_correct_direction(
    route: List[Any],
    from_station: str,
    to_station: str,
    from_region: str,
    to_region: str,
) -> bool:
    if not route:
        return False

    from_station_code = normalize_station_code(from_station)
    to_station_code = normalize_station_code(to_station)
    from_region_code = normalize_station_code(from_region)
    to_region_code = normalize_station_code(to_region)
    if (
        not from_station_code
        or not to_station_code
        or not from_region_code
        or not to_region_code
    ):
        return False

    stops = extract_route_stops(route)
    if not stops:
        return False

    from_station_idx = None
    to_station_idx = None
    for idx, stop in enumerate(stops):
        if from_station_idx is None and stop["station_code"] == from_station_code:
            from_station_idx = idx
        if stop["station_code"] == to_station_code:
            to_station_idx = idx

    if from_station_idx is not None and to_station_idx is not None:
        return from_station_idx < to_station_idx

    from_region_idx = None
    to_region_idx = None
    for idx, stop in enumerate(stops):
        if from_region_idx is None and stop["region_code"] == from_region_code:
            from_region_idx = idx
        if stop["region_code"] == to_region_code:
            to_region_idx = idx

    return (
        from_region_idx is not None
        and to_region_idx is not None
        and from_region_idx < to_region_idx
    )
