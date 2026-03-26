import re
import unicodedata
from datetime import date, datetime, timedelta


def norm(value: str) -> str:
    s = str(value).strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def norm_key(value: str) -> str:
    return norm(value)


def pick(row: dict, *candidates: str):
    normalized = {norm(k): v for k, v in row.items()}
    for candidate in candidates:
        key = norm(candidate)
        if key in normalized:
            return normalized[key]
    return None


def to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    s = re.sub(r'[^0-9.,\-]', '', s)
    if not s:
        return 0.0

    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')

    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_fecha(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def ensure_fecha_text(value: str) -> str:
    fecha = parse_fecha(value)
    if not fecha:
        raise ValueError('Fecha inválida. Usa YYYY-MM-DD.')
    return fecha.strftime('%Y-%m-%d')


def is_positive_amount(value) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


def month_range(today: date):
    start = today.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, next_month


def week_range(today: date):
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=7)
