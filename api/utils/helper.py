import json
from typing import Any, Dict, Optional


def getNonIntermediateStaionFromSchedule(schedule: Any, station_code: str) -> Optional[Dict
[str, Any]]:
    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule)
        except json.JSONDecodeError:
            return None

    if not isinstance(schedule, list):
        return None

    for item in schedule:
        if not isinstance(item, dict):
            continue

        code = item.get("station_code") or item.get("station_code")
        if code and code.strip().upper() == station_code.strip().upper():
            return item
    return None

def getStationFromSchedule(schedule: Any, station_code: str) -> Optional[Dict[str, Any]]:   
    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule)
        except json.JSONDecodeError:
            return None

    if not isinstance(schedule, list):
        return None

    for item in schedule:
        if not isinstance(item, dict):
            continue

        code = item.get("station_code") or item.get("stationCode") or item.get("StationCode")
        if code and code.strip().upper() == station_code.strip().upper():
            return item

        intermediate = item.get("intermediate_stations") or item.get("intermediateStations") or []
        for inter in intermediate:
            if isinstance(inter, dict):
                inter_code = inter.get("station_code") or inter.get("stationCode") or inter.get("StationCode")
                if inter_code and inter_code.strip().upper() == station_code.strip().upper():
                    return inter
    return None

def normalize_station_code(code: Any) -> Optional[str]:
    if code is None:
        return None
    return str(code).strip().upper()

def format_train_running_status(status: str) -> str:
    if(status =='at-station' or status == 'Arrived at' or status == 'Reached'):
        return "at-station"
    if(status == 'departed' or status == 'Departed'):
        return "departed"
    if(status == "Halted"):
        return "halted"
    if(status == "Scheduled"):
        return "scheduled"
    if(status == "TrainSchedule"):
        return "not-scheduled-today"

def compute_current_location(schedule: Any,provider_current_distance: Any, current_distance: Any,) -> Dict[str, Any]:
    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule)
        except json.JSONDecodeError:
            schedule = []
    main_source = "custom"
    if(provider_current_distance > current_distance ):
        current_distance = provider_current_distance
        main_source = "provider"

    if not isinstance(schedule, list):
        schedule = []

    def parse_distance(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit() or ch == ".")
            try:
                return float(digits) if digits else None
            except ValueError:
                return None
        return None

    try:
        current_distance_value = float(parse_distance(current_distance) or 0)
    except (TypeError, ValueError):
        return {
            "currentStation": None,
            "upcomingStation": None,
            "upcomingStationInKms": None,
        }
    

    stations = []
    for item in schedule:
        if not isinstance(item, dict):
            continue

        station_distance = item.get("distance_from_origin") or item.get("distance") or item.get("distanceFromOrigin")
        station_distance_value = parse_distance(station_distance)
        station_code = item.get("station_code") or item.get("stationCode") or item.get("StationCode")

        if station_distance_value is not None and station_code:
            stations.append({"code": station_code, "distance": station_distance_value})

        intermediate = item.get("intermediate_stations") or item.get("intermediateStations") or []
        for inter in intermediate:
            if isinstance(inter, dict):
                inter_distance = inter.get("distanceFromOrigin") or inter.get("distance")
                inter_distance_value = parse_distance(inter_distance)
                inter_code = inter.get("station_code") or inter.get("stationCode") or inter.get("StationCode")
                if inter_distance_value is not None and inter_code:
                    stations.append({"code": inter_code, "distance": inter_distance_value})


    current_station = None
    upcoming_station = None
    upcoming_kms = None
    upcoming_station_idx = 0

    for index, station in enumerate(stations):
        if station["distance"] > current_distance_value:
            upcoming_station = station["code"]
            upcoming_station_idx = index
            upcoming_kms = station["distance"] - current_distance_value
            if index > 0:
                current_station = stations[index - 1]["code"]
            break

    if current_station is None and stations:
        current_station = stations[len(stations) -1]["code"]

    if(current_distance == 0):
        return {
            "currentStation": stations[0]["code"] if stations else None,
            "upcomingStation": stations[1]["code"] if stations else None,
            "upcomingStationInKms": stations[1]["distance"] if stations else None,
            "main_source": main_source
        }

    running_status_overridden = False
    if upcoming_kms is not None:
        upcoming_kms = int(upcoming_kms)
        if upcoming_kms < 1:
            running_status_overridden = True
            current_station = upcoming_station
            upcoming_station = stations[upcoming_station_idx + 1]["code"] if upcoming_station_idx + 1 < len(stations) else None   
            upcoming_kms = int(stations[upcoming_station_idx + 1]["distance"] - current_distance_value) if upcoming_station_idx + 1 < len(stations) else None
    return {
        "currentStation": current_station,
        "upcomingStation": upcoming_station,
        "upcomingStationInKms": upcoming_kms if upcoming_kms is not None else 0,
        "main_source": main_source,
        "running_status_overridden": running_status_overridden
    }
