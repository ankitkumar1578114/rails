import requests
from datetime import datetime
from typing import Any, Dict, Optional
from api.utils.helper import format_train_running_status

def convert_date(date_str):
    return datetime.strptime(date_str, "%d-%m-%Y").strftime("%Y-%m-%d")


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
        api_url = "https://2fe4m4jegh2fuhgkk3u7v4sqv40qpago.lambda-url.ap-south-1.on.aws/trains/"+train_no + "/live?haltsOnly=true&date="+convert_date(date_value)
        params={}
        response = requests.get(api_url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching from whereismytrain2: {e}")
        return {}

def fetch_whereismytrain_response(train_no: str, date_value: Optional[str]) -> Optional[int]:
    try:

        # status = fetch_whereismytrain_status(train_no, date_value)
        status2 = fetch_whereismytrain2_status(train_no, date_value)
        # distance = status.get("distance") if status.get("distance") is not None else 0
        distance2 = status2.get("data").get("currentLocation").get("distanceFromOriginKm") if status2.get("data") and status2.get("data").get("currentLocation") else 0
        distance2RunningStatus = status2.get("data").get("currentLocation").get("status") if status2.get("data") and status2.get("data").get("status") else ""
        schedule2 = status2.get("data").get("route");
        currentStation2 = status2.get("data").get("currentLocation").get("stationCode")
        # if isinstance(distance, int):
        #     return {
        #         "distance": distance,
        #         "running_status": distance2RunningStatus,
        #         "schedule": schedule2
        #         }
        return {
            "distance" : distance2,
            "running_status": distance2RunningStatus,
            "schedule": schedule2,
            "currentStation": currentStation2
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
    if not live_train_status["running_status_overridden"]:
        live_train_status["running_status"] = format_train_running_status(whereIsMyTrainRunningStatus)
    live_train_status["whereismytrain_running_status"] = whereIsMyTrainRunningStatus   
    currentStation = getStationFromProviderResponse(whereismytrain_response, whereismytrain_response.get("currentStation"))

    live_train_status["delay"] = currentStation.get("delayArr") or currentStation.get("delayDep")

    result["live_train_status"] = live_train_status
    return result

def getStationFromProviderResponse(provider_response:Any, station_code: str) -> Any:
    for station in provider_response.get("schedule"):
        if(station.get("stationCode") == station_code):
            return station
    return provider_response


def get_time(datetime_str:str):
    return datetime.fromisoformat(datetime_str).strftime("%H:%M")