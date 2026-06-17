import requests
from datetime import datetime
from typing import Any, Dict, Optional


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
