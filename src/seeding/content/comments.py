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
