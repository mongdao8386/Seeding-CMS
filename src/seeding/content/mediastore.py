"""Kho media: tu file goc ra ban bien the cua tung tai khoan, co cache.

Render dien ra LUC SAP DANG chu khong luc lap ke hoach. Mot chien dich 100 tai khoan
ma render ngay luc lap ke hoach thi phai cho vai phut moi thay duoc lich; con render
sat luc dang thi chi phi rai deu theo dung nhip stagger von da co.

Cache dat theo cong thuc bien doi, ma cong thuc lai sinh tu seed co dinh cua
(campaign, account). Nen lap ke hoach lai khong bao gio render lai - dung tinh than
voi idempotency_key ben planner.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from seeding.config import get_settings
from seeding.content import media, storage

log = structlog.get_logger(__name__)


def root() -> Path:
    return Path(get_settings().media_root)


def sources_dir() -> Path:
    path = root() / "sources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def variants_dir() -> Path:
    path = root() / "variants"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbs_dir() -> Path:
    path = root() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    """Noi giu ban tai ve tu kho tu xa, de ffmpeg co file that ma doc."""
    path = root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend() -> storage.Storage:
    """Kho dang dung. Doc cau hinh moi lan goi de doi backend khong phai khoi dong lai."""
    return storage.build(root(), cache_dir())


def store_upload(local_path: Path, filename: str) -> None:
    """Dua mot file goc vua tai len vao kho.

    Backend local thi file da nam dung cho; backend tu xa thi day len roi giu ban local
    lam cache - khong xoa di, vi render dau tien se can no ngay.
    """
    backend().put(f"sources/{filename}", local_path)


def store_thumbnail(filename: str) -> None:
    thumb = thumbs_dir() / filename
    if thumb.exists():
        backend().put(f"thumbs/{filename}", thumb)


def local_thumbnail(filename: str) -> Path | None:
    """Duong dan anh xem truoc, tai ve tu kho neu can. None neu khong co."""
    local = thumbs_dir() / filename
    if local.exists():
        return local
    try:
        return backend().fetch(f"thumbs/{filename}", local)
    except storage.StorageError:
        return None


def safe_filename(original: str) -> str:
    """Ten file an toan, khong trung, va khong thoat ra khoi thu muc kho.

    Nguoi dung dat ten file, nen phai coi no la du lieu khong tin duoc: bo duong dan,
    bo ky tu la, va them hau to ngan neu da co file cung ten.
    """
    stem = Path(original).stem[:80]
    suffix = Path(original).suffix.lower()[:10]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "media"

    candidate = f"{stem}{suffix}"
    if not (sources_dir() / candidate).exists():
        return candidate

    return f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def probe(path: Path) -> dict:
    """Kich thuoc va do dai, doc tu ffmpeg. Doc duoc gi tra ve nay, khong nem loi."""
    result = subprocess.run(
        [media.ffmpeg_exe(), "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    info: dict = {"width": None, "height": None, "duration_seconds": None}

    if size := re.search(r"(\d{2,5})x(\d{2,5})", result.stderr):
        info["width"], info["height"] = int(size.group(1)), int(size.group(2))

    if stamp := re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr):
        h, m, s = stamp.groups()
        seconds = int(h) * 3600 + int(m) * 60 + float(s)
        # Anh tinh cũng ra mot "duration" vo nghia; chi giu neu that su co do dai.
        info["duration_seconds"] = seconds if seconds > 0.05 else None

    return info


def make_thumbnail(source: Path, name: str) -> str | None:
    """Anh xem truoc .jpg rong toi da 480px. Tra ve ten file, None neu that bai."""
    dest = thumbs_dir() / f"{Path(name).stem}.jpg"
    try:
        media._run(
            [
                media.ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                *(["-ss", "00:00:01"] if source.suffix.lower() in media.VIDEO_SUFFIXES else []),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(480,iw)':-2",
                "-q:v",
                "4",
                str(dest),
            ]
        )
    except media.MediaError:
        # Video ngan hon 1 giay thi -ss vuot qua het phim; thu lai tu khung dau.
        try:
            media._run(
                [
                    media.ffmpeg_exe(),
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(480,iw)':-2",
                    "-q:v",
                    "4",
                    str(dest),
                ]
            )
        except media.MediaError as exc:
            log.warning("media.thumbnail_failed", source=source.name, error=str(exc))
            return None

    return dest.name if dest.exists() else None


def resolve_source(media_ref: str) -> Path:
    """Duong dan THAT toi file goc, tai ve tu kho tu xa neu can.

    ffmpeg doc file chu khong doc URL, nen buoc nay bat buoc voi backend tu xa. Ban tai
    ve nam trong cache va dung lai cho cac lan render sau.
    """
    candidate = Path(media_ref)
    if candidate.is_absolute():
        return candidate

    local = sources_dir() / media_ref
    if local.exists():
        return local

    return backend().fetch(f"sources/{media_ref}", local)


def variant_path(source: Path, recipe: media.VariantRecipe) -> Path:
    """Duong dan on dinh cho mot cap (file goc, cong thuc)."""
    key = hashlib.sha256(f"{source.name}|{recipe}".encode()).hexdigest()[:16]
    return variants_dir() / f"{source.stem}-{key}{source.suffix}"


MAX_ROLLS = 4


def ensure_variant(
    media_ref: str,
    *seed_parts: object,
    strength: media.Strength = media.Strength.MODERATE,
    avoid: set[str] | None = None,
) -> tuple[Path, str]:
    """Tra ve (duong dan ban bien the, pHash). Da co san thi khong render lai.

    `avoid` la cac pHash da duoc dung trong cung chien dich. Cong thuc sinh ngau nhien
    van co the cho ra hai ban tri giac giong het nhau - do luong thuc te tren video mau
    cho thay o muc moderate, hai trong nam tai khoan trung pHash. Trung nhu vay la mat
    het y nghia cua viec sinh bien the, nen o day rut lai voi seed khac.
    """
    source = resolve_source(media_ref)
    if not source.exists():
        raise media.MediaError(f"khong tim thay file goc: {source}")

    last: tuple[Path, str] | None = None

    for roll in range(MAX_ROLLS):
        parts = seed_parts if roll == 0 else (*seed_parts, f"lan{roll}")
        recipe = media.recipe_for(*parts, strength=strength)
        dest = variant_path(source, recipe)

        if dest.exists() and dest.stat().st_size > 0:
            phash = media.perceptual_hash(dest)
        else:
            log.info("media.rendering", source=source.name, recipe=recipe.describe())
            media.render(source, dest, recipe)
            phash = media.perceptual_hash(dest)
            log.info("media.rendered", dest=dest.name, phash=phash)

        last = (dest, phash)
        if not avoid or phash not in avoid:
            return last

        log.info("media.phash_collision", phash=phash, roll=roll + 1)

    # Rut het luot van trung. Tra ve ban cuoi kem canh bao thay vi chan job lai:
    # co bai dang van hon la khong, nhung phai biet la no trung.
    log.warning(
        "media.phash_still_colliding",
        phash=last[1],
        note="tang media_strength hoac dung noi dung goc khac",
    )
    return last


def prune(max_age_days: int, *, dry_run: bool = False) -> dict:
    """Xoa ban bien the cu hon `max_age_days`.

    Chi dong vao thu muc variants, khong bao gio cham vao sources: ban goc la thu khong
    sinh lai duoc, con bien the thi render lai duoc bat cu luc nao vi cong thuc sinh tu
    seed co dinh.

    Bai da dang roi thi ban bien the khong con tac dung gi; giu lai chi ton dia. Mot
    chien dich 100 tai khoan voi video 5 MB la 500 MB cho MOT bai.
    """
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    removed, freed = 0, 0

    for path in variants_dir().iterdir():
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified >= cutoff:
            continue

        size = path.stat().st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError as exc:
                log.warning("media.prune_failed", path=path.name, error=str(exc))
                continue
        removed += 1
        freed += size

    if removed:
        log.info(
            "media.pruned",
            removed=removed,
            freed_mb=round(freed / 1_048_576, 1),
            dry_run=dry_run,
        )

    return {"removed": removed, "freed_bytes": freed, "dry_run": dry_run}


def delete_source(filename: str, thumbnail: str | None = None) -> None:
    """Xoa file goc va anh xem truoc. Bo qua file da khong con.

    Cac ban bien the da render tu file nay khong xoa o day - chung tu het han theo
    MEDIA_VARIANT_KEEP_DAYS, va bai da dang roi thi cung khong con can den chung.
    """
    store = backend()
    store.delete(f"sources/{filename}")
    if thumbnail:
        store.delete(f"thumbs/{thumbnail}")

    # Ban local va cache: backend local da xoa o tren, day la don not cho backend tu xa.
    targets = [sources_dir() / filename, cache_dir() / "sources" / filename]
    if thumbnail:
        targets.append(thumbs_dir() / thumbnail)

    for path in targets:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("media.delete_failed", path=path.name, error=str(exc))


def usage() -> dict:
    """Kho dang chiem bao nhieu."""

    def measure(folder: Path) -> tuple[int, int]:
        files = [p for p in folder.iterdir() if p.is_file()] if folder.exists() else []
        return len(files), sum(p.stat().st_size for p in files)

    src_count, src_bytes = measure(sources_dir())
    var_count, var_bytes = measure(variants_dir())

    return {
        "sources": src_count,
        "sources_bytes": src_bytes,
        "variants": var_count,
        "variants_bytes": var_bytes,
    }


def report(media_ref: str, seeds: list[tuple], *, strength=media.Strength.MODERATE) -> dict:
    """Sinh bien the cho nhieu tai khoan roi do khoang cach giua chung.

    Bao cao chu khong khang dinh: `min_phash_distance` bang 0 nghia la co hai ban ma
    mot bo so khop tri giac van coi la mot file.
    """
    rendered: list[tuple[Path, str]] = []
    taken: set[str] = set()
    for seed in seeds:
        path, phash = ensure_variant(media_ref, *seed, strength=strength, avoid=taken)
        rendered.append((path, phash))
        taken.add(phash)

    hashes = [h for _, h in rendered]
    files = {media.file_hash(p) for p, _ in rendered}

    distances = [
        media.phash_distance(hashes[i], hashes[j])
        for i in range(len(hashes))
        for j in range(i + 1, len(hashes))
    ]

    return {
        "count": len(rendered),
        "unique_files": len(files),
        "all_bytes_differ": len(files) == len(rendered),
        "min_phash_distance": min(distances) if distances else None,
        "max_phash_distance": max(distances) if distances else None,
        "paths": [str(p) for p, _ in rendered],
    }
