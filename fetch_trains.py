#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    requests = None

API_URL = "https://search.railyatri.in/v2/mobile/trainsearch.json"

FIELDNAMES = [
    "trainNo",
    "trainName",
    "train_number",
    "train_name",
    "eng_train_name",
    "new_train_number",
    "is_fav",
    "src_stn_code",
    "src_stn_name",
    "dstn_stn_code",
    "dstn_stn_name",
    "from_station_code",
    "from_station_name",
    "to_station_code",
    "to_station_name",
    "train_type",
    "running_days",
    "departure_time",
    "arrival_time",
    "travel_time",
    "classes",
    "via",
    "last_updated",
    "raw_response",
]


def fetch_train_info(train_no, user_id="-1781269775", temp_user_id="-1781269775"):
    params = {
        "q": str(train_no),
        "user_id": user_id,
        "temp_user_id": temp_user_id,
    }

    if requests is not None:
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    from urllib.parse import urlencode
    from urllib.request import urlopen, Request

    url = f"{API_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "python-urllib/3"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_train_data(train_no, payload):
    if not isinstance(payload, dict):
        return None

    # The API may respond with nested train list data or a direct object
    train_data = None
    if "trains" in payload and isinstance(payload["trains"], list) and payload["trains"]:
        train_data = payload["trains"][0]
    elif "train" in payload:
        train_data = payload["train"]
    else:
        train_data = payload

    if not isinstance(train_data, dict):
        return None

    return {
        "trainNo": str(train_data.get("train_number") or train_data.get("new_train_number") or train_no),
        "trainName": train_data.get("train_name") or train_data.get("eng_train_name") or "",
        "train_number": train_data.get("train_number", ""),
        "train_name": train_data.get("train_name", ""),
        "eng_train_name": train_data.get("eng_train_name", ""),
        "new_train_number": train_data.get("new_train_number", ""),
        "is_fav": str(train_data.get("is_fav", "")),
        "src_stn_code": train_data.get("src_stn_code", ""),
        "src_stn_name": train_data.get("src_stn_name", ""),
        "dstn_stn_code": train_data.get("dstn_stn_code", ""),
        "dstn_stn_name": train_data.get("dstn_stn_name", ""),
        "from_station_code": train_data.get("src_stn_code") or train_data.get("from_station_code") or "",
        "from_station_name": train_data.get("src_stn_name") or train_data.get("from_station_name") or "",
        "to_station_code": train_data.get("dstn_stn_code") or train_data.get("to_station_code") or "",
        "to_station_name": train_data.get("dstn_stn_name") or train_data.get("to_station_name") or "",
        "train_type": train_data.get("train_type") or train_data.get("type") or train_data.get("category") or "",
        "running_days": ",".join(train_data.get("running_days", [])) if isinstance(train_data.get("running_days"), list) else str(train_data.get("running_days", "")),
        "departure_time": train_data.get("departure_time") or train_data.get("dept_time") or "",
        "arrival_time": train_data.get("arrival_time") or train_data.get("arr_time") or "",
        "travel_time": train_data.get("travel_time") or train_data.get("duration") or "",
        "classes": ",".join(train_data.get("classes", [])) if isinstance(train_data.get("classes"), list) else str(train_data.get("classes", "")),
        "via": ",".join(train_data.get("via", [])) if isinstance(train_data.get("via"), list) else str(train_data.get("via", "")),
        "last_updated": train_data.get("last_updated") or train_data.get("updated_at") or "",
        "raw_response": str(payload),
    }


def write_header_if_needed(filename):
    exists = os.path.isfile(filename)
    empty = not exists or os.path.getsize(filename) == 0
    if empty:
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
            writer.writeheader()
    return exists


def append_row(filename, row):
    with open(filename, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Fetch train information from RailYatri API and save to CSV.")
    parser.add_argument("--start", type=int, default=17445, help="Starting train number (inclusive). Default: 99999")
    parser.add_argument("--end", type=int, default=1, help="Ending train number (inclusive). Default: 1")
    parser.add_argument("--output", default="train_info.csv", help="CSV output filename. Default: train_info.csv")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay in seconds between requests. Default: 0.2")
    parser.add_argument("--resume", action="store_true", help="Resume from existing CSV file and skip already saved train numbers.")
    args = parser.parse_args()

    if args.start < args.end:
        parser.error("start must be greater than or equal to end when counting downward")

    if requests is None:
        print("WARNING: requests library is not installed. Falling back to urllib.")

    exists = write_header_if_needed(args.output)
    seen_train_numbers = set()
    if args.resume and exists:
        with open(args.output, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get("trainNo"):
                    seen_train_numbers.add(int(row["trainNo"]))

    total = args.start - args.end + 1
    processed = 0
    found = 0

    for train_no in range(args.start, args.end - 1, -1):
        processed += 1
        if train_no in seen_train_numbers:
            print(f"Skipping already recorded train {train_no}")
            continue

        print(f"Fetching {train_no} ({processed}/{total})...")
        try:
            payload = fetch_train_info(train_no)
        except Exception as exc:
            print(f"  ERROR fetching train {train_no}: {exc}")
            time.sleep(min(args.delay * 2, 5.0))
            continue

        row = normalize_train_data(train_no, payload)
        if row is None or not row.get("trainName"):
            print(f"  No valid train data for {train_no}")
        else:
            append_row(args.output, row)
            found += 1
            print(f"  Saved train {train_no}: {row['trainName']}")

        time.sleep(args.delay)

    print(f"Done. Total scanned: {processed}, records saved: {found}")


if __name__ == "__main__":
    main()
