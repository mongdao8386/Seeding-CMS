"""Doi loi proxy thanh mot cau noi ro phai lam gi.

`ProxyError: 407 Proxy Authentication Required` chinh xac ve ky thuat va vo dung ve
thuc hanh: no khong noi rang o Username dang de trong. Nguoi van hanh doc chu do se di
kiem tra host, port, tuong lua - moi thu tru thu that su sai.

Cac test o day khong goi mang. Chung kiem rang moi kieu hong hay gap deu duoc dich sang
mot cau chi dung cho can sua.
"""

import httpx
import pytest

from seeding.api.routes import explain_proxy_failure
from seeding.models import Proxy


def _proxy(**kw) -> Proxy:
    fields = {
        "label": "HA1",
        "scheme": "http",
        "host": "zl47160.example.com",
        "port": 31159,
        "username": None,
    }
    fields.update(kw)
    return Proxy(**fields)


def test_407_with_no_username_points_at_the_empty_field():
    """Day la truong hop that vua gap: proxy can dang nhap, ma o Username de trong."""
    message = explain_proxy_failure(httpx.ProxyError("407 Proxy Authentication Required"), _proxy())
    assert "username" in message.lower()
    assert "edit" in message.lower()


def test_407_with_a_username_blames_the_credentials_not_the_missing_field():
    """Da dien username roi ma van 407 thi loi khac han - noi nham lam nguoi ta dien
    lai dung cai da dung."""
    message = explain_proxy_failure(
        httpx.ProxyError("407 Proxy Authentication Required"), _proxy(username="user123")
    )
    assert "user123" in message
    assert "password is wrong" in message.lower()


def test_a_bad_hostname_says_it_never_connected():
    message = explain_proxy_failure(
        httpx.ConnectError("[Errno 11001] getaddrinfo failed"), _proxy()
    )
    assert "does not resolve" in message
    assert "zl47160.example.com" in message


def test_a_timeout_names_the_three_usual_causes():
    """Het gio la loi mo ho nhat: co the may chet, sai cong, hoac IP chua duoc cho phep."""
    message = explain_proxy_failure(httpx.ConnectTimeout("timed out"), _proxy())
    assert "31159" in message
    assert "allow-list" in message


def test_a_refused_connection_points_at_the_port_and_scheme():
    message = explain_proxy_failure(
        httpx.ConnectError(
            "No connection could be made because the target machine actively refused it"
        ),
        _proxy(scheme="socks5"),
    )
    assert "31159" in message
    assert "socks5" in message


def test_403_is_about_the_plan_not_the_password():
    message = explain_proxy_failure(
        httpx.HTTPStatusError("403 Forbidden", request=None, response=None), _proxy(username="u")
    )
    assert "plan" in message.lower()


def test_an_unrecognised_error_is_passed_through_untouched():
    """Doan mo la te hon la khong doan: mot cau chi dung sai cho lam nguoi ta di nham
    duong lau hon ca khi khong co goi y nao."""
    message = explain_proxy_failure(RuntimeError("something nobody has seen before"), _proxy())
    assert message == "RuntimeError: something nobody has seen before"


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ProxyError("407 Proxy Authentication Required"),
        httpx.ConnectError("getaddrinfo failed"),
        httpx.ConnectTimeout("timed out"),
        RuntimeError("unknown"),
    ],
)
def test_the_original_error_is_always_kept(exc):
    """Cau giai thich them vao chu khong duoc thay the. Loi goc la thu duy nhat dung
    de tra cuu duoc khi cau giai thich doan sai."""
    message = explain_proxy_failure(exc, _proxy())
    assert type(exc).__name__ in message
