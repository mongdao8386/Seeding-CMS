"""Noi cat file goc: thu muc tren may, hoac Supabase Storage.

CHIA VIEC CO CHU Y - khong phai thu gi cung day len kho tu xa:

    sources/   file goc, KHONG sinh lai duoc  -> len kho tu xa (neu bat)
    thumbs/    anh xem truoc, re, dashboard can -> len kho tu xa (neu bat)
    variants/  ban render cho tung tai khoan  -> LUON o may local

Bien the o lai may vi ba ly do: chung sinh lai duoc bat cu luc nao tu cong thuc co
seed, chung bi don theo tuoi, va ffmpeg can mot duong dan that de doc. Day chung len
kho tu xa la tra tien bang thong cho thu se bi xoa trong hai tuan.

Doi lai, file goc dat tren Supabase thi nhieu may worker dung chung duoc mot kho, va
o dia may ban khong phinh theo so chien dich.

CAN NHAC TRUOC KHI BAT: media chinh la noi dung seeding cua ban. Ca he thong nay chay
local va fail-closed; day file len bucket cua ben thu ba la doi han muc phoi bay. Neu
chi chay mot may thi backend `local` van la lua chon dung.
"""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx
import structlog

from seeding.config import get_settings

log = structlog.get_logger(__name__)


class StorageError(RuntimeError):
    pass


@runtime_checkable
class Storage(Protocol):
    """Kho file phang: khoa la duong dan tuong doi kieu 'sources/clip.mp4'."""

    def put(self, key: str, source: Path) -> None: ...

    def fetch(self, key: str, dest: Path) -> Path:
        """Bao dam co mot file THAT tai `dest` de ffmpeg doc duoc."""
        ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class LocalStorage:
    """Thu muc tren may. Khoa la duong dan tuong doi tinh tu goc kho."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        # Chan thoat thu muc: khoa den tu ten file nguoi dung dat.
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise StorageError(f"key escapes the store: {key!r}")
        return path

    def put(self, key: str, source: Path) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != dest:
            shutil.copyfile(source, dest)

    def fetch(self, key: str, dest: Path) -> Path:
        path = self._path(key)
        if not path.exists():
            raise StorageError(f"not in the store: {key}")
        return path  # da la file that roi, khong can chep di dau

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except (OSError, StorageError) as exc:
            log.warning("storage.delete_failed", key=key, error=str(exc))

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).exists()
        except StorageError:
            return False


class SupabaseStorage:
    """Supabase Storage qua REST.

    Dung service key, nen moi request deu di thang qua Row Level Security. Khoa nay
    tuong duong quyen quan tri bucket - no chi bao gio roi khoi may chu API, va khong
    bao gio duoc gui xuong trinh duyet.
    """

    def __init__(
        self,
        url: str,
        service_key: str,
        bucket: str,
        cache_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base = url.rstrip("/")
        self.bucket = bucket
        self.cache_dir = cache_dir
        # Mot client dung chung: tai mot lo mười file thi bat tay TLS mot lan la du.
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
            timeout=120,
            transport=transport,
        )

    def _object_url(self, key: str) -> str:
        return f"{self.base}/storage/v1/object/{self.bucket}/{key.lstrip('/')}"

    def put(self, key: str, source: Path) -> None:
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        response = self._client.post(
            self._object_url(key),
            content=source.read_bytes(),
            headers={
                "Content-Type": content_type,
                # Ghi de neu da co: upload lai cung mot ten la y dinh binh thuong.
                "x-upsert": "true",
            },
        )
        if response.status_code >= 400:
            raise StorageError(f"upload failed ({response.status_code}): {response.text[:300]}")
        log.info("storage.uploaded", key=key, bucket=self.bucket)

    def fetch(self, key: str, dest: Path) -> Path:
        """Tai ve cache local. Da co trong cache thi khong tai lai."""
        cached = self.cache_dir / key
        if cached.exists() and cached.stat().st_size > 0:
            return cached

        response = self._client.get(self._object_url(key))
        if response.status_code >= 400:
            raise StorageError(f"download failed ({response.status_code}): {key}")

        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(response.content)
        log.info("storage.cached", key=key, bytes=len(response.content))
        return cached

    def delete(self, key: str) -> None:
        response = self._client.request("DELETE", self._object_url(key))
        if response.status_code >= 400 and response.status_code != 404:
            log.warning("storage.delete_failed", key=key, status=response.status_code)
        (self.cache_dir / key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._client.head(self._object_url(key)).status_code < 400


def build(root: Path, cache_dir: Path) -> Storage:
    """Chon backend theo cau hinh. Thieu thong tin thi bao ngay thay vi im lang ve local."""
    settings = get_settings()
    backend = (settings.media_backend or "local").lower()

    if backend == "local":
        return LocalStorage(root)

    if backend == "supabase":
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", settings.supabase_url),
                ("SUPABASE_SERVICE_KEY", settings.supabase_service_key),
                ("SUPABASE_BUCKET", settings.supabase_bucket),
            )
            if not value
        ]
        if missing:
            raise StorageError(
                f"MEDIA_BACKEND=supabase but {', '.join(missing)} is not set in .env"
            )
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_key,
            settings.supabase_bucket,
            cache_dir,
        )

    raise StorageError(f"Unknown MEDIA_BACKEND {backend!r}. Use 'local' or 'supabase'.")
