"""Lay ma xac minh tu hom thu Hotmail cua acc bang OAuth2 - khong cham mang that."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import Account, AccountStatus, Platform
from seeding.ops import mailbox
from seeding.ops.mailbox import MailboxError, _Message, extract_code, pick

NOW = datetime.now(UTC)


def _msg(subject, body="", sender="TikTok <noreply@account.tiktok.com>", minutes_ago=1):
    return _Message(subject, sender, NOW - timedelta(minutes=minutes_ago), body)


def test_code_is_read_from_the_subject_first():
    assert extract_code("482913 is your verification code", "year 2026, id 9912345") == "482913"
    assert extract_code("482913 là mã xác minh của bạn", "") == "482913"


def test_code_in_the_body_must_sit_next_to_the_word_code():
    html = "<html><style>.x{width:600px}</style><p>Your verification code:</p><b>731204</b></html>"
    assert extract_code("Verify your account", html) == "731204"
    assert extract_code("Mã xác minh TikTok", "Mã xác minh của bạn là 5521") == "5521"
    # So bat ky trong than thu KHONG phai la ma.
    assert extract_code("Welcome", "Copyright 2026 TikTok, 10010 NY") is None


def test_pick_takes_the_newest_platform_mail_inside_the_window():
    messages = [
        _msg("111111 is your verification code", minutes_ago=50),  # qua cu
        _msg("222222 is your verification code", minutes_ago=5),
        _msg("333333 is your verification code", minutes_ago=2),
        _msg("999999 is your code", sender="Microsoft <account@microsoft.com>", minutes_ago=1),
    ]
    msg, code = pick(messages, "tiktok", NOW - timedelta(minutes=30))
    assert code == "333333" and "TikTok" in msg.sender


def test_pick_explains_what_to_do_when_there_is_no_code():
    with pytest.raises(MailboxError) as err:
        pick([_msg("Welcome to TikTok")], "tiktok", NOW - timedelta(minutes=30))
    assert "gửi lại mã" in str(err.value)


async def test_fetch_code_uses_imap_for_thunderbird_style_tokens_and_reports_rotation(monkeypatch):
    calls = {}

    async def exchange(client_id, refresh_token):
        calls["exchange"] = (client_id, refresh_token)
        return {
            "access_token": "AT",
            "refresh_token": "RT-new",
            "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
        }

    def imap_read(address, access_token):
        calls["imap"] = (address, access_token)
        return [_msg("654321 is your verification code")]

    monkeypatch.setattr(mailbox, "_exchange", exchange)
    monkeypatch.setattr(mailbox, "_imap_read", imap_read)
    found = await mailbox.fetch_code(
        {
            "recovery_email": "a@hotmail.com",
            "mail_refresh_token": "RT-old",
            "mail_client_id": "cid",
        },
        platform="tiktok",
    )
    assert found.code == "654321" and found.new_refresh_token == "RT-new"
    assert calls["exchange"] == ("cid", "RT-old") and calls["imap"] == ("a@hotmail.com", "AT")


async def test_fetch_code_uses_graph_when_the_token_has_mail_scope(monkeypatch):
    async def exchange(client_id, refresh_token):
        return {"access_token": "AT", "scope": "https://graph.microsoft.com/Mail.Read"}

    async def graph_read(access_token):
        return [_msg("Mã của bạn", body="Mã xác minh: 880011")]

    def imap_read(*a):
        raise AssertionError("khong duoc di IMAP khi token la cua Graph")

    monkeypatch.setattr(mailbox, "_exchange", exchange)
    monkeypatch.setattr(mailbox, "_graph_read", graph_read)
    monkeypatch.setattr(mailbox, "_imap_read", imap_read)
    found = await mailbox.fetch_code(
        {"recovery_email": "a@hotmail.com", "mail_refresh_token": "RT", "mail_client_id": "cid"},
        platform="tiktok",
    )
    assert found.code == "880011" and found.new_refresh_token is None


async def test_missing_oauth_fields_are_explained():
    with pytest.raises(MailboxError) as err:
        await mailbox.fetch_code({"recovery_email": "a@hotmail.com"}, platform="tiktok")
    assert "refresh token" in str(err.value)


# ------------------------------------------------------------------ API


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
        account.set_secrets(
            {
                "recovery_email": "a@hotmail.com",
                "mail_refresh_token": "RT-old",
                "mail_client_id": "cid",
            }
        )
        s.add(account)
        await s.commit()
        aid = account.id
    yield aid
    async with SessionLocal() as s:
        obj = await s.get(Account, aid)
        if obj is not None:
            await s.delete(obj)
        await s.commit()


async def test_api_returns_the_code_and_stores_the_rotated_token(client, account_id, monkeypatch):
    async def fake(secrets, *, platform=None, since_minutes=30):
        assert secrets["mail_refresh_token"] == "RT-old" and platform == "tiktok"
        return mailbox.MailCode(
            code="123456",
            subject="123456 is your verification code",
            sender="TikTok",
            received_at=datetime.now(UTC) - timedelta(seconds=40),
            new_refresh_token="RT-new",
        )

    monkeypatch.setattr(mailbox, "fetch_code", fake)
    r = await client.post(f"/accounts/{account_id}/mail-code")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "123456" and 30 <= body["age_seconds"] <= 120
    assert "RT-" not in r.text, "token khong bao gio di ra ngoai"
    async with SessionLocal() as s:
        acc = await s.get(Account, account_id)
        assert acc.get_secrets()["mail_refresh_token"] == "RT-new"


async def test_api_keeps_the_rotated_token_even_when_no_code_was_found(
    client, account_id, monkeypatch
):
    async def fake(secrets, *, platform=None, since_minutes=30):
        exc = MailboxError("Chưa thấy thư chứa mã")
        exc.new_refresh_token = "RT-rotated"
        raise exc

    monkeypatch.setattr(mailbox, "fetch_code", fake)
    r = await client.post(f"/accounts/{account_id}/mail-code")
    assert r.status_code == 409 and "Chưa thấy thư" in r.json()["detail"]
    async with SessionLocal() as s:
        acc = await s.get(Account, account_id)
        assert acc.get_secrets()["mail_refresh_token"] == "RT-rotated"
