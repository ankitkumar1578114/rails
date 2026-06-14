#!/usr/bin/env python3
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

import requests
import mysql.connector

API_URL = "https://www.redbus.in/railways/api/getTrainScheduleDetails"

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "mydb",
    # "host": "bwr2tjeeysysm7um7pfo-mysql.services.clever-cloud.com",
    # "user": "ucg3v1n4o6kbgzk2",
    # "password": "8CJNC9GDRkkpe5kPvzJw",
    # "database": "bwr2tjeeysysm7um7pfo",
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def ensure_trains_table(conn) -> None:
    create_sql = """
        CREATE TABLE IF NOT EXISTS trains (
            id INT NOT NULL AUTO_INCREMENT UNIQUE,
            TrainNo INT NOT NULL,
            TrainName VARCHAR(255) NOT NULL,
            TrainNumberString VARCHAR(50) NOT NULL,
            TrainType VARCHAR(50),
            Source VARCHAR(255),
            Destination VARCHAR(255),
            SourceCode VARCHAR(50),
            DestinationCode VARCHAR(50),
            DaysOfRun JSON,
            Classes JSON,
            Schedule JSON,
            TotalDuration INT,
            TotalDistance VARCHAR(100),
            TotalNumberOfStops VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unique_train_no (TrainNo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    with conn.cursor() as cursor:
        cursor.execute(create_sql)
        cursor.execute("SHOW COLUMNS FROM trains LIKE 'id'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE trains ADD COLUMN id INT NOT NULL AUTO_INCREMENT UNIQUE FIRST")
        conn.commit()


def fetch_train_schedule(train_no: int, timeout: int = 30) -> Dict[str, Any]:
    response = requests.get(API_URL, params={"trainNo": train_no}, timeout=timeout, headers={"User-Agent": "python-requests/2.x"})
    response.raise_for_status()
    return response.json()


def build_train_row(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "TrainNo": int(data.get("TrainNo") or data.get("trainNo") or 0),
        "TrainName": data.get("TrainName") or data.get("trainName") or "",
        "TrainNumberString": data.get("TrainNumberString") or str(data.get("TrainNo") or ""),
        "TrainType": data.get("TrainType") or "",
        "Source": data.get("Source") or "",
        "Destination": data.get("Destination") or "",
        "SourceCode": data.get("SourceCode") or "",
        "DestinationCode": data.get("DestinationCode") or "",
        "DaysOfRun": json.dumps(data.get("DaysOfRun") or {}, ensure_ascii=False),
        "Classes": json.dumps(data.get("Classes") or [], ensure_ascii=False),
        "Schedule": json.dumps(data.get("Schedule") or [], ensure_ascii=False),
        "TotalDuration": int(data.get("TotalDuration") or 0),
        "TotalDistance": data.get("TotalDistance") or "",
        "TotalNumberOfStops": str(data.get("TotalNumberOfStops") or ""),
    }


def insert_or_update_train(conn, train_row: Dict[str, Any]) -> None:
    sql = """
        INSERT INTO trains (
            TrainNo,
            TrainName,
            TrainNumberString,
            TrainType,
            Source,
            Destination,
            SourceCode,
            DestinationCode,
            DaysOfRun,
            Classes,
            Schedule,
            TotalDuration,
            TotalDistance,
            TotalNumberOfStops
        ) VALUES (
            %(TrainNo)s,
            %(TrainName)s,
            %(TrainNumberString)s,
            %(TrainType)s,
            %(Source)s,
            %(Destination)s,
            %(SourceCode)s,
            %(DestinationCode)s,
            %(DaysOfRun)s,
            %(Classes)s,
            %(Schedule)s,
            %(TotalDuration)s,
            %(TotalDistance)s,
            %(TotalNumberOfStops)s
        )
        ON DUPLICATE KEY UPDATE
            TrainName = VALUES(TrainName),
            TrainNumberString = VALUES(TrainNumberString),
            TrainType = VALUES(TrainType),
            Source = VALUES(Source),
            Destination = VALUES(Destination),
            SourceCode = VALUES(SourceCode),
            DestinationCode = VALUES(DestinationCode),
            DaysOfRun = VALUES(DaysOfRun),
            Classes = VALUES(Classes),
            Schedule = VALUES(Schedule),
            TotalDuration = VALUES(TotalDuration),
            TotalDistance = VALUES(TotalDistance),
            TotalNumberOfStops = VALUES(TotalNumberOfStops)
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, train_row)
        conn.commit()


def get_train_numbers_from_trains_data(conn) -> list[int]:
    query = "SELECT DISTINCT train_number FROM trains_data WHERE train_number IS NOT NULL"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    train_numbers: list[int] = []
    for row in rows:
        if not row:
            continue
        value = row[0]
        try:
            train_numbers.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(train_numbers))


def fetch_and_build_train_row(train_no: int, timeout: int = 30):
    try:
        schedule_data = fetch_train_schedule(train_no, timeout=timeout)
        train_row = build_train_row(schedule_data)
        return train_no, train_row, None
    except Exception as exc:
        return train_no, None, exc


def process_bulk_train_numbers(conn, train_numbers: list[int], timeout: int = 30, batch_size: int = 20, concurrency: int = 20) -> None:
    total = len(train_numbers)
    if total == 0:
        print("No train numbers found in trains_data")
        return

    ensure_trains_table(conn)
    for start in range(0, total, batch_size):
        batch = train_numbers[start : start + batch_size]
        print(f"Processing batch {start // batch_size + 1} of {(total - 1) // batch_size + 1} ({len(batch)} trains)")

        with ThreadPoolExecutor(max_workers=min(len(batch), concurrency)) as executor:
            future_to_train = {
                executor.submit(fetch_and_build_train_row, train_no, timeout): train_no for train_no in batch
            }
            for future in as_completed(future_to_train):
                train_no = future_to_train[future]
                try:
                    train_no, train_row, exc = future.result()
                except Exception as exc:
                    print(f"    Failed to fetch/update trainNo={train_no}: {exc}")
                    continue

                if exc is not None:
                    print(f"    Failed to fetch/update trainNo={train_no}: {exc}")
                    continue

                if train_row["TrainNo"] == 0:
                    print(f"    Skipping trainNo={train_no}: invalid response")
                    continue

                try:
                    insert_or_update_train(conn, train_row)
                    print(f"    Stored trainNo={train_row['TrainNo']}")
                except Exception as exc:
                    print(f"    Failed to insert trainNo={train_no}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch RedBus train schedule and store it in the trains table.")
    parser.add_argument("--train-no", type=int, help="Train number to fetch from redBus API")
    parser.add_argument("--bulk", action="store_true", help="Fetch train numbers from trains_data and process them in batches")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size for bulk redbus fetches")
    parser.add_argument("--concurrency", type=int, default=20, help="Number of parallel RedBus API calls to make")
    parser.add_argument("--host", default=DB_CONFIG["host"], help="MySQL host")
    parser.add_argument("--user", default=DB_CONFIG["user"], help="MySQL user")
    parser.add_argument("--password", default=DB_CONFIG["password"], help="MySQL password")
    parser.add_argument("--database", default=DB_CONFIG["database"], help="MySQL database")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    args = parser.parse_args()

    connection_config = {
        "host": args.host,
        "user": args.user,
        "password": args.password,
        "database": args.database,
    }

    with mysql.connector.connect(**connection_config) as conn:
        if args.bulk:
            train_numbers = get_train_numbers_from_trains_data(conn)
            print(f"Found {len(train_numbers)} train numbers in trains_data")
            process_bulk_train_numbers(
                conn,
                train_numbers,
                timeout=args.timeout,
                batch_size=args.batch_size,
                concurrency=args.concurrency,
            )
            return

        if args.train_no is None:
            parser.error("Either --train-no or --bulk must be provided")

        train_no = args.train_no
        print(f"Fetching train schedule for trainNo={train_no}")
        schedule_data = fetch_train_schedule(train_no, timeout=args.timeout)
        train_row = build_train_row(schedule_data)
        ensure_trains_table(conn)
        insert_or_update_train(conn, train_row)
        print(f"Stored train schedule for TrainNo={train_row['TrainNo']} in trains table")


if __name__ == "__main__":
    main()
