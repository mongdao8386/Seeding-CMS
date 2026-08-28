"""Xac thuc cho API.

Mot token dung chung, dat trong .env. Du cho mot cong cu noi bo vai nguoi dung, va
khong keo theo bang users, phien dang nhap, quen mat khau - nhung thu chi lam tang be
mat tan cong ma khong giai quyet duoc gi o quy mo nay.

FAIL-CLOSED: chua dat token thi API tu choi moi thu, chu khong chay mo. Mot he thong
giu cookie jar cua hang chuc tai khoan ma "tam thoi de mo" la cach mat sach.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from seeding.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def require_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()

    if not settings.api_token:
        raise HTTPException(
            503,
            "No API_TOKEN is set in .env. Generate one with:\n    python scripts/gen_api_token.py",
        )

    if not authorization:
        raise HTTPException(401, "Missing header: Authorization: Bearer <token>")

    # compare_digest de khong lo thong tin qua thoi gian so sanh.
    if not secrets.compare_digest(authorization, f"Bearer {settings.api_token}"):
        raise HTTPException(401, "That token is not valid")
