import argparse
import html
import json
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:
    requests = None


def clean_text(value):
    if value is None:
        return ""
    return " ".join(value.split())


class TableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = None
        self.current_row = None
        self.current_cell = None
        self.in_table = False
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            if self.current_table is not None:
                self.tables.append(self.current_table)
            self.in_table = False
            self.current_table = None
        elif tag == "tr" and self.in_row:
            if self.current_row is not None:
                self.current_table.append(self.current_row)
            self.in_row = False
            self.current_row = None
        elif tag in ("td", "th") and self.in_cell:
            cell_text = clean_text("".join(self.current_cell))
            self.current_row.append(cell_text)
            self.in_cell = False
            self.current_cell = None

    def handle_data(self, data):
        if self.in_cell and data:
            self.current_cell.append(data)


class TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_content = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_content += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip_content > 0:
            self.skip_content -= 1

    def handle_data(self, data):
        if self.skip_content == 0 and data:
            self.parts.append(data)

    def text(self):
        return clean_text(" ".join(self.parts))


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    if requests is not None:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP error while fetching {url}: {exc}") from exc

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def parse_station_table(html_text):
    parser = TableHTMLParser()
    parser.feed(html_text)
    parser.close()

    run_table = None
    for table in parser.tables:
        if not table:
            continue
        header = table[0]
        header_text = " ".join(cell.lower() for cell in header)
        if "station" in header_text and ("arrival" in header_text or "departure" in header_text or "status" in header_text):
            run_table = table
            break

    if run_table is None and parser.tables:
        run_table = parser.tables[0]

    if not run_table or len(run_table) < 2:
        return []

    headers = [cell if cell else f"column_{idx + 1}" for idx, cell in enumerate(run_table[0])]
    stations = []
    for row in run_table[1:]:
        if len(row) < 2:
            continue
        row_data = {}
        for idx, cell in enumerate(row):
            key = headers[idx] if idx < len(headers) else f"column_{idx + 1}"
            row_data[key] = cell
        stations.append(row_data)

    return stations


def parse_running_status(html_text):
    station_rows = []
    for match in re.finditer(r'<div\s+class="row rs__station-row flexy"\s*>', html_text, re.I):
        start = match.start()
        depth = 0
        i = start
        block = None
        while i < len(html_text):
            if html_text.startswith("<div", i):
                depth += 1
                i += 4
            elif html_text.startswith("</div>", i):
                depth -= 1
                i += 6
                if depth == 0:
                    block = html_text[start:i]
                    break
            else:
                i += 1

        if block is None:
            continue

        station_name = re.search(r'class="rs__station-name ellipsis">\s*([^<]+?)\s*<', block)
        day_date_block = re.search(r'<div class="col-xs-3">(.*?)</div>', block, re.S)
        day_text = ""
        date_text = ""
        if day_date_block:
            spans = re.findall(r'<span>([^<]+)</span>', day_date_block.group(1))
            if len(spans) >= 1:
                day_text = clean_text(spans[0])
            if len(spans) >= 2:
                date_text = clean_text(spans[1])

        xs2_blocks = re.findall(r'<div class="col-xs-2">(.*?)</div>', block, re.S)
        arrival_time = ""
        departure_time = ""
        if len(xs2_blocks) >= 1:
            arrival_match = re.search(r'<span>\s*([^<]*)\s*</span>', xs2_blocks[0], re.S)
            if arrival_match:
                arrival_time = clean_text(arrival_match.group(1))
        if len(xs2_blocks) >= 2:
            departure_match = re.search(r'<span>\s*([^<]*)\s*</span>', xs2_blocks[1], re.S)
            if departure_match:
                departure_time = clean_text(departure_match.group(1))

        delay_match = re.search(r'class="rs__station-delay[^"]*"[^>]*>(.*?)</div>', block, re.S)
        delay_text = clean_text(delay_match.group(1)) if delay_match else ""
        if not delay_text:
            delay_guess = re.search(r'>(On time|Expected .*?|Delay by .*?)<', block, re.I)
            delay_text = clean_text(delay_guess.group(1)) if delay_guess else ""

        # if arrival_time:
        #     status_code = f"Arrived {arrival_time}"
        # elif departure_time:
        #     status_code = f"Departs {departure_time}"
        # else:
        #     status_code = "Scheduled"
        # status_code = "Scheduled"
        # if delay_text:
        #     status_code = f"{status_code} ({delay_text})"

        station_rows.append({
            "station_name": station_name.group(1).strip() if station_name else "",
            "day": day_text,
            "date": date_text,
            "arrival": arrival_time,
            "departure": departure_time,
            "delay": delay_text,
            "status_code": delay_text,
        })

    return station_rows


def format_table(rows, headers):
    if not rows or not headers:
        return ""

    widths = [max(len(str(header)), max(len(str(row.get(header, ""))) for row in rows)) for header in headers]
    header_line = " | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
    separator = "-+-".join("-" * widths[idx] for idx in range(len(headers)))
    row_lines = []
    for row in rows:
        row_lines.append(" | ".join(str(row.get(header, "")).ljust(widths[idx]) for idx, header in enumerate(headers)))

    return "\n".join([header_line, separator] + row_lines)


def find_live_status(html_text):
    text = re.sub(r"<script.*?>.*?</script>|<style.*?>.*?</style>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = clean_text(html.unescape(text))

    patterns = [
        r"\b(live(?:ly)? status|running status|current status|estimated arrival|estimated departure|delayed|on time|expected arrival|expected departure)\b.*",
        r".*\b(status|arrival|departure|delay)\b.*",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            candidate = match.group(0)
            candidate = candidate.strip(" .\n")
            if candidate:
                return candidate
    return ""


def extract_title(html_text):
    match = re.search(r"<title>(.*?)</title>", html_text, re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def fetch_train_status(train_no, date=None):
    url = f"https://www.confirmtkt.com/train-running-status/{train_no}"
    if date:
        date_value = date.strip()
        if date_value:
            url = f"{url}?Date={quote(date_value, safe='')}"

    html_text = fetch_html(url)

    train_info = {
        "train_number": str(train_no),
        "date": date,
        "page_title": extract_title(html_text),
        "source_url": url,
    }

    station_status = parse_running_status(html_text)

    return {
        "train_info": train_info,
        "station_status": station_status,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch live train status from confirmtkt.com")
    parser.add_argument("train_no", help="Train number to fetch live status for")
    parser.add_argument("--date", help="Optional date to include in the request, e.g. 11-Jun-2026")
    parser.add_argument("--json", action="store_true", help="Print output as JSON")
    args = parser.parse_args()

    status = fetch_train_status(args.train_no, args.date)
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(f"Train: {status['train_info'].get('train_number')}")
        if status["train_info"].get("page_title"):
            print(f"Page title: {status['train_info']['page_title']}")
        if status["station_status"]:
            print("Live station status:")
            headers = ["station_name", "status_code", "arrival", "departure", "delay"]
            print(format_table(status["station_status"], headers))
        else:
            print("No station data found.")
