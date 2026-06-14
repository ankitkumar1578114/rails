#!/usr/bin/env python3
import argparse
from collections import Counter
from typing import Dict

import mysql.connector


DB_CONFIG = {
        "host": "bwr2tjeeysysm7um7pfo-mysql.services.clever-cloud.com",
        "user": "ucg3v1n4o6kbgzk2",
        "password": "8CJNC9GDRkkpe5kPvzJw",
        "database": "bwr2tjeeysysm7um7pfo"
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def ensure_weight_column():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("ALTER TABLE stations_data ADD COLUMN weight INT DEFAULT 0")
                conn.commit()
                print("Added stations_data.weight column")
            except mysql.connector.Error as exc:
                if exc.errno == 1060:
                    print("stations_data.weight already exists")
                else:
                    raise


def count_trains_by_station() -> Counter:
    counts = Counter()
    query = """
        SELECT src_stn_code, dstn_stn_code
        FROM trains_data
    """
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            for row in cursor:
                for key in ("src_stn_code", "dstn_stn_code"):
                    code = row.get(key) if row else None
                    if code:
                        counts[code.strip()] += 1
    return counts


def update_station_weights(counts: Counter, reset_missing: bool = True) -> int:
    updated = 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if reset_missing:
                cursor.execute("UPDATE stations_data SET weight = 0")
            for station_code, weight in counts.items():
                cursor.execute(
                    "UPDATE stations_data SET weight = %s WHERE station_code = %s",
                    (weight, station_code),
                )
                if cursor.rowcount:
                    updated += 1
        conn.commit()
    return updated


def write_missing_station_rows(counts: Counter) -> int:
    """Optional: report station codes seen in trains_data not present in stations_data."""
    missing = 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            for station_code in sorted(counts):
                cursor.execute(
                    "SELECT 1 FROM stations_data WHERE station_code = %s LIMIT 1",
                    (station_code,),
                )
                if cursor.fetchone() is None:
                    print(f"Warning: stations_data missing station_code={station_code}")
                    missing += 1
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute station weight from trains_data and store in stations_data.weight")
    parser.add_argument("--ensure-column", action="store_true", help="Create stations_data.weight column if it does not exist")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset weight to 0 before updating")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts without updating the database")
    args = parser.parse_args()

    if args.ensure_column:
        ensure_weight_column()

    counts = count_trains_by_station()
    print(f"Found counts for {len(counts)} station codes")

    if args.dry_run:
        for station_code, weight in counts.most_common(20):
            print(f"{station_code}: {weight}")
        return

    missing = write_missing_station_rows(counts)
    if missing:
        print(f"Warning: {missing} station codes were not present in stations_data")

    updated = update_station_weights(counts, reset_missing=not args.no_reset)
    print(f"Updated weight for {updated} stations_data rows")


if __name__ == "__main__":
    main()
