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

