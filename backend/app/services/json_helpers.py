import json
from typing import Any, List, Optional


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def loads_dict(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}

