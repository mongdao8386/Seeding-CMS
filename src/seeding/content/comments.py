"""Bo binh luan ngan, chung chung, tieng Viet doi thuong - dung chung cho moi nen tang.

Chon theo rng seed tu job id: chay lai cung mot job ra cung mot cau, hai tai khoan khac
nhau ra cau khac nhau. Cau phai du chung de dat duoi bat ky video dang len nao - mot
cau "hay quá" duoi video nau an va duoi video bong da deu on.
"""

from __future__ import annotations

import random

COMMENTS = [
    "Hay quá 😂",
    "xem đi xem lại mấy lần luôn",
    "ủa hay v",
    "đỉnh thật sự",
    "cười xỉu 🤣",
    "coi mà thấy vui ghê",
    "trend này hot quá",
    "ai cũng nên xem cái này",
    "hay ghê á",
    "quá đỉnh luôn 👏",
    "lưu lại coi sau",
    "nhạc gì v ạ",
    "xem lần thứ 3 rồi 😅",
    "chất lượng thật sự",
    "vui quá trời",
    "ok cái này hay nè",
    "thật sự là đỉnh",
    "đúng gu mình luôn",
    "quá là hay",
    "coi mà mê",
]


def comment_text(job_id, rng: random.Random | None = None) -> str:
    rng = rng or random.Random(f"comment:{job_id}")
    return rng.choice(COMMENTS)


# Binh luan "sticker": chi emoji, khong chu. Nguoi that nuoi acc hay lam the - it dau
# vet ngon ngu, khong bi soi noi dung, va nhin van tu nhien duoi video dang len.
# TikTok co bo emoji rieng theo ma [ten] (hien thanh sticker cua TikTok).
STICKERS_TIKTOK = [
    "[loveface]",
    "[laughwithtears]",
    "[wow]",
    "[cool]",
    "[proud]",
    "[joyful]",
    "[excited]",
    "[hehe]",
    "[happy]",
    "[lovely]",
    "[sunglasses]",
    "[surprised]",
    "[smile]",
    "[cute]",
    "[shock]",
    "[stun]",
]
# Cac nen tang khac: emoji unicode.
STICKERS = ["😂", "🔥", "❤️", "👏", "😍", "🥰", "💯", "😆", "🤣", "👍", "✨", "🙌", "😮", "💕"]


def sticker_text(job_id, platform: str = "tiktok", rng: random.Random | None = None) -> str:
    """1-3 sticker, thinh thoang lap lai cung mot cai (nguoi that hay go 😂😂😂)."""
    rng = rng or random.Random(f"sticker:{job_id}")
    pool = STICKERS_TIKTOK if platform == "tiktok" else STICKERS
    n = rng.choice([1, 1, 2, 2, 3])
    if rng.random() < 0.4:
        return rng.choice(pool) * n
    return "".join(rng.choice(pool) for _ in range(n))


def warm_comment(
    job_id, platform: str, rng: random.Random | None = None, style: str | None = None
) -> str:
    """Binh luan khi nuoi. `style` (WARM_COMMENT_STYLE): sticker | text | mixed."""
    if style is None:
        from seeding.config import get_settings

        style = get_settings().warm_comment_style
    rng = rng or random.Random(f"warm:{job_id}")
    if style == "text":
        return comment_text(job_id, rng)
    if style == "mixed" and rng.random() < 0.5:
        return comment_text(job_id, rng)
    return sticker_text(job_id, platform, rng)
