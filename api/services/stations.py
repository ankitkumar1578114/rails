
from typing import Any, Dict, List

from repos.stations import fetch_stations_by_name, fetch_stations_by_code

def getStationsByNameOrCode(search_term: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_codes = set()

        name_results = fetch_stations_by_name(search_term)
        for row in name_results:
            results.append(row)
            if "code" in row:
                seen_codes.add(row["code"])
            if len(results) >= 5:
                return results

        code_results = fetch_stations_by_code(search_term)
        for row in code_results:
            if row.get("code") not in seen_codes:
                results.append(row)
                if len(results) >= 5:
                    break

        return results
