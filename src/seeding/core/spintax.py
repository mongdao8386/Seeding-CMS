"""Sinh bien the van ban bang spintax: {a|b|c}, ho tro long nhau.

    "Chao {ban|cac ban}, {hom nay|toi nay} {troi dep|mat me} qua"

Quan trong: dung RNG co seed co dinh theo tung account, khong dung random toan cuc.
Nho vay lap ke hoach lai cho cung mot campaign se ra dung ban cu -> khong bao gio
sinh noi dung khac cho mot job da ton tai.
"""

from __future__ import annotations

import hashlib
import random


def expand(template: str, rng: random.Random) -> str:
    """Chon mot nhanh cho moi khoi {…|…}, xu ly tu trong ra ngoai."""
    out: list[str] = []
    i = 0
    n = len(template)

    while i < n:
        ch = template[i]
        if ch == "{":
            block, end = _read_block(template, i)
            options = _split_top_level(block)
            chosen = options[rng.randrange(len(options))] if options else ""
            # Nhanh duoc chon co the con khoi long ben trong.
            out.append(expand(chosen, rng))
            i = end
        else:
            out.append(ch)
            i += 1

    return "".join(out)


def _read_block(s: str, start: int) -> tuple[str, int]:
    """Doc khoi bat dau tai s[start] == '{'. Tra ve (noi dung ben trong, chi so sau '}')."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1 : i], i + 1
    # Thieu dau dong -> coi phan con lai la van ban thuong.
    return s[start + 1 :], len(s)


def _split_top_level(block: str) -> list[str]:
    """Tach theo '|' nhung bo qua nhung dau '|' nam trong khoi long ben trong."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in block:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def combinations(template: str) -> int:
    """Dem so to hop khac nhau ma template co the sinh ra.

    Con so nay quan trong hon ve ngoai cua tung bien the: template co 288 to hop ma
    dung cho 50 tai khoan thi gan nhu chac chan co bai trung nhau, va bai trung la tin
    hieu spam ro nhat. Biet truoc thi con kip them nhanh.

    Cac khoi noi tiep nhau thi nhan, cac lua chon trong mot khoi thi cong.
    """
    total = 1
    i = 0
    n = len(template)

    while i < n:
        if template[i] == "{":
            block, end = _read_block(template, i)
            options = _split_top_level(block)
            total *= sum(combinations(opt) for opt in options) or 1
            i = end
        else:
            i += 1

    return total


def rng_for(*parts: object) -> random.Random:
    """RNG on dinh: cung dau vao luon cho cung ket qua, ke ca giua cac lan chay."""
    seed = hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\x00{body}".encode()).hexdigest()
