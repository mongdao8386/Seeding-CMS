"""Ket bi mat: ma hoa truoc khi ghi xuong DB.

Moi thu nhay cam deu di qua day - mat khau, TOTP seed, email khoi phuc, mat khau
proxy, va ca cookie jar. Cookie jar dac biet quan trong: no chinh la phien dang
nhap, ai co no la vao duoc tai khoan.

Khoa nam trong bien moi truong VAULT_KEY. MAT KHOA LA MAT TOAN BO PHIEN DANG NHAP,
khong khoi phuc duoc - sao luu no rieng, dung de chung cho voi ban sao luu DB.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from seeding.config import get_settings


class VaultError(RuntimeError):
    pass


@lru_cache
def _cipher() -> Fernet:
    key = get_settings().vault_key
    if not key:
        raise VaultError(
            "Thieu VAULT_KEY trong .env. Tao mot khoa moi bang:\n"
            "    python scripts/gen_vault_key.py"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise VaultError(f"VAULT_KEY khong hop le: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise VaultError(
            "Khong giai ma duoc. Thuong la do VAULT_KEY hien tai khac voi khoa da dung luc ma hoa."
        ) from exc


def encrypt_json(data: dict) -> str:
    return encrypt(json.dumps(data, ensure_ascii=False))


def decrypt_json(token: str | None) -> dict:
    if not token:
        return {}
    return json.loads(decrypt(token))


def totp_now(seed: str) -> str:
    """Sinh ma 2FA tu seed da luu. Seed lay luc bat 2FA, dang base32."""
    return pyotp.TOTP(seed.replace(" ", "")).now()


def new_key() -> str:
    return Fernet.generate_key().decode()
