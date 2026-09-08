"""Danh tinh cua tai khoan: ten hien thi, username, anh dai dien.

Mot lo tai khoan mua ve thuong mang ten kieu `user8827361` va anh trong. Truoc khi nuoi
phai doi thanh mot nguoi: ten Viet binh thuong, username giong nguoi that dat, anh that.
Phan thuan tuy o day: goi y ten, kiem tra username theo luat tung nen tang, va lam ban
anh dai dien rieng cho moi tai khoan (cat, lat, chinh sang nhe) de hai tai khoan dung
cung mot anh goc khong ra hai file giong het nhau.

Luat doi username (khong ep duoc):
    TikTok      30 ngay mot lan, 2-24 ky tu a-z 0-9 _ . (khong ket thuc bang .)
    Instagram   1-30 ky tu a-z 0-9 _ . ; doi lai nhieu lan trong 14 ngay se bi khoa
    X           4-15 ky tu a-z 0-9 _ ; doi bao nhieu lan cung duoc
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from pathlib import Path

from seeding.domain.models import Platform

# Nen tang da co duong doi danh tinh tu dong. TikTok chua: web cua no khong lo endpoint
# sua ho so trong bundle tinh, va trang sua ho so qua proxy dan cu mat nhieu phut.
SUPPORTED = frozenset({Platform.INSTAGRAM, Platform.X})

# So ngay toi thieu giua hai lan doi USERNAME. Ten hien thi va anh thi khong gioi han.
MIN_DAYS = {Platform.TIKTOK: 30, Platform.INSTAGRAM: 14, Platform.X: 1}

USERNAME_RULES: dict[Platform, tuple[int, int, str]] = {
    Platform.TIKTOK: (2, 24, r"^[a-z0-9_.]+$"),
    Platform.INSTAGRAM: (1, 30, r"^[a-z0-9_.]+$"),
    Platform.X: (4, 15, r"^[a-z0-9_]+$"),
}

GIVEN = [
    "Minh Anh",
    "Ngọc Trâm",
    "Thu Hà",
    "Bảo Ngọc",
    "Khánh Linh",
    "Phương Thảo",
    "Hồng Nhung",
    "Thanh Trúc",
    "Mai Chi",
    "Quỳnh Như",
    "Yến Nhi",
    "Tú Anh",
    "Diệu Linh",
    "Hà My",
    "Lan Anh",
    "Gia Hân",
    "Thùy Dung",
    "Kim Ngân",
    "Bích Phương",
    "Trúc Quỳnh",
    "Minh Quân",
    "Đức Anh",
    "Hoàng Nam",
    "Tuấn Kiệt",
    "Quang Huy",
    "Trung Hiếu",
    "Nhật Minh",
    "Anh Khoa",
    "Thanh Tùng",
    "Bảo Long",
    "Hữu Phước",
    "Văn Đạt",
    "Gia Bảo",
    "Thái Sơn",
    "Minh Khang",
    "Duy Khánh",
]
FAMILY = [
    "Nguyễn",
    "Trần",
    "Lê",
    "Phạm",
    "Hoàng",
    "Huỳnh",
    "Phan",
    "Vũ",
    "Võ",
    "Đặng",
    "Bùi",
    "Đỗ",
    "Hồ",
    "Ngô",
    "Dương",
    "Lý",
]
NICK = [
    "xinh",
    "cute",
    "daily",
    "vlog",
    "real",
    "story",
    "life",
    "nha",
    "corner",
    "vibes",
    "chill",
    "review",
    "tips",
    "food",
    "travel",
    "beauty",
    "style",
    "official",
    "ne",
    "oi",
]
# Duoi trang tri cho ten hien thi. Rat nhieu tai khoan that co, mot it tai khoan thi khong.
ORNAMENTS = ["", "", "", "", " ✨", " 🌸", " 🍀", " ☁️", " 🌷", " 💫"]


def strip_accents(text: str) -> str:
    """ "Ngọc Trâm" -> "ngoc tram". Chu d gach (đ) khong co dang to hop, doi tay."""
    text = text.replace("đ", "d").replace("Đ", "D")
    out = unicodedata.normalize("NFD", text)
    out = "".join(ch for ch in out if unicodedata.category(ch) != "Mn")
    return out.lower()


def suggest_names(seed: str, n: int = 3) -> list[str]:
    """Ten hien thi: 'Minh Anh', 'Nguyễn Thu Hà', 'Ngọc Trâm ✨'. Cung seed cung ket qua."""
    rng = random.Random(f"name:{seed}")
    out: list[str] = []
    while len(out) < n:
        given = rng.choice(GIVEN)
        style = rng.random()
        if style < 0.35:
            name = given
        elif style < 0.75:
            name = f"{rng.choice(FAMILY)} {given}"
        else:
            name = given + rng.choice(ORNAMENTS)
        if name not in out:
            out.append(name)
    return out


def suggest_usernames(
    seed: str, platform: Platform, n: int = 3, *, from_name: str | None = None
) -> list[str]:
    """Username giong nguoi that dat: ten + so, ten.nick, nick_ten. Theo luat nen tang."""
    rng = random.Random(f"username:{seed}:{platform.value}")
    lo, hi, pattern = USERNAME_RULES.get(platform, (2, 24, r"^[a-z0-9_.]+$"))
    dots = "." in pattern
    out: list[str] = []
    tries = 0
    while len(out) < n and tries < 60:
        tries += 1
        base = strip_accents(from_name or rng.choice(GIVEN))
        parts = [p for p in re.split(r"[^a-z0-9]+", base) if p]
        if not parts:
            continue
        given = "".join(parts[-2:]) if len(parts) >= 2 else parts[0]
        style = rng.random()
        if style < 0.3:
            cand = given + str(rng.randint(10, 99))
        elif style < 0.55:
            cand = (given + "." if dots else given + "_") + rng.choice(NICK)
        elif style < 0.75:
            cand = rng.choice(NICK) + "_" + given
        elif style < 0.9:
            cand = ("_".join(parts[-2:]) if len(parts) >= 2 else given) + str(rng.randint(1, 9))
        else:
            cand = given + "_" + str(rng.randint(1990, 2006))
        cand = re.sub(r"[^a-z0-9_.]", "", cand)
        if not dots:
            cand = cand.replace(".", "_")
        cand = cand.strip("._")[:hi]
        if len(cand) < lo or cand in out or validate_username(platform, cand):
            continue
        out.append(cand)
    return out


def validate_username(platform: Platform, username: str) -> str | None:
    """None neu hop le, khong thi mot cau tieng Viet noi vi sao."""
    lo, hi, pattern = USERNAME_RULES.get(platform, (2, 24, r"^[a-z0-9_.]+$"))
    u = username.strip().lstrip("@")
    if not u:
        return "username trống"
    if u != u.lower():
        return "username phải viết thường"
    if not (lo <= len(u) <= hi):
        return f"username phải dài {lo}-{hi} ký tự"
    if not re.match(pattern, u):
        allowed = "a-z, 0-9, _ và ." if "." in pattern else "a-z, 0-9 và _"
        return f"username chỉ được dùng {allowed}"
    if u.endswith(".") or ".." in u:
        return "username không được kết thúc bằng dấu chấm hay có hai dấu chấm liền"
    return None


# ------------------------------------------------------------------ ke hoach doi

PREFIX = "identity:"


def plan_to_target(plan: dict) -> str:
    """Ke hoach doi -> chuoi de vao ActivityJob.target_url (cot Text, khong co cot JSON)."""
    clean = {k: v for k, v in plan.items() if v}
    return PREFIX + json.dumps(clean, ensure_ascii=False, sort_keys=True)


def plan_from_target(target_url: str | None) -> dict:
    if not target_url or not target_url.startswith(PREFIX):
        return {}
    try:
        data = json.loads(target_url[len(PREFIX) :])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def describe(plan: dict) -> str:
    bits = []
    if plan.get("username"):
        bits.append(f"username → @{plan['username']}")
    if plan.get("display_name"):
        bits.append(f"tên → {plan['display_name']}")
    if plan.get("avatar"):
        bits.append("ảnh đại diện")
    return ", ".join(bits) or "không đổi gì"


# ------------------------------------------------------------------ anh dai dien


def avatar_variant(source: Path, dest: Path, seed: str, *, size: int = 640) -> Path:
    """Ban anh dai dien rieng cho mot tai khoan: cat vuong lech nhe, doi khi lat, chinh
    sang / tuong phan vai phan tram, luu JPEG. Cung seed cung ket qua."""
    from PIL import Image, ImageEnhance, ImageOps

    rng = random.Random(f"avatar:{seed}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        side = min(w, h)
        max_dx, max_dy = w - side, h - side
        # Lech toi da 40% khoang trong, quanh giua.
        dx = (max_dx // 2) + int(rng.uniform(-0.4, 0.4) * (max_dx // 2)) if max_dx else 0
        dy = (max_dy // 2) + int(rng.uniform(-0.4, 0.4) * (max_dy // 2)) if max_dy else 0
        im = im.crop((dx, dy, dx + side, dy + side))
        if rng.random() < 0.5:
            im = ImageOps.mirror(im)
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.94, 1.06))
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.94, 1.06))
        im = ImageEnhance.Color(im).enhance(rng.uniform(0.95, 1.05))
        im = im.resize((size, size), Image.Resampling.LANCZOS)
        im.save(dest, "JPEG", quality=rng.randint(86, 93), optimize=True)
    return dest
