import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException

from app.config import settings


def authorize_telegram_id(
    init_data: str | None,
    requested_telegram_id: str | None = None,
) -> str:
    if init_data:
        telegram_id = _verified_telegram_id(init_data)
    elif settings.allow_demo_auth or not settings.telegram_bot_token:
        if not requested_telegram_id:
            raise HTTPException(status_code=400, detail="Telegram ID kerak.")
        return requested_telegram_id
    else:
        raise HTTPException(status_code=401, detail="Telegram WebApp auth ma'lumoti yuborilmadi.")

    if requested_telegram_id and str(requested_telegram_id) != telegram_id:
        raise HTTPException(status_code=403, detail="Telegram ID auth ma'lumotiga mos emas.")
    return telegram_id


def _verified_telegram_id(init_data: str) -> str:
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN sozlanmagan.")

    payload = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = payload.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram auth hash topilmadi.")

    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram auth imzosi noto'g'ri.")

    _validate_auth_date(payload.get("auth_date"))
    user_payload = _parse_user_payload(payload.get("user"))
    telegram_id = user_payload.get("id")
    if telegram_id is None:
        raise HTTPException(status_code=401, detail="Telegram user ID topilmadi.")
    return str(telegram_id)


def _validate_auth_date(value: str | None) -> None:
    try:
        auth_date = int(value or "0")
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Telegram auth_date noto'g'ri.") from error

    now = int(time.time())
    if auth_date > now + 60:
        raise HTTPException(status_code=401, detail="Telegram auth_date kelajakda.")
    if settings.telegram_auth_max_age_seconds > 0 and now - auth_date > settings.telegram_auth_max_age_seconds:
        raise HTTPException(status_code=401, detail="Telegram auth muddati tugagan.")


def _parse_user_payload(value: str | None) -> dict:
    if not value:
        raise HTTPException(status_code=401, detail="Telegram user ma'lumoti topilmadi.")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=401, detail="Telegram user JSON noto'g'ri.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Telegram user JSON object emas.")
    return payload
