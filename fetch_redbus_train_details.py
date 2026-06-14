#!/usr/bin/env python3
import argparse
import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None

API_URL = "https://www.redbus.in/railways/api/getLtsDetails"
INPUT_CSV = "train_info.csv"
OUTPUT_CSV = "redbus_train_details.csv"
FIELDNAMES = ["train_no", "train_name", "response"]


def fetch_redbus_details(train_no: str, timeout: int = 30) -> Dict:
    params = {"trainNo": train_no}
    if requests is not None:
        response = requests.get(API_URL, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()

    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    url = f"{API_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "python-urllib/3.11"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def write_header_if_needed(filename: str) -> bool:
    exists = os.path.isfile(filename)
    if not exists:
        with open(filename, "w", newline="", encoding="utf-8") as out_file:
            writer = csv.DictWriter(out_file, fieldnames=FIELDNAMES)
            writer.writeheader()
    return exists


def append_row(filename: str, row: Dict[str, str]) -> None:
    with open(filename, "a", newline="", encoding="utf-8") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=FIELDNAMES)
        writer.writerow(row)


def load_done_train_numbers(filename: str) -> set:
    done = set()
    if not os.path.isfile(filename):
        return done
    with open(filename, newline="", encoding="utf-8") as in_file:
        reader = csv.DictReader(in_file)
        for row in reader:
            train_no = (row.get("train_no") or "").strip()
            if train_no:
                done.add(train_no)
    return done


def read_input_train_rows(filename: str) -> list[Dict[str, str]]:
    with open(filename, newline="", encoding="utf-8") as in_file:
        reader = csv.DictReader(in_file)
        return list(reader)


def fetch_train_response(train_no: str, train_name: str, timeout: int = 30) -> Dict[str, str]:
    try:
        payload = fetch_redbus_details(train_no, timeout=timeout)
        response_text = json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        response_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
        print(f"  ERROR for {train_no}: {exc}")

    return {
        "train_no": train_no,
        "train_name": train_name,
        "response": response_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch RedBus train details for stored trains and save to CSV.")
    parser.add_argument("--input", default=INPUT_CSV, help="Input CSV containing stored trains. Default: train_info.csv")
    parser.add_argument("--output", default=OUTPUT_CSV, help="Output CSV to write RedBus responses. Default: redbus_train_details.csv")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay in seconds between batches. Default: 0.2")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of parallel requests to make at once. Default: 10")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds for each request. Default: 30")
    parser.add_argument("--resume", action="store_true", help="Resume from existing output file and skip already processed train numbers.")
    args = parser.parse_args()

    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")

    if not os.path.isfile(args.input):
        raise FileNotFoundError(f"Input file not found: {args.input}")

    train_rows = read_input_train_rows(args.input)
    if not train_rows:
        print(f"No rows found in {args.input}")
        return

    done_train_numbers = set()
    if args.resume:
        done_train_numbers = load_done_train_numbers(args.output)
        print(f"Resuming: {len(done_train_numbers)} train numbers already processed")

    write_header_if_needed(args.output)

    rows_to_fetch = []
    for row in reversed(train_rows):
        train_no = (row.get("trainNo") or row.get("train_number") or "").strip()
        train_name = (row.get("trainName") or row.get("train_name") or "").strip()
        if not train_no:
            continue
        if args.resume and train_no in done_train_numbers:
            continue
        rows_to_fetch.append((train_no, train_name))

    if not rows_to_fetch:
        print("No new trains to process.")
        return

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for start in range(0, len(rows_to_fetch), args.concurrency):
            batch = rows_to_fetch[start : start + args.concurrency]
            print(f"Fetching batch {start // args.concurrency + 1} of {((len(rows_to_fetch) - 1) // args.concurrency) + 1}")
            futures = [executor.submit(fetch_train_response, train_no, train_name, args.timeout) for train_no, train_name in batch]
            for future in futures:
                result_row = future.result()
                append_row(args.output, result_row)
            if args.delay and start + args.concurrency < len(rows_to_fetch):
                time.sleep(args.delay)

    print(f"Done. Output written to {args.output}")


if __name__ == "__main__":
    main()
