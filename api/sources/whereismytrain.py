import requests
from datetime import datetime
from typing import Any, Dict, Optional

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
        api_url = "https://2fe4m4jegh2fuhgkk3u7v4sqv40qpago.lambda-url.ap-south-1.on.aws/trains/"+train_no + "/live?haltsOnly=true&date=2026-06-20"
        params = {
            "date": convert_date(date_value),
        }
        response = requests.get(api_url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching from whereismytrain2: {e}")
        return {}

def fetch_whereismytrain_distance(train_no: str, date_value: Optional[str]) -> Optional[int]:
    status = fetch_whereismytrain_status(train_no, date_value)
    status2 = fetch_whereismytrain2_status(train_no, date_value)
    distance = status.get("distance") if status.get("distance") is not None else 0
    distance2 = status2.get("data").get("currentLocation").get("distanceFromOriginKm") if status2.get("data") and status2.get("data").get("currentLocation") else 0
    print(distance,distance2,date_value)
    if isinstance(distance, int):
        return distance
    return max(distance,distance2)