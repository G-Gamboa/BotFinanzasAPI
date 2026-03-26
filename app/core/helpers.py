
from datetime import datetime


def parse_iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("La fecha debe tener formato YYYY-MM-DD") from exc


def norm_key(value: str) -> str:
    return (value or "").strip().lower()
