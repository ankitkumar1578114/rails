import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import mysql.connector
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from fetch_live_status import fetch_train_status
from api.sources.redbus import RedbusTrainStatusProvider

app = FastAPI(
    title="Live Train Status API",
    description="Fetch live train status from confirmtkt.com",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/status")
def get_live_status(
    request: Request,
    train: Optional[str] = Query(None, description="Primary train number query parameter"),
    train_no: Optional[str] = Query(None, alias="train_no", description="Alternative train number query parameter"),
    date: Optional[str] = Query(None, alias="date", description="Optional date parameter in format 11-Jun-2026"),
):
    train_no_value = (train or train_no or "").strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required query parameter: train or train_no")

    date_value = request.query_params.get("Date") or date
    if date_value:
        date_value = date_value.strip()

    try:
        return fetch_train_status(train_no_value, date_value)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch live status: {exc}")


@app.get("/v2/status")
def get_v2_status(
    request: Request,
    train: Optional[str] = Query(None, description="Primary train number query parameter"),
    train_no: Optional[str] = Query(None, alias="train_no", description="Alternative train number query parameter"),
    date: Optional[str] = Query(None, alias="date", description="Optional date parameter in format 11-Jun-2026"),
):
    train_no_value = (train or train_no or "").strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required query parameter: train or train_no")

    date_value = request.query_params.get("Date") or date
    if date_value:
        date_value = date_value.strip()

    try:
        provider = RedbusTrainStatusProvider()
        live_status = provider.fetch(train_no_value)
        metadata = fetch_train_metadata(train_no_value)
        return merge_live_with_metadata(live_status, metadata)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch v2 status: {exc}")


def get_db_connection():
    return mysql.connector.connect(
        # host="127.0.0.1",
        # user="root",
        # password="",
        # database="mydb",
        host = "bwr2tjeeysysm7um7pfo-mysql.services.clever-cloud.com",
        user = "ucg3v1n4o6kbgzk2",
        password = "8CJNC9GDRkkpe5kPvzJw",
        database = "bwr2tjeeysysm7um7pfo"
    )


def parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def fetch_train_metadata(train_no: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT *
        FROM trains
        WHERE train_number_string = %s OR train_no = %s
        LIMIT 1
    """
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (train_no, train_no))
            row = cursor.fetchone()
            if not row:
                return None

            row["days_of_run"] = parse_json_value(row.get("days_of_run") or row.get("DaysOfRun"))
            row["classes"] = parse_json_value(row.get("classes") or row.get("Classes"))
            row["schedule"] = parse_json_value(row.get("schedule") or row.get("Schedule"))
            return row


def merge_live_with_metadata(live_status: Dict[str, Any], metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if metadata is None:
        return live_status

    merged = live_status.copy()
    fallback_fields = [
        "train_name",
        "train_number_string",
        "train_type",
        "source_station",
        "source_code",
        "destination",
        "destination_code",
        "days_of_run",
        "classes",
        "schedule",
        "total_duration",
        "total_distance",
        "total_number_of_stops",
    ]

    for field in fallback_fields:
        if not merged.get(field) and metadata.get(field) is not None:
            merged[field] = metadata.get(field)

    if not merged.get("train_no") and metadata.get("train_number_string"):
        merged["train_no"] = str(metadata.get("train_number_string"))
    return merged


def fetch_stations_by_code(code: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_code LIKE %s
        ORDER By weight desc

    """
    like_value = f"%{code}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()


def fetch_stations_by_name(name: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_name LIKE %s
        ORDER By weight desc
    """
    like_value = f"%{name}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()


def fetch_trains_by_query(query_value: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM trains
        WHERE train_number_string LIKE %s
           OR train_name LIKE %s
        LIMIT 5
    """
    like_value = f"%{query_value}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value, like_value))
            return cursor.fetchall()


def parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def parse_json_string_list(value: Any) -> List[str]:
    return [str(item) for item in parse_json_list(value) if item is not None]


def normalize_station_code(code: Any) -> Optional[str]:
    if code is None:
        return None
    return str(code).strip().upper()


def load_station_trains(station_code: str) -> List[str]:
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT trains FROM stations WHERE station_code = %s LIMIT 1", (station_code,))
            row = cursor.fetchone()
            if not row:
                return []
            return parse_json_string_list(row.get("trains"))


def route_has_station_order(route: List[Any], from_station: str, to_station: str) -> bool:
    if not route:
        return False

    source_code = normalize_station_code(from_station)
    dest_code = normalize_station_code(to_station)
    if not source_code or not dest_code or source_code == dest_code:
        return False

    source_index = None
    dest_index = None

    for idx, station in enumerate(route):
        if isinstance(station, dict):
            code = (
                station.get("StationCode")
                or station.get("stationCode")
                or station.get("station_code")
                or station.get("code")
            )
        else:
            code = station
        normalized = normalize_station_code(code)
        if normalized == source_code and source_index is None:
            source_index = idx
        if normalized == dest_code and dest_index is None:
            dest_index = idx
        if source_index is not None and dest_index is not None:
            break

    return source_index is not None and dest_index is not None and source_index < dest_index


def fetch_trains_between(from_station: str, to_station: str) -> List[Dict[str, Any]]:
    from_trains = set(load_station_trains(from_station))
    to_trains = set(load_station_trains(to_station))
    common_trains = from_trains.intersection(to_trains)
    if not common_trains:
        return []

    placeholders = ",".join(["%s"] * len(common_trains))
    query = f"SELECT * FROM trains WHERE train_number_string IN ({placeholders})"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, tuple(common_trains))
            rows = cursor.fetchall()

    filtered_rows: List[Dict[str, Any]] = []
    for row in rows:
        schedule = parse_json_list(row.get("Schedule") or row.get("schedule"))
        if route_has_station_order(schedule, from_station, to_station):
            filtered_rows.append(row)

    return filtered_rows


@app.get("/stations")
def search_stations(
    q: Optional[str] = Query(None, description="Search term for station code first, then station name"),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameter: q")

    search_term = q.strip()
    try:
        results: List[Dict[str, Any]] = []
        seen_codes = set()

        name_results = fetch_stations_by_name(search_term)
        for row in name_results:
            results.append(row)
            if "code" in row:
                seen_codes.add(row["code"])
            if len(results) >= 5:
                return results

        code_results = fetch_stations_by_code(search_term)
        for row in code_results:
            if row.get("code") not in seen_codes:
                results.append(row)
                if len(results) >= 5:
                    break

        return results
    except mysql.connector.Error as exc:
        raise HTTPException(status_code=500, detail=f"Database error while fetching stations: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stations: {exc}")


@app.get("/trains")
def search_trains(
    q: Optional[str] = Query(None, description="Search term for train number or train name"),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameter: q")

    try:
        return fetch_trains_by_query(q.strip())
    except mysql.connector.Error as exc:
        raise HTTPException(status_code=500, detail=f"Database error while fetching trains: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trains: {exc}")


@app.get("/trains/between")
def search_trains_between(
    from_station: Optional[str] = Query(None, alias="from", description="Source station code or name"),
    to_station: Optional[str] = Query(None, alias="to", description="Destination station code or name"),
):
    if not from_station or not from_station.strip() or not to_station or not to_station.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameters: from and to")

    try:
        return fetch_trains_between(from_station.strip(), to_station.strip())
    except mysql.connector.Error as exc:
        raise HTTPException(status_code=500, detail=f"Database error while fetching trains between stations: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trains between stations: {exc}")


def run_server(host: str, port: int):
    uvicorn.run("api.index:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a local live train status API for confirmtkt.com")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the server")
    args = parser.parse_args()
    run_server(args.host, args.port)
