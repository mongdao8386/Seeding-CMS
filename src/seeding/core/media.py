"""Sinh bien the media cho tung tai khoan.

Van ban khac nhau la chua du. Neu muoi tai khoan upload cung mot file video giong het
tung byte thi he thong nhan dien noi dung trung bat duoc ngay.

VE MUC DO HIEU QUA, noi that:

    Cac phep bien doi o day CHAC CHAN pha duoc so khop theo hash file - do la dieu
    kien can, va no re. Chung KHONG chac pha duoc so khop tri giac (perceptual
    matching) cua nen tang: pHash duoc thiet ke de chiu dung dung nhung thay doi nho
    kieu nay. Cang bien doi manh de pHash dich chuyen thi anh/video cang xuong cap
    thay ro.

    Neu nen tang so khop tri giac tot, cau tra loi that su khong nam o day ma o cho
    khac: quay/dung noi dung goc khac nhau cho tung nhom tai khoan.

Vi vay module nay do va bao cao khoang cach pHash thay vi khang dinh "da du khac".
Ban nhin so roi tu quyet.
"""

from __future__ import annotations

import hashlib
import random
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import imagehash
import imageio_ffmpeg
import structlog
from PIL import Image

log = structlog.get_logger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class Strength(StrEnum):
    """Danh doi giua "khong nhin ra" va "pHash dich duoc"."""

    SUBTLE = "subtle"  # mat thuong khong thay; chi pha duoc hash file
    MODERATE = "moderate"  # hoi khac; pHash bat dau dich
    AGGRESSIVE = "aggressive"  # co lat guong; pHash dich ro, nhung nhin ra duoc


class MediaError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass(frozen=True, slots=True)
class VariantRecipe:
    crop: float  # ty le cat vien moi ben
    speed: float  # he so toc do (video)
    brightness: float
    saturation: float
    noise: int
    crf: int
    mirror: bool

    def describe(self) -> str:
        parts = [
            f"cat {self.crop * 100:.1f}%",
            f"toc do {self.speed:.3f}x",
            f"sang {self.brightness:+.3f}",
            f"bao hoa {self.saturation:.3f}",
            f"nhieu {self.noise}",
            f"crf {self.crf}",
        ]
        if self.mirror:
            parts.append("lat guong")
        return ", ".join(parts)


_RANGES = {
    Strength.SUBTLE: dict(
        crop=(0.005, 0.02),
        speed=(0.99, 1.01),
        bright=(-0.02, 0.02),
        sat=(0.98, 1.02),
        noise=(2, 5),
        crf=(20, 23),
        mirror=False,
    ),
    Strength.MODERATE: dict(
        crop=(0.02, 0.06),
        speed=(0.96, 1.04),
        bright=(-0.05, 0.05),
        sat=(0.94, 1.06),
        noise=(4, 10),
        crf=(22, 27),
        mirror=False,
    ),
    Strength.AGGRESSIVE: dict(
        crop=(0.06, 0.12),
        speed=(0.92, 1.08),
        bright=(-0.08, 0.08),
        sat=(0.88, 1.12),
        noise=(8, 16),
        crf=(24, 30),
        mirror=True,
    ),
}


def recipe_for(*seed_parts: object, strength: Strength = Strength.MODERATE) -> VariantRecipe:
    """Cong thuc bien doi, sinh tu seed co dinh.

    Dung cung kieu seed voi spintax: lap ke hoach lai cho cung mot (campaign, account)
    phai ra dung file cu, khong sinh ban moi.
    """
    digest = hashlib.sha256(":".join(str(p) for p in seed_parts).encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    r = _RANGES[strength]

    return VariantRecipe(
        crop=rng.uniform(*r["crop"]),
        speed=rng.uniform(*r["speed"]),
        brightness=rng.uniform(*r["bright"]),
        saturation=rng.uniform(*r["sat"]),
        noise=rng.randint(*r["noise"]),
        crf=rng.randint(*r["crf"]),
        mirror=r["mirror"] and rng.random() < 0.5,
    )


def render(source: Path, dest: Path, recipe: VariantRecipe) -> Path:
    """Sinh mot ban bien the. Tra ve duong dan ket qua."""
    source, dest = Path(source), Path(dest)
    if not source.exists():
        raise MediaError(f"khong tim thay file goc: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()

    if suffix in VIDEO_SUFFIXES:
        _run(_video_command(source, dest, recipe))
    elif suffix in IMAGE_SUFFIXES:
        _run(_image_command(source, dest, recipe))
    else:
        raise MediaError(f"chua ho tro duoi {suffix}")

    if not dest.exists() or dest.stat().st_size == 0:
        raise MediaError(f"ffmpeg chay xong nhung khong ra file: {dest}")
    return dest


def _filters(recipe: VariantRecipe, *, video: bool) -> str:
    # Cat deu bon phia roi ep ve so chan - h264 khong nhan kich thuoc le.
    keep = 1 - recipe.crop * 2
    chain = [
        f"crop=floor(iw*{keep:.4f}/2)*2:floor(ih*{keep:.4f}/2)*2",
        f"eq=brightness={recipe.brightness:.4f}:saturation={recipe.saturation:.4f}",
        f"noise=alls={recipe.noise}:allf=t+u",
    ]
    if recipe.mirror:
        chain.append("hflip")
    if video and abs(recipe.speed - 1.0) > 1e-6:
        chain.append(f"setpts={1 / recipe.speed:.6f}*PTS")
    return ",".join(chain)


def _video_command(source: Path, dest: Path, recipe: VariantRecipe) -> list[str]:
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vf",
        _filters(recipe, video=True),
    ]
    if abs(recipe.speed - 1.0) > 1e-6:
        # atempo chi nhan 0.5-2.0; day luon trong khoang do nen mot tang la du.
        cmd += ["-filter:a", f"atempo={recipe.speed:.6f}"]
    cmd += [
        "-c:v",
        "libx264",
        "-crf",
        str(recipe.crf),
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        # Xoa sach metadata: ten may quay, phan mem dung, toa do GPS deu la dau vet noi
        # cac tai khoan lai voi nhau.
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    return cmd


def _image_command(source: Path, dest: Path, recipe: VariantRecipe) -> list[str]:
    quality = max(2, min(31, recipe.crf - 12))
    return [
        ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vf",
        _filters(recipe, video=False),
        "-q:v",
        str(quality),
        "-map_metadata",
        "-1",
        str(dest),
    ]


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MediaError(f"ffmpeg loi ({result.returncode}): {result.stderr.strip()[:600]}")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def perceptual_hash(path: Path) -> str:
    """pHash cua anh, hoac cua mot khung hinh giua video."""
    path = Path(path)
    if path.suffix.lower() in VIDEO_SUFFIXES:
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            _run(
                [
                    ffmpeg_exe(),
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "select=eq(n\\,0)",
                    str(frame),
                ]
            )
            return str(imagehash.phash(Image.open(frame)))
    return str(imagehash.phash(Image.open(path)))


def phash_distance(a: str, b: str) -> int:
    """Khoang cach Hamming giua hai pHash. 0 = tri giac giong het.

    Ep ve int thuan: imagehash tra ve np.int64, ma kieu do khong JSON hoa duoc nen se
    vo khi con so nay di vao cot JSON hoac ra API.
    """
    return int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))


def compare(a: Path, b: Path) -> dict:
    """So hai file. Dung de TU KIEM TRA, khong phai de khang dinh da du khac.

    `bytes_differ` la dieu kien can, gan nhu luon dat.
    `phash_distance` moi la con so dang nhin: 0 nghia la voi mot bo so khop tri giac
    thi hai file nay van la mot.
    """
    ha, hb = perceptual_hash(a), perceptual_hash(b)
    return {
        "bytes_differ": file_hash(a) != file_hash(b),
        "phash_a": ha,
        "phash_b": hb,
        "phash_distance": phash_distance(ha, hb),
    }


def make_test_video(dest: Path, seconds: int = 2) -> Path:
    """Video mau de thu pipeline ma khong can file that."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=640x360:rate=24:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-shortest",
            str(dest),
        ]
    )
    return dest


def probe_duration(path: Path) -> float:
    """Do dai video, doc tu ffmpeg (khong can ffprobe rieng)."""
    result = subprocess.run(
        [ffmpeg_exe(), "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    for line in result.stderr.splitlines():
        if "time=" in line:
            stamp = line.rsplit("time=", 1)[1].split(" ", 1)[0]
            try:
                h, m, s = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                continue
    raise MediaError(f"khong doc duoc do dai cua {path}")


def have_ffmpeg() -> bool:
    """imageio-ffmpeg mang theo binary rieng, nhung van kiem tra cho chac."""
    try:
        return Path(ffmpeg_exe()).exists()
    except Exception:
        return False
