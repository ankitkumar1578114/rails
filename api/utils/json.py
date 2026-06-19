import json

from typing import Any, List

def parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def parse_json_string_list(value: Any) -> List[str]:
    return [str(item) for item in parse_json_list(value) if item is not None]
