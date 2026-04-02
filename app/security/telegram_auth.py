import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from app.config import get_settings


def _build_data_check_string(init_data_raw: str) -> tuple[str, str]:
    pairs = parse_qsl(init_data_raw, keep_blank_values=True)

    data = {}
    received_hash = None

    for key, value in pairs:
        if key == "hash":
            received_hash = value
        else:
            data[key] = value

    if not received_hash:
        raise HTTPException(status_code=401, detail="initData inválido: falta hash.")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items(), key=lambda x: x[0])
    )

    return data_check_string, received_hash


def _calculate_hash(bot_token: str, data_check_string: str) -> str:
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    return hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def validate_init_data(init_data_raw: str, bot_token: str, max_age_seconds: int = 3600) -> dict:
    data_check_string, received_hash = _build_data_check_string(init_data_raw)
    calculated_hash = _calculate_hash(bot_token, data_check_string)

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="initData inválido: firma incorrecta.")

    parsed = dict(parse_qsl(init_data_raw, keep_blank_values=True))

    auth_date_raw = parsed.get("auth_date")
    if not auth_date_raw:
        raise HTTPException(status_code=401, detail="initData inválido: falta auth_date.")

    try:
        auth_ts = int(auth_date_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="initData inválido: auth_date incorrecto.")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts - auth_ts > max_age_seconds:
        raise HTTPException(status_code=401, detail="initData expirado.")

    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="initData inválido: falta user.")

    try:
        user_data = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="initData inválido: user corrupto.")

    return {
        "user": user_data,
        "auth_date": auth_ts,
        "query_id": parsed.get("query_id"),
        "start_param": parsed.get("start_param"),
    }


def extract_bearer_tma(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Falta Authorization.")

    prefix = "tma "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization inválido.")

    raw = authorization[len(prefix):].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Authorization vacío.")

    return raw


def get_current_telegram_auth(authorization: str | None = Header(default=None)):
    settings = get_settings()

    init_data_raw = extract_bearer_tma(authorization)
    return validate_init_data(
        init_data_raw=init_data_raw,
        bot_token=settings.telegram_bot_token,
        max_age_seconds=3600,
    )