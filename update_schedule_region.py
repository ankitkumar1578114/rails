#!/usr/bin/env python3
"""Add region_code to each station entry in trains.schedule using stationsV2."""

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import mysql.connector

DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "mydb"),
}

INTERMEDIATE_KEYS = (
    "intermediate_stations",
    "intermediateStations",
    "intermediateStationsList",
)


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


def normalize_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def get_station_code(item: Dict[str, Any]) -> Optional[str]:
    for key in ("station_code", "stationCode", "StationCode", "code", "Code"):
        code = normalize_code(item.get(key))
        if code:
            return code
    return None


def get_region_from_row(row: Dict[str, Any]) -> Optional[str]:
    for key in ("region", "region_code", "Region", "RegionCode"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def load_region_map(conn, stations_table: str) -> Dict[str, str]:
    sql = f"""
        SELECT *
        FROM `{stations_table}`
        WHERE station_code IS NOT NULL
    """
    mapping: Dict[str, str] = {}
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(sql)
        for row in cursor:
            code = normalize_code(row.get("station_code"))
            region = get_region_from_row(row)
            if code and region:
                mapping[code] = region
    return mapping


def enrich_station_item(item: Dict[str, Any], region_map: Dict[str, str]) -> int:
    changed = 0
    code = get_station_code(item)
    if code:
        region = region_map.get(code)
        if region is not None and item.get("region_code") != region:
            item["region_code"] = region
            changed += 1

    for key in INTERMEDIATE_KEYS:
        nested = item.get(key)
        if not isinstance(nested, list):
            continue
        for nested_item in nested:
            if isinstance(nested_item, dict):
                changed += enrich_station_item(nested_item, region_map)

    return changed


def apply_region_update(
    schedule_value: Any,
    region_map: Dict[str, str],
) -> Tuple[Any, int]:
    schedule = parse_json(schedule_value)
    if not isinstance(schedule, list):
        return schedule_value, 0

    changed = 0
    for item in schedule:
        if isinstance(item, dict):
            changed += enrich_station_item(item, region_map)

    if changed == 0:
        return schedule_value, 0

    return json.dumps(schedule, ensure_ascii=False), changed


def iter_train_row_batches(
    conn,
    batch_size: int = 100,
    limit: Optional[int] = None,
) -> Iterable[List[Dict[str, Any]]]:
    sql = "SELECT id, train_no, schedule FROM trains WHERE schedule IS NOT NULL"
    offset = 0
    fetched = 0

    while True:
        current_batch_size = batch_size
        if limit is not None:
            remaining = limit - fetched
            if remaining <= 0:
                break
            current_batch_size = min(batch_size, remaining)

        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(f"{sql} LIMIT %s OFFSET %s", (current_batch_size, offset))
            batch = cursor.fetchall()

        if not batch:
            break

        yield batch
        fetched += len(batch)
        offset += len(batch)


def update_train_rows(conn, updates: List[Dict[str, Any]], dry_run: bool) -> None:
    if not updates:
        return

    sql = "UPDATE trains SET schedule = %s WHERE id = %s"
    with conn.cursor() as cursor:
        for item in updates:
            if dry_run:
                print(
                    f"[dry-run] Would update train_id={item['id']} "
                    f"train_no={item['train_no']} with {item['changed']} region_code changes"
                )
                continue

            cursor.execute(sql, (item["schedule"], item["id"]))
            print(
                f"Updated train_id={item['id']} train_no={item['train_no']} "
                f"with {item['changed']} region_code changes"
            )

    if not dry_run:
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add region_code to train schedule entries from stationsV2."
    )
    parser.add_argument("--host", default=DEFAULT_DB_CONFIG["host"], help="MySQL host")
    parser.add_argument("--user", default=DEFAULT_DB_CONFIG["user"], help="MySQL user")
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
        "--stations-table",
        default=os.getenv("STATIONS_TABLE", "stationsV2"),
        help="Table containing station_code and region",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of train rows to fetch per batch",
    )
    parser.add_argument(
        "--commit-batch-size",
        type=int,
        default=50,
        help="Number of updated rows to commit together",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N train rows (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute updates but do not write to the database",
    )
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be greater than 0")
    if args.commit_batch_size <= 0:
        raise SystemExit("--commit-batch-size must be greater than 0")

    with get_db_connection(
        args.host,
        args.user,
        args.password,
        args.database,
    ) as conn:
        print(f"Loading region map from {args.stations_table}...")
        region_map = load_region_map(conn, args.stations_table)
        print(f"Loaded {len(region_map)} station regions")

        processed_rows = 0
        changed_rows = 0
        missing_codes: Dict[str, int] = {}
        updates: List[Dict[str, Any]] = []

        def flush_updates() -> None:
            nonlocal updates, changed_rows
            if not updates:
                return
            batch = updates[:]
            updates = []
            update_train_rows(conn, batch, args.dry_run)
            changed_rows += len(batch)

        for batch in iter_train_row_batches(
            conn,
            batch_size=args.batch_size,
            limit=args.limit,
        ):
            for row in batch:
                processed_rows += 1
                updated_schedule, changed = apply_region_update(
                    row.get("schedule"),
                    region_map,
                )

                if changed > 0:
                    updates.append(
                        {
                            "id": row.get("id"),
                            "train_no": row.get("train_no"),
                            "schedule": updated_schedule,
                            "changed": changed,
                        }
                    )
                    if len(updates) >= args.commit_batch_size:
                        flush_updates()
                else:
                    schedule = parse_json(row.get("schedule"))
                    if isinstance(schedule, list):
                        for item in schedule:
                            if not isinstance(item, dict):
                                continue
                            code = get_station_code(item)
                            if code and code not in region_map:
                                missing_codes[code] = missing_codes.get(code, 0) + 1

        flush_updates()

        print(
            f"Finished processing {processed_rows} train rows; "
            f"{'would update' if args.dry_run else 'updated'} {changed_rows} rows"
        )
        if missing_codes:
            top_missing = sorted(missing_codes.items(), key=lambda item: item[1], reverse=True)[:20]
            print(f"Station codes missing from {args.stations_table} (top 20 by frequency):")
            for code, count in top_missing:
                print(f"  {code}: {count}")


if __name__ == "__main__":
    main()
