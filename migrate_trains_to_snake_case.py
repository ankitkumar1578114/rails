#!/usr/bin/env python3
import argparse
import json
import re
from typing import Any, Dict, List, Optional

import mysql.connector

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "mydb",
}

JSON_COLUMNS = {"DaysOfRun", "Classes", "Schedule", "days_of_run", "classes", "schedule"}


def get_db_connection(host: str, user: str, password: str, database: str):
    return mysql.connector.connect(host=host, user=user, password=password, database=database)


def camel_to_snake(name: str) -> str:
    if not name:
        return name
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.replace("-", "_").lower()


def to_camel_case(name: str) -> str:
    if not isinstance(name, str) or not name:
        return name
    if "_" in name:
        parts = name.split("_")
        return parts[0].lower() + "".join(part.capitalize() for part in parts[1:])
    return name[0].lower() + name[1:] if name[0].isupper() else name


def transform_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_camel_case(key): transform_json_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [transform_json_value(item) for item in value]
    return value


def parse_json_column(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def ensure_target_table(conn) -> None:
    create_sql = """
        CREATE TABLE IF NOT EXISTS trains_snake (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            train_no INT,
            train_name VARCHAR(255),
            train_number_string VARCHAR(50),
            train_type VARCHAR(50),
            source VARCHAR(255),
            destination VARCHAR(255),
            source_code VARCHAR(50),
            destination_code VARCHAR(50),
            days_of_run JSON,
            classes JSON,
            schedule JSON,
            total_duration INT,
            total_distance VARCHAR(100),
            total_number_of_stops VARCHAR(50),
            created_at TIMESTAMP NULL,
            updated_at TIMESTAMP NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    with conn.cursor() as cursor:
        cursor.execute(create_sql)
        conn.commit()


def read_source_rows(conn) -> List[Dict[str, Any]]:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM trains")
        return cursor.fetchall()


def build_target_row(row: Dict[str, Any]) -> Dict[str, Any]:
    target_row: Dict[str, Any] = {}
    for key, value in row.items():
        snake_key = camel_to_snake(key)
        if snake_key in {"id", "train_no", "train_name", "train_number_string", "train_type", "source", "destination", "source_code", "destination_code", "total_duration", "total_distance", "total_number_of_stops", "created_at", "updated_at"}:
            target_row[snake_key] = value
            continue

        if snake_key in {"days_of_run", "classes", "schedule"}:
            parsed = parse_json_column(value)
            if parsed is None:
                target_row[snake_key] = None
            else:
                target_row[snake_key] = json.dumps(transform_json_value(parsed), ensure_ascii=False)
            continue

        # Keep other columns, if any, in snake_case as raw values.
        target_row[snake_key] = value

    return target_row


def upsert_target_rows(conn, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return

    columns = [
        "id",
        "train_no",
        "train_name",
        "train_number_string",
        "train_type",
        "source",
        "destination",
        "source_code",
        "destination_code",
        "days_of_run",
        "classes",
        "schedule",
        "total_duration",
        "total_distance",
        "total_number_of_stops",
        "created_at",
        "updated_at",
    ]
    placeholders = ", ".join(["%({})s".format(col) for col in columns])
    insert_columns = ", ".join(columns)
    update_clause = ", ".join([f"{col}=VALUES({col})" for col in columns if col != "id"])
    sql = f"INSERT INTO trains_snake ({insert_columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_clause}"
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transfer trains table to snake_case columns and camelCase JSON contents.")
    parser.add_argument("--host", default=DB_CONFIG["host"], help="MySQL host")
    parser.add_argument("--user", default=DB_CONFIG["user"], help="MySQL user")
    parser.add_argument("--password", default=DB_CONFIG["password"], help="MySQL password")
    parser.add_argument("--database", default=DB_CONFIG["database"], help="MySQL database")
    args = parser.parse_args()

    with get_db_connection(args.host, args.user, args.password, args.database) as conn:
        ensure_target_table(conn)
        source_rows = read_source_rows(conn)
        if not source_rows:
            print("No rows found in trains table.")
            return

        target_rows = [build_target_row(row) for row in source_rows]
        upsert_target_rows(conn, target_rows)
        print(f"Migrated {len(target_rows)} rows from trains to trains_snake.")


if __name__ == "__main__":
    main()
