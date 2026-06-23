from api.repos.db import get_db_connection
from typing import Any, Dict, List
from api.utils.json import parse_json_string_list


def fetch_trains_by_query(query_value: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM trains
        WHERE train_number_string LIKE %s
           OR train_name LIKE %s
        LIMIT 5
    """
    like_value = f"%{query_value}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value, like_value))
            return cursor.fetchall()
        

def load_station_trains(station_code: str) -> List[str]:
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT trains FROM stations WHERE station_code = %s LIMIT 1", (station_code,))
            row = cursor.fetchone()
            if not row:
                return []
            return parse_json_string_list(row.get("trains"))
        
def load_region_trains(region_code: str) -> List[str]:
    normalized_region = str(region_code).strip().upper()
    if not normalized_region:
        return []

    query = """
        SELECT trains
        FROM stationsV2
        WHERE UPPER(TRIM(COALESCE(region, ''))) = %s
    """
    trains: List[str] = []
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (normalized_region,))
            for row in cursor.fetchall():
                trains.extend(parse_json_string_list(row.get("trains")))
    return trains