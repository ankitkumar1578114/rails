#!/usr/bin/env python3
"""Populate station coordinates from ixigo into a duplicate stationsV2 table.

The script:
1. Reads station rows from the configured source table.
2. Fetches ixigo station data for each station code in batches of 10 requests.
3. Matches the incoming station code with the response payload.
4. Stores the original row plus lat, lon, and ext in the target table.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Sequence

import mysql.connector
import requests

DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "mydb"),
}

DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_WORKERS = 3
DEFAULT_REQUEST_DELAY = 1.0
DEFAULT_MAX_RETRIES = 4
IXIGO_API_URL = (
    "https://www.ixigo.com/action/content/trainstation"
    "?searchFor=trainstationsLatLon&anchor=false&value={code}"
)

proxy_pool: List[str] = []
proxy_cycle = None
proxy_lock = Lock()


def get_db_connection(config: Dict[str, Any]) -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(**config)


def load_proxy_list(proxy_arg: Optional[str], proxy_file: Optional[str]) -> List[str]:
    proxies: List[str] = []
    if proxy_arg:
        proxies.extend([item.strip() for item in proxy_arg.split(",") if item.strip()])
    if proxy_file and os.path.isfile(proxy_file):
        with open(proxy_file, "r", encoding="utf-8") as fh:
            proxies.extend([line.strip() for line in fh if line.strip()])
    return list(dict.fromkeys(proxies))


def configure_proxy_rotation(proxy_arg: Optional[str], proxy_file: Optional[str]) -> None:
    global proxy_pool, proxy_cycle
    proxy_pool = load_proxy_list(proxy_arg, proxy_file)
    proxy_cycle = cycle(proxy_pool) if proxy_pool else None


def get_next_proxy() -> Optional[str]:
    global proxy_cycle
    if not proxy_cycle:
        return None
    with proxy_lock:
        return next(proxy_cycle)


def fetch_columns(conn, table_name: str) -> List[str]:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table_name,),
        )
        return [row["COLUMN_NAME"] for row in cursor.fetchall()]


def ensure_target_table(conn, source_table: str, target_table: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS `{target_table}` LIKE `{source_table}`"
        )
        conn.commit()

    column_defs = {
        "lat": "VARCHAR(255) DEFAULT NULL",
        "lon": "VARCHAR(255) DEFAULT NULL",
        "ext": "VARCHAR(255) DEFAULT NULL",
    }

    for column_name, definition in column_defs.items():
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                f"SHOW COLUMNS FROM `{target_table}` LIKE %s",
                (column_name,),
            )
            if cursor.fetchone() is None:
                with conn.cursor() as alter_cursor:
                    alter_cursor.execute(
                        f"ALTER TABLE `{target_table}` ADD COLUMN `{column_name}` {definition}"
                    )
    conn.commit()


def normalize_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def get_station_code(row: Dict[str, Any]) -> Optional[str]:
    for key in (
        "station_code",
        "stationCode",
        "StationCode",
        "code",
        "Code",
        "stationCodeFromSource",
    ):
        code = normalize_code(row.get(key))
        if code:
            return code
    return None


def get_lat_lon(item: Dict[str, Any]) -> Dict[str, Optional[str]]:
    for key in ("lat", "latitude", "Latitude", "latitute"):
        if key in item and item.get(key) not in (None, ""):
            lat = str(item.get(key))
            break
    else:
        lat = None

    for key in ("lon", "lng", "longitude", "Longitude", "long"):
        if key in item and item.get(key) not in (None, ""):
            lon = str(item.get(key))
            break
    else:
        lon = None

    return {"lat": lat, "lon": lon}


def response_item_matches(item: Dict[str, Any], target_code: str) -> bool:
    # Explicit field matches.
    for key in (
        "stationCode",
        "station_code",
        "StationCode",
        "code",
        "Code",
        "c",
        "a",
    ):
        if normalize_code(item.get(key)) == target_code:
            return True

    # Fallback: match against text fields that may contain (CODE).
    text_fields = [
        item.get("e"),
        item.get("name"),
        item.get("stationName"),
        item.get("station_name"),
        item.get("value"),
    ]
    for value in text_fields:
        if value is None:
            continue
        if re.search(rf"\({re.escape(target_code)}\)", str(value), flags=re.IGNORECASE):
            return True
    return False


def fetch_ixigo_response(
    code: str,
    timeout: int = 20,
    request_delay: float = DEFAULT_REQUEST_DELAY,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> List[Dict[str, Any]]:
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            if request_delay > 0:
                time.sleep(request_delay)

            proxy = get_next_proxy()
            request_kwargs = {
                "timeout": timeout,
                "headers": {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.ixigo.com/",
                },
            }
            if proxy:
                request_kwargs["proxies"] = {
                    "http": proxy,
                    "https": proxy,
                }

            response = requests.get(
                IXIGO_API_URL.format(code=code),
                **request_kwargs,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == max_retries:
                    response.raise_for_status()
                wait_time = min(2 ** attempt, 30)
                print(
                    f"Rate-limited or server error for {code} (status={response.status_code}). "
                    f"Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})"
                )
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, dict):
                for key in ("stations", "data", "items", "results"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, dict)]
            return []
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == max_retries:
                raise
            wait_time = min(2 ** attempt, 30)
            print(
                f"Retrying {code} after error: {exc}. Sleeping {wait_time}s"
            )
            time.sleep(wait_time)

    if last_error is not None:
        raise last_error
    return []


def build_update_payload(
    row: Dict[str, Any],
    columns: Sequence[str],
    matched_item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = dict(row)
    if matched_item:
        payload["lat"] = matched_item.get("lat") if matched_item.get("lat") not in (None, "") else None
        payload["lon"] = matched_item.get("lon") if matched_item.get("lon") not in (None, "") else None
        payload["ext"] = matched_item.get("a") if matched_item.get("a") not in (None, "") else None
    else:
        payload["lat"] = None
        payload["lon"] = None
        payload["ext"] = None

    # Ensure every output column exists, even if the row dict doesn't include it.
    for col in columns:
        payload.setdefault(col, None)
    return payload


def insert_or_update_row(
    conn,
    source_table: str,
    target_table: str,
    columns: Sequence[str],
    row: Dict[str, Any],
    matched_item: Optional[Dict[str, Any]],
) -> None:
    payload = build_update_payload(row, columns, matched_item)
    insert_columns = list(columns)
    if "lat" not in insert_columns:
        insert_columns.append("lat")
    if "lon" not in insert_columns:
        insert_columns.append("lon")
    if "ext" not in insert_columns:
        insert_columns.append("ext")

    placeholders = ", ".join(["%s"] * len(insert_columns))
    sql = (
        f"INSERT INTO `{target_table}` ({', '.join(f'`{c}`' for c in insert_columns)}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE "
        + ", ".join(f"`{c}` = VALUES(`{c}`)" for c in insert_columns)
    )
    values = tuple(payload.get(c) for c in insert_columns)
    with conn.cursor() as cursor:
        cursor.execute(sql, values)
    conn.commit()


def fetch_rows(conn, source_table: str) -> List[Dict[str, Any]]:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(f"SELECT * FROM `{source_table}`")
        return cursor.fetchall()


def process_station_row(
    db_config: Dict[str, Any],
    source_table: str,
    target_table: str,
    columns: Sequence[str],
    row: Dict[str, Any],
    timeout: int,
    request_delay: float,
    max_retries: int,
) -> Dict[str, Any]:
    station_code = get_station_code(row)
    if not station_code:
        return {"row": row, "matched": False, "reason": "missing_station_code"}

    conn = get_db_connection(db_config)
    try:
        try:
            response_items = fetch_ixigo_response(
                station_code,
                timeout=timeout,
                request_delay=request_delay,
                max_retries=max_retries,
            )
        except requests.RequestException as exc:
            return {"row": row, "matched": False, "reason": f"request_error:{exc}"}
        except ValueError as exc:
            return {"row": row, "matched": False, "reason": f"json_error:{exc}"}

        matched_item = None
        for item in response_items:
            if response_item_matches(item, station_code):
                matched_item = item
                break

        lat_lon = get_lat_lon(matched_item or {})
        if matched_item:
            matched_item = {**matched_item, **lat_lon}

        insert_or_update_row(
            conn,
            source_table,
            target_table,
            columns,
            row,
            matched_item,
        )
        return {
            "row": row,
            "matched": matched_item is not None,
            "station_code": station_code,
            "reason": "matched" if matched_item else "not_found",
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch station coordinates from ixigo for rows in stations and store them in stationsV2."
    )
    parser.add_argument(
        "--source-table",
        default=os.getenv("SOURCE_TABLE", "stations"),
        help="Source table to read station rows from.",
    )
    parser.add_argument(
        "--target-table",
        default=os.getenv("TARGET_TABLE", "stationsV2"),
        help="Target table to write the duplicate rows to.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("BATCH_SIZE", DEFAULT_BATCH_SIZE)),
        help="Number of rows to process in a batch.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("MAX_WORKERS", DEFAULT_MAX_WORKERS)),
        help="Maximum number of concurrent requests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("REQUEST_TIMEOUT", 20)),
        help="HTTP timeout per request.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=float(os.getenv("REQUEST_DELAY", DEFAULT_REQUEST_DELAY)),
        help="Seconds to pause between request attempts.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("MAX_RETRIES", DEFAULT_MAX_RETRIES)),
        help="Number of retries after transient request failures.",
    )
    parser.add_argument(
        "--proxy",
        default=os.getenv("REQUEST_PROXY"),
        help="Comma-separated list of proxy URLs to rotate between requests.",
    )
    parser.add_argument(
        "--proxy-file",
        default=os.getenv("REQUEST_PROXY_FILE"),
        help="Path to a text file containing proxy URLs (one per line).",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("DB_HOST", DEFAULT_DB_CONFIG["host"]),
        help="MySQL host.",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("DB_USER", DEFAULT_DB_CONFIG["user"]),
        help="MySQL user.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("DB_PASSWORD", DEFAULT_DB_CONFIG["password"]),
        help="MySQL password.",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DB_NAME", DEFAULT_DB_CONFIG["database"]),
        help="MySQL database.",
    )
    args = parser.parse_args()

    config = {
        "host": args.host,
        "user": args.user,
        "password": args.password,
        "database": args.database,
    }
    configure_proxy_rotation(args.proxy, args.proxy_file)

    if proxy_pool:
        print(f"Using {len(proxy_pool)} proxy entries for rotation")

    try:
        conn = get_db_connection(config)
    except mysql.connector.Error as exc:
        raise SystemExit(f"Unable to connect to database: {exc}")

    try:
        ensure_target_table(conn, args.source_table, args.target_table)
        columns = fetch_columns(conn, args.source_table)
        # Ensure target columns are synced.
        if "lat" not in columns:
            columns = columns + ["lat", "lon", "ext"]
        rows = fetch_rows(conn, args.source_table)

        processed = 0
        total = len(rows)
        print(
            f"Starting to process {total} rows from `{args.source_table}` into `{args.target_table}` "
            f"with batch size {args.batch_size}"
        )

        for start in range(0, total, args.batch_size):
            batch = rows[start : start + args.batch_size]
            with ThreadPoolExecutor(
                max_workers=min(args.workers, len(batch), args.batch_size)
            ) as executor:
                futures = {
                    executor.submit(
                        process_station_row,
                        config,
                        args.source_table,
                        args.target_table,
                        columns,
                        row,
                        args.timeout,
                        args.request_delay,
                        args.max_retries,
                    ): row
                    for row in batch
                }
                for future in as_completed(futures):
                    result = future.result()
                    processed += 1
                    if result["matched"]:
                        print(
                            f"Matched {result['station_code']} -> {result['reason']}"
                        )
                    else:
                        print(
                            f"No match for {result.get('station_code') or 'unknown'} -> {result['reason']}"
                        )
        print(f"Finished processing {processed} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
