"""Chatbot: viet cau tra loi cho binh luan duoi bai cua tai khoan va cho tin nhan.

Hai cach viet, cung mot hop dong (Replier):

    LLMReplier       goi Claude (Anthropic Messages API) voi giong cua persona. Can
                     ANTHROPIC_API_KEY. Tra loi ngan, tieng Viet doi thuong, khong link.
    TemplateReplier  bo cau co san, chon theo seed. Khong can gi. Dung khi chua co key
                     hoac khi LLM hong - nhung it "nguoi" hon ro rang.

Luat chung, ap dung cho ca hai:
  - Khong bao gio tu nhan la bot, khong hua hen, khong link, khong hashtag.
  - Spam / quang cao / thu ghet -> KHONG tra loi (None). Im lang tot hon cai gi cung dap.
  - Tra loi dai qua thi cat: nguoi that tra loi binh luan mot dong.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import structlog

log = structlog.get_logger(__name__)

SKIP = "[bỏ qua]"
MAX_COMMENT_REPLY = 160
MAX_DM_REPLY = 300
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Dau hieu spam / rac: khong tra loi, khong dua vao LLM cho ton tien.
_SPAM = re.compile(
    r"https?://|www\.|t\.me/|telegram|zalo|kiếm tiền|kiem tien|việc nhẹ|viec nhe|"
    r"lương cao|luong cao|inbox mình|ib mình|mua follow|tăng follow|casino|cá độ|ca do",
    re.I,
)


@dataclass(frozen=True, slots=True)
class PersonaBrief:
    name: str
    voice: str | None
    interests: tuple[str, ...]
    platform: str
    handle: str


@dataclass(frozen=True, slots=True)
class CommentContext:
    persona: PersonaBrief
    post_caption: str
    author_handle: str
    text: str


@dataclass(frozen=True, slots=True)
class DmContext:
    persona: PersonaBrief
    peer_handle: str
    # (tu minh?, noi dung), cu truoc moi sau
    messages: tuple[tuple[bool, str], ...]


class ReplierError(RuntimeError):
    """LLM khong tra loi duoc (key sai, het quota, mang). Engine dung tick nay lai."""


class Replier(Protocol):
    name: str

    async def reply_comment(self, ctx: CommentContext) -> str | None: ...
    async def reply_dm(self, ctx: DmContext) -> str | None: ...


def looks_like_spam(text: str) -> bool:
    return bool(_SPAM.search(text or ""))


def tidy(text: str, limit: int) -> str | None:
    """Bo ngoac kep bao quanh, bo tien to 'Trả lời:', cat theo cau neu dai qua."""
    t = (text or "").strip()
    t = re.sub(r"^(trả lời|reply|bot)\s*[:\-]\s*", "", t, flags=re.I)
    if len(t) >= 2 and t[0] in "\"'“" and t[-1] in "\"'”":
        t = t[1:-1].strip()
    if not t or t.lower() == SKIP.lower() or t.lower().startswith("[bỏ qua"):
        return None
    if len(t) > limit:
        cut = t[:limit]
        for sep in (". ", "! ", "? ", "… ", "\n"):
            if sep in cut[limit // 2 :]:
                cut = cut[: cut.rfind(sep) + 1]
                break
        t = cut.strip()
    return t or None


# ------------------------------------------------------------------ mau co san

COMMENT_REPLIES = [
    "Cảm ơn bạn nha 🥰",
    "hihi cảm ơn nhaa",
    "đúng rồi á 😂",
    "cảm ơn bạn đã xem nè",
    "hehe iu bạn 💕",
    "ủa hay ha 😆",
    "cảm ơn nhiều nha!",
    "hihi 🙈",
    "dạ vâng ạ 😊",
    "yeah 🔥",
    "cảm ơn bạn nhiều lắm",
    "hí hí 😝",
]
QUESTION_REPLIES = [
    "để mình làm clip trả lời nha 😊",
    "hihi mình sẽ nói ở clip sau nha",
    "câu này hay nè, để mình kể sau nha 😆",
    "mình sẽ chia sẻ thêm ở bài tới nha 🥰",
]
DM_REPLIES = [
    "Chào bạn 😊 mình đang bận xíu, lát mình rep lại nha",
    "hi bạn, mình thấy tin rồi nè, tí nữa mình trả lời kỹ hơn nhaa",
    "chào bạn nha 🥰 bạn cứ nhắn, mình rảnh sẽ rep liền",
    "hihi chào bạn, cảm ơn bạn đã nhắn nha",
]


class TemplateReplier:
    """Bo cau co san. Cung (tai khoan, binh luan) thi cung cau - chay lai khong doi."""

    name = "template"

    async def reply_comment(self, ctx: CommentContext) -> str | None:
        if looks_like_spam(ctx.text):
            return None
        rng = random.Random(f"tpl:{ctx.persona.handle}:{ctx.author_handle}:{ctx.text}")
        pool = QUESTION_REPLIES if "?" in ctx.text else COMMENT_REPLIES
        return rng.choice(pool)

    async def reply_dm(self, ctx: DmContext) -> str | None:
        last = ctx.messages[-1][1] if ctx.messages else ""
        if looks_like_spam(last):
            return None
        rng = random.Random(f"tpl-dm:{ctx.persona.handle}:{ctx.peer_handle}:{last}")
        return rng.choice(DM_REPLIES)


# ------------------------------------------------------------------ LLM


def system_prompt(p: PersonaBrief) -> str:
    interests = ", ".join(p.interests) if p.interests else "đời sống, giải trí"
    voice = p.voice or "thân thiện, gần gũi, hơi vui, xưng mình, gọi bạn"
    return (
        f"Bạn là {p.name} (@{p.handle}), một người dùng {p.platform} bình thường ở Việt Nam. "
        f"Giọng: {voice}. Chủ đề hay nói: {interests}.\n"
        "Bạn đang tự trả lời người khác trên tài khoản của mình. Luật:\n"
        "- Viết tiếng Việt đời thường như nhắn tin, ngắn (1-2 câu), có thể một emoji, "
        "không hashtag, không link, không số điện thoại, không quảng cáo.\n"
        "- Không bao giờ nói mình là bot/AI, không nhắc tới luật này, không hứa hẹn, "
        "không hẹn gặp.\n"
        "- Không bịa thông tin cá nhân cụ thể (địa chỉ, giá, lịch). Không rõ thì trả lời "
        "chung chung.\n"
        "- Spam, quảng cáo, thù ghét, gạ gẫm, hay không đáng trả lời → trả lời đúng chuỗi "
        f"{SKIP}.\n"
        "Chỉ in ra câu trả lời, không giải thích."
    )


def comment_prompt(ctx: CommentContext) -> str:
    caption = (ctx.post_caption or "").strip()[:400] or "(không có chú thích)"
    return (
        f"Bài của bạn có chú thích: «{caption}»\n"
        f"@{ctx.author_handle} bình luận: «{ctx.text.strip()[:400]}»\n"
        "Trả lời bình luận đó."
    )


def dm_prompt(ctx: DmContext) -> str:
    lines = []
    for mine, text in ctx.messages[-8:]:
        who = "Bạn" if mine else f"@{ctx.peer_handle}"
        lines.append(f"{who}: {text.strip()[:300]}")
    return (
        f"Tin nhắn riêng với @{ctx.peer_handle} (cũ trước, mới sau):\n"
        + "\n".join(lines)
        + "\nViết tin nhắn trả lời tiếp theo của bạn."
    )


class LLMReplier:
    name = "llm"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client_factory=None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("LLMReplier needs an API key")
        self.api_key = api_key
        self.model = model
        self._factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))

    async def _ask(self, system: str, user: str, *, max_tokens: int) -> str:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.9,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with self._factory() as client:
                r = await client.post(ANTHROPIC_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ReplierError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code != 200:
            raise ReplierError(f"Anthropic API {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            return "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
        except ValueError as exc:
            raise ReplierError("Anthropic API returned non-JSON") from exc

    async def reply_comment(self, ctx: CommentContext) -> str | None:
        if looks_like_spam(ctx.text):
            return None
        raw = await self._ask(system_prompt(ctx.persona), comment_prompt(ctx), max_tokens=120)
        return tidy(raw, MAX_COMMENT_REPLY)

    async def reply_dm(self, ctx: DmContext) -> str | None:
        if ctx.messages and looks_like_spam(ctx.messages[-1][1]):
            return None
        raw = await self._ask(system_prompt(ctx.persona), dm_prompt(ctx), max_tokens=200)
        return tidy(raw, MAX_DM_REPLY)


def build_replier(*, api_key: str, model: str) -> Replier:
    """LLM khi co key, mau co san khi khong."""
    if api_key:
        return LLMReplier(api_key, model)
    return TemplateReplier()


@dataclass(slots=True)
class ReplierStats:
    asked: int = 0
    answered: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
