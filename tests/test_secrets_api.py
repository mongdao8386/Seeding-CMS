"""Thong tin dang nhap dan vao luc nhap acc phai xem lai va sua duoc - khong thi luc phien
chet nguoi van hanh phai di mo lai file nguoi ban (than phien that 08/09/2026)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import Account, AccountStatus, Platform


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


@pytest.fixture
async def account_id():
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        account = Account(
            persona_id=persona.id,
            platform=Platform.TIKTOK,
            handle=f"thu_{uuid.uuid4().hex[:10]}",
            status=AccountStatus.WARMING,
        )
        account.set_secrets({"username": "thu_user", "password": "matkhau1"})
        s.add(account)
        await s.commit()
        aid = account.id
    yield aid
    async with SessionLocal() as s:
        obj = await s.get(Account, aid)
        if obj is not None:
            await s.delete(obj)
        await s.commit()


async def test_imported_credentials_can_be_read_back(client, account_id):
    r = await client.get(f"/accounts/{account_id}/secrets")
    assert r.status_code == 200
    body = r.json()
    assert body["fields"] == {"username": "thu_user", "password": "matkhau1"}
    assert body["totp_code"] is None
    assert "recovery_email" in body["known"]


async def test_credentials_can_be_edited_and_blank_removes_a_field(client, account_id):
    r = await client.put(
        f"/accounts/{account_id}/secrets",
        json={"fields": {"password": "moi123", "recovery_email": " a@b.c ", "username": ""}},
    )
    assert r.status_code == 200
    assert r.json()["fields"] == {"password": "moi123", "recovery_email": "a@b.c"}

    async with SessionLocal() as s:
        acc = await s.get(Account, account_id)
        assert acc.get_secrets() == {"password": "moi123", "recovery_email": "a@b.c"}


async def test_unknown_credential_field_is_refused(client, account_id):
    r = await client.put(f"/accounts/{account_id}/secrets", json={"fields": {"pin": "1"}})
    assert r.status_code == 422


async def test_totp_code_is_computed_from_the_seed(client, account_id):
    r = await client.put(
        f"/accounts/{account_id}/secrets", json={"fields": {"totp_seed": "JBSWY3DPEHPK3PXP"}}
    )
    assert r.status_code == 200
    code = r.json()["totp_code"]
    assert code is not None and len(code) == 6 and code.isdigit()
