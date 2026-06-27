import os
import requests
from datetime import datetime
from typing import Any, Dict, Optional
from api.utils.helper import format_train_running_status

DEFAULT_WHEREISMYTRAIN2_BASE_URL = (
    "https://2fe4m4jegh2fuhgkk3u7v4sqv40qpago.lambda-url.ap-south-1.on.aws/trains"
)


def convert_date(date_str: Optional[str]) -> str:
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    return datetime.strptime(date_str.strip(), "%d-%m-%Y").strftime("%Y-%m-%d")


def _format_date_for_api(date_value: Optional[str]) -> str:
    if date_value:
        return date_value.strip()
    return datetime.now().strftime("%d-%m-%Y")


def fetch_whereismytrain_status(train_no: str, date_value: Optional[str]) -> Dict[str, Any]:
    api_url = "https://whereismytrain.in/cache/live_status"
    params = {
        "train_no": train_no,
        "lang": "en",
        "date": _format_date_for_api(date_value),
        "appVersion": "6.7.5",
        "from_day": "1",
    }
    response = requests.get(api_url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()

def fetch_whereismytrain2_status(train_no: str, date_value: Optional[str]) -> Dict[str, Any]:
    try:
        base_url = os.environ.get("WHEREISMYTRAIN2_URL", DEFAULT_WHEREISMYTRAIN2_BASE_URL).rstrip("/")
        api_url = (
            f"{base_url}/{train_no}/live"
            f"?haltsOnly=true&date={convert_date(date_value)}"
        )
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching from whereismytrain2: {e}")
        return {}


def has_whereismytrain_data(response: Optional[Dict[str, Any]]) -> bool:
    if not response:
        return False
    if response.get("currentStation"):
        return True
    schedule = response.get("schedule")
    return isinstance(schedule, list) and bool(schedule)


def fetch_whereismytrain_response(train_no: str, date_value: Optional[str]) -> Dict[str, Any]:
    try:
        status2 = fetch_whereismytrain2_status(train_no, date_value)
        data = status2.get("data") if isinstance(status2, dict) else None
        if not isinstance(data, dict):
            return {}

        current_location = data.get("currentLocation")
        route = data.get("route")
        if not isinstance(current_location, dict):
            current_location = {}

        station_code = current_location.get("stationCode")
        has_route = isinstance(route, list) and bool(route)
        if not station_code and not has_route:
            return {}

        return {
            "distance": current_location.get("distanceFromOriginKm"),
            "running_status": current_location.get("status") or "",
            "schedule": route if isinstance(route, list) else [],
            "currentStation": station_code,
        }
    except Exception as e:
        print(f"Error fetching from whereismytrain_response: {e}")
        return {}
    
def format_final_response(result: Any, whereismytrain_response: Any, live_train_status: Any) -> Any:
    schedule = result.get("schedule") or None
    for station in schedule:
        stationFromProviderResponse = getStationFromProviderResponse(whereismytrain_response, station.get("stationCode"))
        station["arrivalTime"] = get_time(stationFromProviderResponse.get("actualArrival")) if stationFromProviderResponse.get("actualArrival") else station.get("scheduledArrivalTime")
        station["departureTime"] = get_time(stationFromProviderResponse.get("actualDeparture")) if stationFromProviderResponse.get("actualDeparture") else station.get("scheduledDepartureTime")
        station["originDst"] =  stationFromProviderResponse.get("distance") if stationFromProviderResponse.get("distance") else 0
        station["delayArr"] = stationFromProviderResponse.get("delayArrival") if stationFromProviderResponse.get("delayArrival") else 0
        station["delayDep"] = stationFromProviderResponse.get("delayDeparture") if stationFromProviderResponse.get("delayDeparture") else 0
        result["schedule"] = schedule    
    whereIsMyTrainRunningStatus = whereismytrain_response.get("running_status")
    if not live_train_status.get("running_status_overridden"):
        live_train_status["running_status"] = format_train_running_status(whereIsMyTrainRunningStatus)
    else:
        live_train_status["running_status"] = "at-station"
    live_train_status["whereismytrain_running_status"] = whereIsMyTrainRunningStatus   
    currentStation = getStationFromProviderResponse(whereismytrain_response, whereismytrain_response.get("currentStation"))

    live_train_status["delay"] = currentStation.get("delayArr") or currentStation.get("delayDep")

    result["live_train_status"] = live_train_status
    return result

def getStationFromProviderResponse(provider_response: Any, station_code: str) -> Any:
    schedule = provider_response.get("schedule")
    if not isinstance(schedule, list):
        return {}
    for station in schedule:
        if station.get("stationCode") == station_code:
            return station
    return {}


def get_time(datetime_str:str):
    return datetime.fromisoformat(datetime_str).strftime("%H:%M")