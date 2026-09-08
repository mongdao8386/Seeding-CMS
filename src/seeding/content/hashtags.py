"""Tui hashtag, rut ngau nhien cho tung tai khoan.

Vi sao khong phai mot khoi hashtag co dinh dan vao moi bai: muoi tai khoan dung dung
mot day the giong het nhau la cung mot dau vet trung lap nhu van ban giong nhau. Nhieu
cong cu seeding cho dan mot khoi hashtag chung, va do chinh la cho lo.

Cach dung: trong bai soan dat mot cho danh

    [[tags:cong-nghe:3]]

nghia la "rut 3 the tu tui cong-nghe". Planner rut bang dung RNG co seed nhu spintax,
nen moi tai khoan mot to hop khac, va lap ke hoach lai van ra dung ket qua cu.
"""

from __future__ import annotations

import math
import random
import re

# [[tags:ten-tui]] hoac [[tags:ten-tui:3]]
PATTERN = re.compile(r"\[\[tags:([a-zA-Z0-9_-]+)(?::(\d+))?\]\]")

DEFAULT_COUNT = 3
MAX_COUNT = 30


def normalise(tag: str) -> str:
    """Bo khoang trang, dam bao co dau #, bo cac dau # thua."""
    cleaned = tag.strip().lstrip("#").strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    return f"#{cleaned}" if cleaned else ""


def clean_pool(tags: list[str]) -> list[str]:
    """Chuan hoa va bo trung, giu nguyen thu tu nguoi dung nhap."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        tag = normalise(raw)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def referenced(text: str) -> set[str]:
    """Ten cac tui duoc nhac toi trong bai."""
    return {m.group(1).lower() for m in PATTERN.finditer(text or "")}


def expand(text: str, pools: dict[str, list[str]], rng: random.Random) -> str:
    """Thay moi cho danh bang cac the rut ngau nhien.

    Ten tui khong ton tai thi GIU NGUYEN cho danh chu khong xoa di - de nguoi soan
    nhin thay ngay minh go sai ten, thay vi bai len thieu hashtag ma khong ai biet.
    """

    def pick(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        wanted = int(match.group(2) or DEFAULT_COUNT)
        pool = pools.get(name)
        if not pool:
            return match.group(0)
        take = max(0, min(wanted, MAX_COUNT, len(pool)))
        return " ".join(rng.sample(pool, take))

    return PATTERN.sub(pick, text or "")


def combination_factor(text: str, pools: dict[str, list[str]]) -> int:
    """So to hop ma cac cho danh hashtag them vao.

    Dung de bao cao nguy co trung cho dung: mot tui 20 the rut 3 cai cho ra 6840 to
    hop co thu tu, tuc la no lam giam nguy co trung manh hon bat ky nhanh spintax nao.
    """
    total = 1
    for match in PATTERN.finditer(text or ""):
        pool = pools.get(match.group(1).lower())
        if not pool:
            continue
        wanted = max(0, min(int(match.group(2) or DEFAULT_COUNT), MAX_COUNT, len(pool)))
        if wanted:
            total *= math.perm(len(pool), wanted)
    return total
