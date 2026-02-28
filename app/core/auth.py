from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Literal

from app.core.config import settings

Role = Literal["promotion", "procurement", "document", "admin"]

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def create_token(role: Role) -> str:
    # payload: role|iat
    payload = f"{role}|{int(time.time())}".encode("utf-8")
    sig = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url(payload)}.{_b64url(sig)}"

def verify_token(token: str) -> Role:
    try:
        p_b64, s_b64 = token.split(".", 1)
        payload = _b64url_decode(p_b64)
        sig = _b64url_decode(s_b64)

        expected = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")

        role_str, _iat = payload.decode("utf-8").split("|", 1)
        if role_str not in ("promotion", "procurement", "document", "admin"):
            raise ValueError("bad role")

        return role_str  # type: ignore[return-value]
    except Exception:
        raise ValueError("invalid token")