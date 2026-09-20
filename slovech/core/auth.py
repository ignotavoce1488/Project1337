"""Telegram signatures are credentials, accepted exclusively in request headers."""

import hashlib
import hmac
import json
import time
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, Query

from slovech.core.config import Settings, get_settings


def verify_telegram_init_data(raw: str, token: str, max_age: int = 3600) -> dict | None:
    if not raw or not token or len(raw) > 16384:
        return None
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        parsed = dict(pairs)
        if len(pairs) != len(parsed):
            return None
        received = parsed.pop("hash")
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        check = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received, expected):
            return None
        age = time.time() - int(parsed["auth_date"])
        if age < -30 or age > max_age:
            return None
        user = json.loads(parsed["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            return None
        return user
    except (ValueError, KeyError, TypeError, OverflowError):
        return None


def get_authenticated_user_id(
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_init_data: str | None = Header(None),
    x_admin_secret: str | None = Header(None),
    user_id: str | None = Query(None),
) -> str:
    if x_telegram_init_data:
        user = verify_telegram_init_data(
            x_telegram_init_data, settings.bot_token.get_secret_value(), settings.auth_max_age
        )
        if user:
            return str(user["id"])
    elif x_admin_secret and settings.admin_secret.get_secret_value():
        if hmac.compare_digest(x_admin_secret, settings.admin_secret.get_secret_value()):
            if user_id is not None and (
                not user_id.isascii()
                or not user_id.isdigit()
                or int(user_id) <= 0
                or len(user_id) > 20
            ):
                raise HTTPException(400, "Invalid user ID")
            return str(int(user_id)) if user_id else str(settings.admin_user_id)
    raise HTTPException(401, "Откройте приложение через Telegram для авторизации.")
