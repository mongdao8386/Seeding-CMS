"""Bao ra ngoai khi co tai khoan can nguoi.

Van de that: acc ket luc 2 gio sang thi no nam im toi khi ban mo dashboard. Moi gio
nam do la mot gio nen tang nhin thay mot tai khoan bi chan ma khong ai phan ung -
va voi vai nen tang, im lang sau checkpoint chinh la dau hieu bo tai khoan.

Ba nguyen tac:
  - Moi tai khoan ket chi bao MOT lan. Bao lai moi vong quet la cach nhanh nhat de
    nguoi ta tat thong bao di, va roi bo lo lan that su quan trong.
  - Bao hong thi KHONG duoc lam hong viec chinh. Webhook chet khong duoc keo theo
    ca vong quet suc khoe.
  - Khong bao gio dat bi mat vao noi dung tin nhan: khong mat khau, khong ma 2FA,
    khong cookie. Chi ten tai khoan, nen tang, va ly do.
"""

from __future__ import annotations

import httpx
import structlog

from seeding.config import get_settings

log = structlog.get_logger(__name__)


class AlertError(RuntimeError):
    pass


def configured() -> bool:
    return bool(get_settings().alert_webhook_url)


def _payload(kind: str, text: str) -> dict:
    """Moi dich mot hinh dang JSON khac nhau."""
    settings = get_settings()

    if kind == "telegram":
        # Bot API: chat_id di kem, URL la .../botTOKEN/sendMessage
        return {"chat_id": settings.alert_telegram_chat_id, "text": text}
    if kind == "discord":
        return {"content": text}
    if kind == "slack":
        return {"text": text}
    return {"text": text, "message": text}  # generic: gui ca hai khoa hay gap


def send(text: str) -> bool:
    """Gui mot tin. Tra ve True neu di duoc. Khong bao gio nem loi ra ngoai.

    Nuot loi la co y: ham nay duoc goi tu duong xu ly su co, va mot webhook chet
    khong duoc bien su co nho thanh su co lon.
    """
    settings = get_settings()
    url = settings.alert_webhook_url
    if not url:
        return False

    kind = (settings.alert_kind or "generic").lower()
    if kind == "telegram" and not settings.alert_telegram_chat_id:
        log.warning("alert.misconfigured", reason="ALERT_TELEGRAM_CHAT_ID is empty")
        return False

    try:
        response = httpx.post(url, json=_payload(kind, text), timeout=10)
        if response.status_code >= 400:
            log.warning("alert.rejected", status=response.status_code, body=response.text[:200])
            return False
        log.info("alert.sent", kind=kind)
        return True
    except Exception as exc:
        log.warning("alert.failed", error=f"{type(exc).__name__}: {exc}")
        return False


def takeover_opened(handle: str, platform: str, reason: str, queue_size: int) -> bool:
    """Mot tai khoan vua vao hang doi cho nguoi."""
    return send(
        f"[seeding-cms] {handle} ({platform}) needs a person.\n"
        f"{reason}\n"
        f"{queue_size} account(s) waiting."
    )
