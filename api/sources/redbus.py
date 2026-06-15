import requests
from typing import Any, Dict, List, Optional

from .base import TrainStatusProvider


class RedbusTrainStatusProvider(TrainStatusProvider):
    source_name = "redbus"

    def _normalize_station(self, station: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "station_name": station.get("stationName") or station.get("StationName") or None,
            "station_code": station.get("stationCode") or station.get("StationCode") or None,
            "distance_from_origin": station.get("distanceFromOrigin") or station.get("DistanceFromOrigin") or None,
            "origin_dst": station.get("originDst") or station.get("originDst") or None,
            "platform": station.get("platform") or station.get("Platform") or None,
            "scheduled_arrival_time": station.get("scheduledArrivalTime") or station.get("ScheduledArrivalTime") or None,
            "arrival_time": station.get("arrivalTime") or station.get("ArrivalTime") or None,
            "scheduled_departure_time": station.get("scheduledDepartureTime") or station.get("ScheduledDepartureTime") or None,
            "departure_time": station.get("departureTime") or station.get("DepartureTime") or None,
            "day_count": station.get("dayCount") or station.get("Day") or None,
            "arrival_date": station.get("arrivalDate") or station.get("ArrivalDate") or None,
            "departure_date": station.get("departureDate") or station.get("DepartureDate") or None,
            "delay_arr": station.get("delayArr") or station.get("delayArr") or None,
            "delay_dep": station.get("delayDep") or station.get("delayDep") or None,
            "is_station_cancelled": station.get("isStationCancelled") or station.get("is_station_cancelled") or None,
            "is_it_queried_station": station.get("isItQueriedStation") or station.get("is_it_queried_station") or None,
            "has_arrived": station.get("hasArrived") or station.get("has_arrived") or None,
            "has_departed": station.get("hasDeparted") or station.get("has_departed") or None,
            "delay_status": station.get("delayStatus") or station.get("delay_status") or None,
            "current_delay_status": station.get("currDelayStatus") or station.get("currDelayStatus") or None,
            "intermediate_stations": self._normalize_intermediate_stations(station.get("intermediateStations") or station.get("intermediate_stations") or []),
        }

    def _normalize_intermediate_stations(self, items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "station_name": item.get("stationName") or item.get("station_name") or None,
                    "station_code": item.get("stationCode") or item.get("station_code") or None,
                    "scheduled_time": item.get("scheduledTime") or item.get("scheduled_time") or None,
                    "distance_from_origin": item.get("distanceFromOrigin") or item.get("distance_from_origin") or None,
                    "origin_dst": item.get("originDst") or item.get("origin_dst") or None,
                }
            )
        return normalized

    def _build_schedule(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        stations = raw.get("stations") or raw.get("Stations") or []
        if not isinstance(stations, list):
            return []
        return [self._normalize_station(station) for station in stations if isinstance(station, dict)]

    def _build_station_status(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        running_status = raw.get("runningStatus") or {}
        return {
            "currently_at": raw.get("currentlyAt") or raw.get("currently_at") or None,
            "currently_at_code": raw.get("currentlyAtCode") or raw.get("currently_at_code") or None,
            "upcoming_station": raw.get("upcomingStation") or raw.get("upcoming_station") or None,
            "upcoming_station_code": raw.get("upcomingStationCode") or raw.get("upcoming_station_code") or None,
            "total_late_minutes": raw.get("totalLateMins") or raw.get("total_late_mins") or None,
            "cancelled_from": raw.get("cancelledFrom") or raw.get("cancelled_from") or None,
            "cancelled_to": raw.get("cancelledTo") or raw.get("cancelled_to") or None,
            "running_status": {
                "header": running_status.get("header"),
                "status": running_status.get("status"),
                "message": running_status.get("runningStatusMessage") or running_status.get("running_status_message"),
            },
        }

    def _extract_route_endpoints(self, raw: Dict[str, Any]) -> Dict[str, Optional[str]]:
        schedule = self._build_schedule(raw)
        if schedule:
            first = schedule[0]
            last = schedule[-1]
            return {
                "source_station": first.get("station_name"),
                "source_code": first.get("station_code"),
                "destination": last.get("station_name"),
                "destination_code": last.get("station_code"),
            }
        return {
            "source_station": None,
            "source_code": None,
            "destination": None,
            "destination_code": None,
        }

    def fetch(self, train_no: str, **kwargs: Any) -> Dict[str, Any]:
        api_url = "https://www.redbus.in/railways/api/getLtsDetails"
        response = requests.get(api_url, params={"trainNo": train_no}, timeout=30)
        response.raise_for_status()
        raw = response.json()

        route_endpoints = self._extract_route_endpoints(raw)
        schedule = self._build_schedule(raw)
        station_status = self._build_station_status(raw)

        return self.normalize_response(
            train_no=str(raw.get("trainNumber") or raw.get("TrainNo") or train_no),
            train_name=raw.get("trainName") or None,
            train_number_string=str(raw.get("trainNumber") or raw.get("trainNo") or train_no),
            train_type=raw.get("trainType") or raw.get("TrainType") or None,
            source_station=route_endpoints["source_station"],
            source_code=route_endpoints["source_code"],
            destination=route_endpoints["destination"],
            destination_code=route_endpoints["destination_code"],
            classes=raw.get("classes") or raw.get("Classes") or None,
            schedule=schedule,
            total_duration=raw.get("totalDuration") or raw.get("TotalDuration") or None,
            total_distance=raw.get("totalDistance") or raw.get("TotalDistance") or None,
            total_number_of_stops=raw.get("totalNumberOfStops") or raw.get("TotalNumberOfStops") or None,
            page_title=None,
            status_source_url=api_url,
            station_status=station_status,
        )
