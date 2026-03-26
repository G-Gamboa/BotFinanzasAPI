
from datetime import datetime

def ensure_fecha_text(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%d")
    return value

def parse_money_text(value: str) -> float:
    clean = value.replace(",", "").replace("Q", "").strip()
    return float(clean)
