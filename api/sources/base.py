from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class TrainStatusProvider(ABC):
    """Uniform provider interface for train status sources."""

    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, train_no: str, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError()

    def normalize_response(
        self,
        train_no: str,
        train_name: Optional[str] = None,
        train_number_string: Optional[str] = None,
        train_type: Optional[str] = None,
        source_station: Optional[str] = None,
        source_code: Optional[str] = None,
        destination: Optional[str] = None,
        destination_code: Optional[str] = None,
        days_of_run: Optional[Any] = None,
        classes: Optional[Any] = None,
        schedule: Optional[Any] = None,
        total_duration: Optional[int] = None,
        total_distance: Optional[str] = None,
        total_number_of_stops: Optional[str] = None,
        page_title: Optional[str] = None,
        status_source_url: Optional[str] = None,
        station_status: Optional[Any] = None,
    ) -> Dict[str, Any]:
        return {
            "source": self.source_name,
            "train_no": str(train_no),
            "train_name": train_name,
            "train_number_string": train_number_string,
            "train_type": train_type,
            "source_station": source_station,
            "source_code": source_code,
            "destination": destination,
            "destination_code": destination_code,
            "days_of_run": days_of_run,
            "classes": classes,
            "schedule": schedule,
            "total_duration": total_duration,
            "total_distance": total_distance,
            "total_number_of_stops": total_number_of_stops,
            "page_title": page_title,
            "status_source_url": status_source_url,
            "station_status": station_status,
        }
