"""Loi proxy phai noi ro PHAI LAM GI, khong chi la ma loi.

`ProxyError: 407` la chinh xac ve ky thuat va vo dung ve thuc hanh. Nguoi van hanh cam
proxy vao, thay chu do, se di kiem tra host, port, tuong lua - moi thu tru cai that su
sai. Cac test o day khoa lai viec moi loi hay gap deu chi dung vao cho can sua.
"""

import httpx
import pytest

from seeding.domain.models import Proxy
from seeding.ops.proxytest import explain_failure


def _proxy(username: str | None = None, scheme: str = "http") -> Proxy:
    return Proxy(
        label="P01",
        host="zl47160.example.com",
        port=31159,
        scheme=scheme,
        username=username,
    )


def test_407_with_no_username_points_at_the_empty_field():
    message = explain_failure(httpx.ProxyError("407 Proxy Authentication Required"), _proxy())
    assert "username" in message.lower()
    assert "zl47160.example.com" in message


def test_407_with_a_username_blames_the_credentials_not_the_missing_field():
    message = explain_failure(
        httpx.ProxyError("407 Proxy Authentication Required"), _proxy(username="user123")
    )
    assert "user123" in message
    assert "mật khẩu" in message.lower()


def test_a_bad_hostname_says_it_never_connected():
    message = explain_failure(httpx.ConnectError("[Errno 11001] getaddrinfo failed"), _proxy())
    assert "không phân giải" in message
    assert "zl47160.example.com" in message


def test_a_timeout_names_the_usual_causes():
    message = explain_failure(httpx.ConnectTimeout("timed out"), _proxy())
    assert "31159" in message
    assert "cho phép" in message  # IP may chua duoc nha cung cap cho phep


def test_a_refused_connection_points_at_the_port_and_scheme():
    message = explain_failure(
        httpx.ConnectError("[WinError 10061] connection refused"), _proxy(scheme="socks5")
    )
    assert "31159" in message
    assert "socks5" in message


def test_403_is_about_the_plan_not_the_password():
    message = explain_failure(
        httpx.HTTPStatusError("403 Forbidden", request=None, response=None),
        _proxy(),  # type: ignore[arg-type]
    )
    assert "gói" in message.lower()


def test_an_unrecognised_error_is_passed_through_untouched():
    message = explain_failure(RuntimeError("something nobody has seen before"), _proxy())
    assert message == "RuntimeError: something nobody has seen before"


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ProxyError("407 Proxy Authentication Required"),
        httpx.ConnectError("getaddrinfo failed"),
        httpx.ConnectTimeout("timed out"),
        RuntimeError("x"),
    ],
)
def test_the_original_error_is_always_kept(exc):
    """Giai thich la de bat tay dung cho; chuoi goc la de go loi. Khong bo cai nao."""
    message = explain_failure(exc, _proxy())
    assert type(exc).__name__ in message
