"""Doc danh sach proxy dan vao, tu nhieu dinh dang.

Bat bien cua he thong la MOT acc MOT proxy, khong dung chung - nen so proxy luon phai
bang so tai khoan. Them tung cai qua form la viec on voi hai proxy va vo ly voi bon
muoi, dung nhu chuyen da xay ra voi tai khoan truoc khi co phan nhap CSV.

Nguoi ban proxy dua ra bon dinh dang, va khong ai thong nhat:

    host:port
    host:port:user:pass          <- pho bien nhat o Viet Nam
    user:pass@host:port
    socks5://user:pass@host:port

Cho de sai am tham nhat la hai dinh dang giua: `a:b:c:d` co the la host:port:user:pass
ma cung co the la mot thu khac. Phan biet bang cach nhin phan tu THU HAI co phai so
cong hay khong - doan sai o day thi proxy duoc tao voi mat khau nam trong o cong, va
loi bao ra se la mot cai gi do hoan toan khong lien quan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMES = ("http", "https", "socks5", "socks4")

# Cong hop le. 0 khong phai cong, va tren 65535 thi khong ton tai.
PORT_MIN, PORT_MAX = 1, 65535


@dataclass(slots=True)
class ParsedProxy:
    line: int
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def address(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass(slots=True)
class ProxyProblem:
    line: int
    raw: str
    detail: str


@dataclass(slots=True)
class ProxyReport:
    rows: list[ParsedProxy] = field(default_factory=list)
    problems: list[ProxyProblem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def with_auth(self) -> int:
        return sum(1 for r in self.rows if r.username)


def _port(value: str) -> int | None:
    if not value.isdigit():
        return None
    port = int(value)
    return port if PORT_MIN <= port <= PORT_MAX else None


def parse_one(raw: str, line: int = 0, default_scheme: str = "http") -> ParsedProxy:
    """Doc mot dong. Nem ValueError kem ly do doc duoc neu khong hieu."""
    text = raw.strip()
    if not text:
        raise ValueError("empty line")

    scheme = default_scheme
    if match := re.match(r"^([a-z][a-z0-9]*)://(.*)$", text, re.I):
        scheme = match.group(1).lower()
        text = match.group(2)
        if scheme not in SCHEMES:
            raise ValueError(f"'{scheme}' is not a scheme this system speaks {list(SCHEMES)}")

    username = password = None

    # user:pass@host:port
    if "@" in text:
        auth, _, address = text.rpartition("@")
        if ":" in auth:
            username, _, password = auth.partition(":")
        else:
            username = auth
        text = address

    parts = text.split(":")

    if len(parts) == 2:
        host, port_raw = parts
    elif len(parts) == 4 and username is None:
        # host:port:user:pass - phan biet voi cac dang khac bang cach nhin phan tu thu
        # hai. Doan sai o day thi mat khau roi vao o cong, va loi bao ra sau do se noi
        # ve mot chuyen hoan toan khac.
        host, port_raw, username, password = parts
        if _port(port_raw) is None:
            raise ValueError(
                f"four parts, but '{port_raw}' is not a port — expected host:port:user:pass"
            )
    else:
        raise ValueError(
            "cannot read this. Use host:port, host:port:user:pass, or user:pass@host:port"
        )

    port = _port(port_raw)
    if port is None:
        raise ValueError(f"'{port_raw}' is not a port between {PORT_MIN} and {PORT_MAX}")
    if not host:
        raise ValueError("no host")

    return ParsedProxy(
        line=line,
        scheme=scheme,
        host=host,
        port=port,
        username=username or None,
        password=password or None,
    )


def parse(text: str, default_scheme: str = "http") -> ProxyReport:
    """Doc ca danh sach.

    Mot dong hong khong lam dung ca danh sach: nguoi dung can thay HET moi dong sai
    trong mot lan, giong het phan nhap tai khoan.
    """
    report = ProxyReport()
    seen: set[tuple[str, int]] = set()

    for offset, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        try:
            proxy = parse_one(line, offset, default_scheme)
        except ValueError as exc:
            report.problems.append(ProxyProblem(offset, line, str(exc)))
            continue

        # Trung trong chinh danh sach nay. Hai ban ghi cung host:port la mot loi ra
        # duy nhat duoc dem thanh hai - va bat bien mot-acc-mot-proxy im lang vo.
        key = (proxy.host.lower(), proxy.port)
        if key in seen:
            report.problems.append(
                ProxyProblem(offset, line, f"{proxy.host}:{proxy.port} appears twice in this list")
            )
            continue
        seen.add(key)

        report.rows.append(proxy)

    if not report.rows and not report.problems:
        report.problems.append(ProxyProblem(0, "", "Nothing to read."))

    return report
