#!/usr/bin/env python3
import argparse
import csv
import json
import os
from typing import Any, Dict, List, Optional

import mysql.connector

INPUT_CSV = "redbus_train_details.csv"

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "mydb",
}


def get_db_connection(host: str, user: str, password: str, database: str):
    return mysql.connector.connect(host=host, user=user, password=password, database=database)


def ensure_route_column(conn) -> None:
    with conn.cursor() as cursor:
        try:
            cursor.execute("ALTER TABLE trains_data ADD COLUMN route JSON NULL")
            conn.commit()
            print("Added trains_data.route column")
        except mysql.connector.Error as exc:
            if exc.errno == 1060:
                print("trains_data.route already exists")
            else:
                raise


def load_train_rows(filename: str) -> List[Dict[str, str]]:
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Input file not found: {filename}")

    rows: List[Dict[str, str]] = []
    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for idx, row in enumerate(reader):
            if not row:
                continue
            if idx == 0 and row[0] in ("trainNo", "train_no", "train_number"):
                continue
            if len(row) < 3:
                continue
            train_no = row[0].strip()
            train_name = row[1].strip()
            response = ",".join(row[2:]).strip()
            rows.append({"train_no": train_no, "train_name": train_name, "response": response})
    return rows


def parse_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text:
        return None
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        try:
            return json.loads(response_text.replace("'", '"'))
        except json.JSONDecodeError:
            return None


def get_train_route(parsed: Dict[str, Any]) -> Optional[List[Any]]:
    route = parsed.get("stations")
    if isinstance(route, list):
        return route
    return None


def get_train_number(row: Dict[str, str], parsed: Optional[Dict[str, Any]]) -> Optional[int]:
    train_no = (row.get("train_no") or "").strip()
    if train_no:
        try:
            return int(train_no)
        except ValueError:
            pass
    if parsed and isinstance(parsed, dict):
        parsed_no = parsed.get("trainNumber")
        if isinstance(parsed_no, (int, str)):
            try:
                return int(parsed_no)
            except ValueError:
                pass
    return None


def build_train_route_update(row: Dict[str, str]) -> Optional[tuple]:
    response_text = row.get("response") or ""
    parsed = parse_response(response_text)
    if not parsed or not isinstance(parsed, dict):
        print(f"Skipping train {row.get('train_no')} because response JSON could not be parsed")
        return None

    route = get_train_route(parsed)
    if route is None:
        print(f"Skipping train {row.get('train_no')} because stations array is missing")
        return None

    train_number = get_train_number(row, parsed)
    if train_number is None:
        print(f"Skipping train because train number is invalid: {row.get('train_no')}")
        return None

    route_json = json.dumps(route, ensure_ascii=False)
    return (route_json, train_number)


def bulk_update_routes(conn, batch: List[tuple]) -> int:
    if not batch:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(
            "UPDATE trains_data SET route = %s WHERE train_number = %s",
            batch,
        )
        conn.commit()
        return cursor.rowcount or 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import RedBus route station arrays into trains_data.route")
    parser.add_argument("--input", default=INPUT_CSV, help="CSV file containing RedBus train responses")
    parser.add_argument("--host", default=DB_CONFIG["host"], help="MySQL host")
    parser.add_argument("--user", default=DB_CONFIG["user"], help="MySQL user")
    parser.add_argument("--password", default=DB_CONFIG["password"], help="MySQL password")
    parser.add_argument("--database", default=DB_CONFIG["database"], help="MySQL database")
    parser.add_argument("--batch-size", type=int, default=200, help="Number of updates to write to the DB in each batch")
    args = parser.parse_args()

    train_rows = load_train_rows(args.input)
    conn = get_db_connection(args.host, args.user, args.password, args.database)
    try:
        ensure_route_column(conn)

        pending_updates: List[tuple] = []
        updated_rows = 0
        processed = 0

        for row in train_rows:
            processed += 1
            update_item = build_train_route_update(row)
            if update_item is None:
                continue
            pending_updates.append(update_item)
            if len(pending_updates) >= args.batch_size:
                updated_rows += bulk_update_routes(conn, pending_updates)
                pending_updates = []

        if pending_updates:
            updated_rows += bulk_update_routes(conn, pending_updates)
    finally:
        conn.close()

    print(f"Done importing route data into trains_data. Processed {processed} rows, updated {updated_rows} trains.")


if __name__ == "__main__":
    main()
