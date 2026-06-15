from typing import Any, Dict, Optional

from fetch_live_status import fetch_train_status
from .base import TrainStatusProvider


class ConfirmtktTrainStatusProvider(TrainStatusProvider):
    source_name = "confirmtkt"

    def fetch(self, train_no: str, date: Optional[str] = None) -> Dict[str, Any]:
        raw = fetch_train_status(train_no, date)
        train_info = raw.get("train_info", {}) if isinstance(raw, dict) else {}

        return self.normalize_response(
            train_no=str(train_info.get("train_number") or train_no),
            raw=raw,
            train_name=None,
            train_number_string=str(train_info.get("train_number") or train_no),
            train_type=None,
            source_station=None,
            source_code=None,
            destination=None,
            destination_code=None,
            days_of_run=None,
            classes=None,
            schedule=None,
            total_duration=None,
            total_distance=None,
            total_number_of_stops=None,
            page_title=train_info.get("page_title"),
            status_source_url=train_info.get("source_url"),
            station_status=raw.get("station_status") if isinstance(raw, dict) else None,
        )
