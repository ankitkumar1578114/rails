#!/usr/bin/env python3
"""Update train schedule station distances from WhereIsMyTrain live API data."""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple

import mysql.connector
import requests

API_URL = "https://whereismytrain.in/cache/live_status"
DEFAULT_DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "mydb",
}


def get_db_connection(host: str, user: str, password: str, database: str):
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
    )


def parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None
    return None


def get_station_code(item: Dict[str, Any]) -> Optional[str]:
    for key in ("station_code", "stationCode", "StationCode", "code"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def get_distance_fields(item: Dict[str, Any]) -> Iterable[str]:
    return (
        "whereismytraindistance",
        "whereismyTrainDistance",
        "whereismytrainDistance",
        "distance_from_origin",
        "distanceFromOrigin",
        "origin_dst",
        "originDst",
    )


def is_non_intermediate(item: Dict[str, Any]) -> bool:
    code = get_station_code(item)

    for key in (
        "isIntermediate",
        "is_intermediate",
        "isIntermediateStation",
        "is_intermediate_station",
    ):
        if key in item and str(item.get(key)).lower() in {"1", "true", "yes", "y"}:
            return False

    for key in (
        "intermediateStations",
        "intermediate_stations",
        "intermediateStationsList",
    ):
        nested = item.get(key)
        if isinstance(nested, list):
            for nested_item in nested:
                if isinstance(nested_item, dict):
                    nested_code = get_station_code(nested_item)
                    if nested_code and code and nested_code == code:
                        return False

    return True


def extract_days_schedule(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("days_schedule", "daysSchedule", "daySchedule", "schedule"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    return []


def fetch_live_status(
    train_no: int,
    date_value: str,
    app_version: str,
    session: Optional[requests.Session] = None,
    proxy: Optional[str] = None,
    max_retries: int = 3,
    backoff_seconds: float = 2.0,
    delay_seconds: float = 0.0,
) -> Dict[str, Any]:
    request = session.get if session is not None else requests.get
    request_kwargs = {
        "params": {
            "lang": "en",
            "appVersion": app_version,
            "date": date_value,
            "train_no": train_no,
        },
        "timeout": 30,
        "headers": {"User-Agent": "python-requests/2.x"},
    }
    if proxy:
        request_kwargs["proxies"] = {"http": proxy, "https": proxy}

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            response = request(API_URL, **request_kwargs)
            if response.status_code == 429:
                raise requests.HTTPError(f"429 Too Many Requests for train_no={train_no}")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("API response was not a JSON object")
            return data
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                sleep_time = backoff_seconds * attempt
                print(
                    f"Retrying train_no={train_no} after {sleep_time}s "
                    f"(attempt {attempt}/{max_retries}): {exc}"
                )
                time.sleep(sleep_time)
                continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Failed to fetch live status for train_no={train_no}")


def build_distance_map(response: Dict[str, Any]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for item in extract_days_schedule(response):
        code = get_station_code(item)
        if not code:
            continue

        distance_value = None
        for key in (
            "whereismytraindistance",
            "whereismyTrainDistance",
            "whereismytrainDistance",
            "distance_from_origin",
            "distanceFromOrigin",
            "distance",
            "origin_dst",
            "originDst",
        ):
            if key in item and item.get(key) is not None:
                distance_value = to_int(item.get(key))
                if distance_value is not None:
                    break

        if distance_value is not None:
            mapping[str(code).strip().upper()] = distance_value
    return mapping


def apply_distance_update(
    schedule_value: Any,
    distance_map: Dict[str, int],
) -> Tuple[Any, int]:
    schedule = parse_json(schedule_value)
    if not isinstance(schedule, list):
        return schedule_value, 0

    updated_count = 0
    for item in schedule:
        if not isinstance(item, dict):
            continue

        code = get_station_code(item)
        if not code or not is_non_intermediate(item):
            continue

        target_distance = distance_map.get(str(code).strip().upper())
        if target_distance is None:
            continue

        # Preserve all existing fields and add the new integer distance value.
        item["whereismytraindistance"] = target_distance
        item["whereismyTrainDistance"] = target_distance
        item["whereismytrainDistance"] = target_distance
        item["distance_from_origin"] = item.get("distance_from_origin") if item.get("distance_from_origin") is not None else target_distance
        item["distanceFromOrigin"] = item.get("distanceFromOrigin") if item.get("distanceFromOrigin") is not None else target_distance
        item["origin_dst"] = item.get("origin_dst") if item.get("origin_dst") is not None else target_distance
        item["originDst"] = item.get("originDst") if item.get("originDst") is not None else target_distance
        item["distance"] = target_distance
        updated_count += 1

    return json.dumps(schedule, ensure_ascii=False), updated_count


def fetch_and_prepare_update(
    row: Dict[str, Any],
    date_value: str,
    app_version: str,
    session: Optional[requests.Session] = None,
    proxy: Optional[str] = None,
    max_retries: int = 3,
    backoff_seconds: float = 2.0,
    delay_seconds: float = 0.0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    train_no = row.get("train_no")
    if train_no is None:
        return None, "missing train_no"

    try:
        train_no_int = int(train_no)
    except (TypeError, ValueError):
        return None, f"invalid train_no={train_no}"

    try:
        response = fetch_live_status(
            train_no_int,
            date_value,
            app_version,
            session=session,
            proxy=proxy,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            delay_seconds=delay_seconds,
        )
        distance_map = build_distance_map(response)
        if not distance_map:
            return None, f"no distances found for train_no={train_no_int}"

        updated_schedule, changed = apply_distance_update(row.get("schedule"), distance_map)
        return {
            "id": row.get("id"),
            "schedule": updated_schedule,
            "changed": changed,
            "train_no": train_no_int,
        }, None
    except Exception as exc:
        return None, f"train_no={train_no_int}: {exc}"


def update_train_rows(conn, updates: List[Dict[str, Any]]) -> None:
    if not updates:
        return

    sql = "UPDATE trains SET schedule = %s WHERE id = %s"
    with conn.cursor() as cursor:
        for item in updates:
            cursor.execute(sql, (item["schedule"], item["id"]))
            print(
                f"Updated train_id={item['id']} train_no={item['train_no']} "
                f"with {item['changed']} station distance changes"
            )
        conn.commit()


def iter_train_rows(conn, batch_size: int = 100) -> Iterable[Dict[str, Any]]:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT id, train_no, schedule FROM trains WHERE train_no IS NOT NULL AND schedule IS NOT NULL"
        )
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            for row in batch:
                yield row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update non-intermediate station distances from WhereIsMyTrain live data."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_DB_CONFIG["host"],
        help="MySQL host",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_DB_CONFIG["user"],
        help="MySQL user",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_DB_CONFIG["password"],
        help="MySQL password",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DB_CONFIG["database"],
        help="MySQL database",
    )
    parser.add_argument(
        "--date",
        default="17-06-2026",
        help="Date to request from the live-status API",
    )
    parser.add_argument(
        "--app-version",
        default="6.7.5",
        help="App version to send to the API",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Number of concurrent API requests",
    )
    parser.add_argument(
        "--proxy",
        default=os.getenv("WHEREISMYTRAIN_PROXY") or "",
        help="Proxy URL for WhereIsMyTrain requests (e.g. http://user:pass@host:port)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries for 429 or transient API failures",
    )
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=2.0,
        help="Seconds to wait between retries",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay before each API request to reduce rate-limit pressure",
    )
    args = parser.parse_args()

    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be greater than 0")

    with get_db_connection(
        args.host,
        args.user,
        args.password,
        args.database,
    ) as conn:
        total_rows = 0
        changed_rows = 0

        print(
            f"Fetching station distances for trains from {args.database} "
            f"using concurrency={args.concurrency}"
        )

        proxy = args.proxy.strip() or None
        print(f"Using proxy={'yes' if proxy else 'no'}")

        updates: List[Dict[str, Any]] = []
        update_batch_size = 10

        def flush_updates() -> None:
            nonlocal updates, changed_rows
            if not updates:
                return
            batch = updates[:]
            updates = []
            update_train_rows(conn, batch)
            changed_rows += len(batch)
            print(
                f"Committed {len(batch)} updated rows to the database "
                f"(running total: {changed_rows})"
            )

        with requests.Session() as session:
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = {
                    executor.submit(
                        fetch_and_prepare_update,
                        row,
                        args.date,
                        args.app_version,
                        session=session,
                        proxy=proxy,
                        max_retries=args.max_retries,
                        backoff_seconds=args.backoff_seconds,
                        delay_seconds=args.delay_seconds,
                    ): row.get("id")
                    for row in iter_train_rows(conn)
                }
                for future in as_completed(futures):
                    row_id = futures[future]
                    try:
                        update, exc = future.result()
                    except Exception as exc:
                        print(f"Failed for row_id={row_id}: {exc}")
                        continue

                    if exc is not None:
                        print(f"Failed for row_id={row_id}: {exc}")
                        continue

                    if update is None:
                        continue

                    total_rows += 1
                    if update.get("changed", 0) > 0:
                        updates.append(update)
                        print(
                            f"Prepared train_no={update['train_no']} with {update['changed']} station updates"
                        )
                        if len(updates) >= update_batch_size:
                            flush_updates()
                    else:
                        print(f"No station distance changes for train_no={update['train_no']}")

                flush_updates()

        print(
            f"Finished processing {total_rows} rows; committed {changed_rows} updated rows"
        )


if __name__ == "__main__":
    main()
