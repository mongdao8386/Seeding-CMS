"""Lay ma xac minh tu hom thu Hotmail/Outlook cua acc bang OAuth2 (refresh_token + client_id).

Acc mua san di kem `refresh_token|client_id` cua hom thu ("mail trust OAuth2, code can be
recovered"): khi dang nhap lai trong profile, nen tang gui ma ve email, va nguoi van hanh
khong phai mo Hotmail bang tay - bam "Lay ma tu email" la co.

Luong:
  1. Doi refresh_token lay access_token (login.microsoftonline.com, du phong login.live.com).
     Microsoft XOAY refresh_token moi lan doi: cai moi phai duoc luu lai, khong thi lan sau
     cai cu co the da het han. `fetch_code` tra ve token moi de nguoi goi ghi vao ket.
  2. Doc thu: scope cua token quyet dinh duong - Graph (Mail.Read) hoac IMAP XOAUTH2
     (client_id cua Thunderbird, cai nguoi ban hay dung, chi co IMAP).
  3. Tim thu moi nhat cua nen tang trong `since_minutes` phut, rut ma 4-8 chu so.

Hom thu duoc doc TRUC TIEP tu may chu, khong qua proxy cua acc: imaplib khong di qua HTTP
proxy, va day la Microsoft chu khong phai nen tang dang nuoi. Khong bao gio ghi noi dung thu
hay token ra log.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

import httpx
import structlog

log = structlog.get_logger(__name__)

TOKEN_ENDPOINTS = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "https://login.live.com/oauth20_token.srf",
)
IMAP_HOST = "outlook.office365.com"
GRAPH_MESSAGES = "https://graph.microsoft.com/v1.0/me/messages"
LOOK_AT = 15  # so thu moi nhat duoc mo ra xem
TIMEOUT = 30

# Ten nen tang -> chu nhan ra thu cua no (nguoi gui / tieu de). Khong co thi nhan moi thu.
SENDER_HINTS = {
    "tiktok": ("tiktok",),
    "instagram": ("instagram",),
    "facebook": ("facebook", "meta"),
    "x": ("twitter", "x.com"),
    "reddit": ("reddit",),
}

_CODE_IN_SUBJECT = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_CODE_NEAR_WORD = re.compile(
    r"(?:code|mã|ma xac|verification|xác minh|xac minh)\D{0,80}?(?<!\d)(\d{4,8})(?!\d)", re.I | re.S
)
_TAGS = re.compile(r"<(style|script)\b.*?</\1>|<[^>]+>", re.I | re.S)


class MailboxError(RuntimeError):
    """Khong lay duoc ma; thong diep da san sang hien cho nguoi van hanh."""


@dataclass(slots=True)
class MailCode:
    code: str
    subject: str
    sender: str
    received_at: datetime | None
    # refresh_token Microsoft vua cap lai (None neu khong doi) - nguoi goi PHAI luu.
    new_refresh_token: str | None = None


@dataclass(slots=True)
class _Message:
    subject: str
    sender: str
    received_at: datetime | None
    body: str


def extract_code(subject: str, body: str) -> str | None:
    """Ma xac minh trong mot thu. Tieu de truoc ("123456 is your verification code"), roi
    toi so dung gan chu "code"/"ma" trong than thu. Khong doan bua so dau tien trong than
    thu: than thu day so (nam, ma buu chinh, id)."""
    m = _CODE_IN_SUBJECT.search(subject or "")
    if m:
        return m.group(1)
    text = _TAGS.sub(" ", body or "")
    m = _CODE_NEAR_WORD.search(text)
    return m.group(1) if m else None


def pick(messages: list[_Message], platform: str | None, since: datetime) -> tuple[_Message, str]:
    """Thu moi nhat cua nen tang, trong khoang thoi gian, co ma."""
    hints = SENDER_HINTS.get((platform or "").lower(), ())
    candidates = []
    for msg in messages:
        if msg.received_at is not None and msg.received_at < since:
            continue
        hay = f"{msg.sender} {msg.subject}".lower()
        if hints and not any(h in hay for h in hints):
            continue
        code = extract_code(msg.subject, msg.body)
        if code:
            candidates.append((msg, code))
    if not candidates:
        raise MailboxError(
            "Chưa thấy thư chứa mã trong hộp thư (đã xem thư mới nhất ở Hộp thư đến và Thư "
            "rác). Bấm gửi lại mã trên trang đăng nhập, đợi 10-20 giây rồi thử lại."
        )
    candidates.sort(
        key=lambda c: c[0].received_at or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return candidates[0]


async def _exchange(client_id: str, refresh_token: str) -> dict:
    last = "không có phản hồi"
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        for url in TOKEN_ENDPOINTS:
            try:
                r = await http.post(
                    url,
                    data={
                        "client_id": client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                )
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}"
                continue
            try:
                body = r.json()
            except ValueError:
                last = f"HTTP {r.status_code}"
                continue
            if r.status_code == 200 and body.get("access_token"):
                return body
            last = str(body.get("error_description") or body.get("error") or r.status_code)[:200]
    raise MailboxError(
        f"Microsoft từ chối refresh token của hộp thư ({last}). Token có thể đã hết hạn hoặc bị "
        "thu hồi; đăng nhập hộp thư bằng mật khẩu email để lấy mã."
    )


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_of(msg: email.message.Message) -> str:
    parts = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() != "text":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(parts)[:20000]


def _imap_read(address: str, access_token: str) -> list[_Message]:
    """Doc LOOK_AT thu moi nhat cua INBOX va Junk bang XOAUTH2. Chay trong thread."""
    auth = f"user={address}\x01auth=Bearer {access_token}\x01\x01".encode()
    out: list[_Message] = []
    conn = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=TIMEOUT)
    try:
        conn.authenticate("XOAUTH2", lambda _challenge: auth)
        for folder in ("INBOX", "Junk"):
            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                continue
            status, data = conn.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                continue
            ids = data[0].split()[-LOOK_AT:]
            for msg_id in reversed(ids):
                status, fetched = conn.fetch(msg_id, "(RFC822)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                msg = email.message_from_bytes(fetched[0][1])
                received = None
                try:
                    received = parsedate_to_datetime(msg.get("Date"))
                    if received is not None and received.tzinfo is None:
                        received = received.replace(tzinfo=UTC)
                except Exception:
                    received = None
                out.append(
                    _Message(
                        subject=_decode(msg.get("Subject")),
                        sender=_decode(msg.get("From")),
                        received_at=received,
                        body=_body_of(msg),
                    )
                )
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return out


async def _graph_read(access_token: str) -> list[_Message]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        r = await http.get(
            GRAPH_MESSAGES,
            params={
                "$top": str(LOOK_AT),
                "$orderby": "receivedDateTime desc",
                "$select": "subject,from,receivedDateTime,body",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise MailboxError(f"Graph API từ chối đọc thư (HTTP {r.status_code}).")
    out = []
    for item in r.json().get("value", []):
        received = None
        try:
            received = datetime.fromisoformat(
                str(item.get("receivedDateTime")).replace("Z", "+00:00")
            )
        except ValueError:
            received = None
        sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        out.append(
            _Message(
                subject=str(item.get("subject") or ""),
                sender=str(sender),
                received_at=received,
                body=str((item.get("body") or {}).get("content") or ""),
            )
        )
    return out


async def fetch_code(
    secrets: dict, *, platform: str | None = None, since_minutes: int = 30
) -> MailCode:
    """Ma xac minh moi nhat cua `platform` trong hom thu cua acc."""
    address = (secrets.get("recovery_email") or "").strip()
    refresh_token = (secrets.get("mail_refresh_token") or "").strip()
    client_id = (secrets.get("mail_client_id") or "").strip()
    if not (address and refresh_token and client_id):
        raise MailboxError(
            "Acc này chưa có đủ email + refresh token + client id của hộp thư (xem thẻ Thông tin "
            "đăng nhập). Thiếu thì phải đăng nhập hộp thư bằng mật khẩu email."
        )

    token = await _exchange(client_id, refresh_token)
    access = token["access_token"]
    scope = str(token.get("scope") or "").lower()
    rotated = token.get("refresh_token")
    new_refresh = rotated if rotated and rotated != refresh_token else None

    try:
        if "graph.microsoft.com" in scope and "mail" in scope:
            messages = await _graph_read(access)
        else:
            messages = await asyncio.to_thread(_imap_read, address, access)
    except MailboxError:
        raise
    except (imaplib.IMAP4.error, OSError, httpx.HTTPError) as exc:
        raise MailboxError(
            f"Không đọc được hộp thư {address} ({type(exc).__name__}). Token đổi được nhưng "
            "Microsoft không cho đọc thư; thử lại sau ít phút hoặc đăng nhập bằng mật khẩu email."
        ) from exc

    since = datetime.now(UTC) - timedelta(minutes=since_minutes)
    try:
        msg, code = pick(messages, platform, since)
    except MailboxError as exc:
        # Van tra token moi ve cho nguoi goi luu, du khong co ma.
        exc.new_refresh_token = new_refresh  # type: ignore[attr-defined]
        raise
    log.info("mailbox.code_found", platform=platform, age_known=msg.received_at is not None)
    return MailCode(
        code=code,
        subject=msg.subject[:120],
        sender=msg.sender[:120],
        received_at=msg.received_at,
        new_refresh_token=new_refresh,
    )
