from db import get_db_connection
from typing import Any, Dict, List
def fetch_stations_by_name(name: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_name LIKE %s
        ORDER BY weight DESC
    """
    like_value = f"%{name}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()
        
def fetch_stations_by_code(code: str) -> List[Dict[str, Any]]:
    query = """
        SELECT *
        FROM stations
        WHERE station_code LIKE %s
        ORDER By weight desc

    """
    like_value = f"%{code}%"
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query, (like_value,))
            return cursor.fetchall()

