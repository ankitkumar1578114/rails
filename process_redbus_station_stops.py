#!/usr/bin/env python3
import argparse
import csv
import json
import os
from collections import defaultdict
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


def ensure_station_table(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                code VARCHAR(255),
                trains JSON,
                weight INT DEFAULT 0
            )
            """
        )
        conn.commit()


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
                # Skip header row when present
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


def get_station(conn, code: str) -> Optional[Dict[str, Any]]:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id, name, code, trains, weight FROM stations WHERE code = %s LIMIT 1", (code,))
        return cursor.fetchone()


def insert_station(conn, code: str, name: str) -> Dict[str, Any]:
    trains_json = json.dumps([])
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO stations (name, code, trains, weight) VALUES (%s, %s, %s, %s)",
            (name, code, trains_json, 0),
        )
        conn.commit()
        station_id = cursor.lastrowid
    return {"id": station_id, "name": name, "code": code, "trains": [], "weight": 0}


def update_station(conn, code: str, name: str, weight: int, trains: List[str]) -> None:
    trains_json = json.dumps(trains, ensure_ascii=False)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE stations SET name = %s, weight = %s, trains = %s WHERE code = %s",
            (name, weight, trains_json, code),
        )
    conn.commit()


def normalize_station_item(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    code = item.get("stationCode") or item.get("station_code")
    name = item.get("stationName") or item.get("station_name")
    if not code:
        return None
    return {"code": str(code).strip(), "name": str(name).strip() if name else ""}


def process_station_entries(conn, station_cache: Dict[str, Dict[str, Any]], train_number: str, station: Dict[str, Any]) -> None:
    normal_station = normalize_station_item(station)
    if not normal_station:
        return

    code = normal_station["code"]
    name = normal_station["name"]

    entry = station_cache.get(code)
    if entry is None:
        entry = get_station(conn, code)
        if entry is None:
            entry = insert_station(conn, code, name)
        else:
            entry["trains"] = entry["trains"] or []
            if isinstance(entry["trains"], str):
                try:
                    entry["trains"] = json.loads(entry["trains"])
                except Exception:
                    entry["trains"] = []
        station_cache[code] = entry

    if train_number not in entry["trains"]:
        entry["trains"].append(train_number)
        entry["weight"] = (entry["weight"] or 0) + 1
        entry["name"] = name or entry["name"]
        update_station(conn, code, entry["name"], entry["weight"], entry["trains"])


def ensure_only_station_exists(conn, station_cache: Dict[str, Dict[str, Any]], station: Dict[str, Any]) -> None:
    normalized = normalize_station_item(station)
    if not normalized:
        return
    code = normalized["code"]
    name = normalized["name"]
    if code in station_cache:
        return
    entry = get_station(conn, code)
    if entry is None:
        insert_station(conn, code, name)
        station_cache[code] = {"code": code, "name": name, "trains": [], "weight": 0}
    else:
        station_cache[code] = entry


def process_train_row(conn, station_cache: Dict[str, Dict[str, Any]], row: Dict[str, str]) -> None:
    train_number = (row.get("train_no") or "").strip()
    if not train_number:
        return
    response_text = row.get("response") or ""
    parsed = parse_response(response_text)
    if not parsed or not isinstance(parsed, dict):
        return

    stations = parsed.get("stations")
    if not isinstance(stations, list):
        return

    for station in stations:
        process_station_entries(conn, station_cache, train_number, station)
        intermediate = station.get("intermediateStations") or station.get("intermediate_stations")
        if isinstance(intermediate, list):
            for intermediate_station in intermediate:
                ensure_only_station_exists(conn, station_cache, intermediate_station)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process redbus_train_details.csv and populate local stations table.")
    parser.add_argument("--input", default=INPUT_CSV, help="CSV file with train responses (default redbus_train_details.csv)")
    parser.add_argument("--host", default=DB_CONFIG["host"], help="MySQL host")
    parser.add_argument("--user", default=DB_CONFIG["user"], help="MySQL user")
    parser.add_argument("--password", default=DB_CONFIG["password"], help="MySQL password")
    parser.add_argument("--database", default=DB_CONFIG["database"], help="MySQL database")
    args = parser.parse_args()

    train_rows = load_train_rows(args.input)
    conn = get_db_connection(args.host, args.user, args.password, args.database)
    try:
        ensure_station_table(conn)
        station_cache: Dict[str, Dict[str, Any]] = {}
        for row in train_rows:
            process_train_row(conn, station_cache, row)
    finally:
        conn.close()

    print("Done processing redbus train station data.")


if __name__ == "__main__":
    main()
