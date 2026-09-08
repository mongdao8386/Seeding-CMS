"""Bao ra ngoai khi co tai khoan can nguoi.

Kiem bang transport gia, khong can webhook that. Ba thu duoc kiem la ba nguyen tac
cua module: dung hinh dang JSON cho tung dich, bao hong khong duoc nem loi, va khong
bao gio co bi mat trong noi dung tin.
"""

import httpx
import pytest

from seeding.ops import alerts


class _settings:
    def __init__(self, *, url="https://hooks.example/abc", kind="generic", chat_id=""):
        self.alert_webhook_url = url
        self.alert_kind = kind
        self.alert_telegram_chat_id = chat_id


@pytest.fixture
def posted(monkeypatch):
    """Bat loi goi httpx.post va tra ve mot phan hoi gia."""
    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    return calls


# ------------------------------------------------------------------ cau hinh


def test_no_webhook_means_not_configured(monkeypatch):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings(url=""))
    assert alerts.configured() is False
    assert alerts.send("anything") is False


def test_a_webhook_means_configured(monkeypatch):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())
    assert alerts.configured() is True


def test_telegram_without_a_chat_id_refuses_instead_of_sending_nowhere(monkeypatch, posted):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings(kind="telegram", chat_id=""))
    assert alerts.send("hello") is False
    assert posted == [], "thieu chat_id ma van goi mang la gui vao hu khong"


# ------------------------------------------------------------- hinh dang JSON


@pytest.mark.parametrize(
    "kind,key",
    [("discord", "content"), ("slack", "text"), ("telegram", "text")],
)
def test_each_destination_gets_the_shape_it_expects(monkeypatch, posted, kind, key):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings(kind=kind, chat_id="99"))
    assert alerts.send("hello") is True
    assert posted[0]["json"][key] == "hello"


def test_telegram_carries_the_chat_id(monkeypatch, posted):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings(kind="telegram", chat_id="99"))
    alerts.send("hello")
    assert posted[0]["json"]["chat_id"] == "99"


def test_an_unknown_kind_sends_both_common_keys(monkeypatch, posted):
    """Khong biet dich la gi thi gui ca hai khoa hay gap, con hon gui sai ca hai."""
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings(kind="whatever"))
    alerts.send("hello")
    assert posted[0]["json"] == {"text": "hello", "message": "hello"}


# ------------------------------------------------------------ khong duoc no ra


def test_a_rejected_webhook_returns_false_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())

    def rejecting(url, json=None, timeout=None):
        return httpx.Response(500, content=b"upstream is down")

    monkeypatch.setattr(alerts.httpx, "post", rejecting)
    assert alerts.send("hello") is False


def test_a_dead_network_returns_false_and_does_not_raise(monkeypatch):
    """Ham nay duoc goi tu duong xu ly su co. Webhook chet khong duoc keo do ca vong quet."""
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())

    def exploding(url, json=None, timeout=None):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(alerts.httpx, "post", exploding)
    assert alerts.send("hello") is False


def test_a_send_always_has_a_timeout(monkeypatch, posted):
    """Khong timeout thi mot webhook treo se treo luon vong quet suc khoe."""
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())
    alerts.send("hello")
    assert posted[0]["timeout"] is not None


# ---------------------------------------------------------------- noi dung tin


def test_the_takeover_message_names_the_account_platform_and_queue(monkeypatch, posted):
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())
    alerts.takeover_opened("seed_01", "reddit", "captcha on login", 3)

    text = posted[0]["json"]["text"]
    assert "seed_01" in text
    assert "reddit" in text
    assert "captcha on login" in text
    assert "3" in text


def test_no_secret_ever_reaches_the_message_body(monkeypatch, posted):
    """Ly do su co di thang tu he thong vao tin nhan, nen no la duong ro ri de nhat.

    Tin nhan chi duoc mang ten tai khoan, nen tang va ly do - khong mat khau, khong
    ma 2FA, khong cookie.
    """
    monkeypatch.setattr(alerts, "get_settings", lambda: _settings())
    alerts.takeover_opened("seed_01", "facebook", "checkpoint", 1)

    body = str(posted[0]["json"])
    for leak in ("password", "cookie", "totp", "secret", "token", "session"):
        assert leak not in body.lower()
