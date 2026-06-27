import argparse
import json
import os
import sys

from typing import Any, Dict, List, Optional
from api.repos.db import db_connection

from api.services.trains import (
    fetchTrainsByNameOrNumber,
    fetch_trains_between,
    fetch_trains_between_with_alternatives,
)
from api.services.stations import getStationsByNameOrCode

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import mysql.connector
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from fetch_live_status import fetch_train_status
from api.sources.redbus import RedbusFetchError, RedbusTrainStatusProvider
from api.sources.whereismytrain import (
    fetch_whereismytrain_response,
    format_final_response,
    has_whereismytrain_data,
)
from api.utils.helper import getNonIntermediateStaionFromSchedule, getStationFromSchedule, compute_current_location

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
        result = fetch_train_metadata(train_no_value)
        if not result:
            raise HTTPException(status_code=404, detail=f"Train not found: {train_no_value}")

        whereIsMyTrainResponse = fetch_whereismytrain_response(train_no_value, date_value)

        if has_whereismytrain_data(whereIsMyTrainResponse):
            wimt_distance = whereIsMyTrainResponse.get("distance")
            live_train_status = compute_current_location(
                result.get("schedule"),
                0,
                wimt_distance if wimt_distance is not None else -1,
            )
            response = format_final_response(result, whereIsMyTrainResponse, live_train_status)
            response["live_status_source"] = "whereismytrain"
            return response

        if not date_value:
            raise HTTPException(
                status_code=400,
                detail="Missing required date parameter for Redbus fallback when WhereIsMyTrain has no data",
            )

        provider = RedbusTrainStatusProvider()
        provider_response = provider.fetch(train_no_value, date_value)
        providerCurrStationCode = provider_response.get("station_status").get("currently_at_code")
        providerCurrStation = (
            getStationFromSchedule(result.get("schedule"), providerCurrStationCode)
            if providerCurrStationCode
            else None
        )
        providerCurrStationDistance = providerCurrStation.get("originDst") if providerCurrStation else None

        live_train_status = compute_current_location(
            result.get("schedule"),
            providerCurrStationDistance if providerCurrStationDistance else 0,
            -1,
        )
        response = provider.format_final_response(result, provider_response, live_train_status)
        response["live_status_source"] = "redbus"
        return response
    except RedbusFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch v2 status: {exc}")
    





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
    with db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (train_no, train_no))
            row = cursor.fetchone()
            if not row:
                return None

            row["days_of_run"] = parse_json_value(row.get("days_of_run") or row.get("DaysOfRun"))
            row["classes"] = parse_json_value(row.get("classes") or row.get("Classes"))
            row["schedule"] = parse_json_value(row.get("schedule") or row.get("Schedule"))
            return row

@app.get("/stations")
def search_stations(
    q: Optional[str] = Query(None, description="Search term for station code first, then station name"),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameter: q")

    search_term = q.strip()
    try:
        return getStationsByNameOrCode(search_term)
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
        return fetchTrainsByNameOrNumber(q.strip())
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


@app.get("/trains/between/v2")
def search_trains_between_with_alternatives(
    from_station: Optional[str] = Query(None, alias="from", description="Source station code or name"),
    to_station: Optional[str] = Query(None, alias="to", description="Destination station code or name"),
):
    if not from_station or not from_station.strip() or not to_station or not to_station.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameters: from and to")

    try:
        return fetch_trains_between_with_alternatives(
            from_station.strip(), to_station.strip()
        )
    except mysql.connector.Error as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Database error while fetching trains between stations: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch trains between stations: {exc}",
        )


def run_server(host: str, port: int):
    uvicorn.run("api.index:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a local live train status API for confirmtkt.com")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the server")
    args = parser.parse_args()
    run_server(args.host, args.port)
