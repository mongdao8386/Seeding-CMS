"""Kiem tra kho media that su hoat dong, voi dung cau hinh trong .env.

    python scripts/check_storage.py

Chay mot vong tron: ghi len - doc ve - so tung byte - xoa di. Voi backend supabase,
day la lan goi mang that toi bucket cua ban.

Chay cai nay NGAY SAU khi doi MEDIA_BACKEND, truoc khi upload thu gi quan trong. Kho
cau hinh sai thi loi chi lo ra luc worker sap dang bai, va luc do la muon.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from seeding.config import get_settings
from seeding.core import mediastore, storage


def main() -> int:
    settings = get_settings()
    backend_name = (settings.media_backend or "local").lower()

    print(f"\nBackend: {backend_name}")
    if backend_name == "supabase":
        print(f"  url:    {settings.supabase_url}")
        print(f"  bucket: {settings.supabase_bucket}")
        key = settings.supabase_service_key
        print(f"  key:    {key[:6]}…{key[-4:] if len(key) > 10 else ''} ({len(key)} ky tu)")
    else:
        print(f"  root:   {mediastore.root().resolve()}")

    try:
        store = mediastore.backend()
    except storage.StorageError as exc:
        print(f"\n  [LOI] {exc}\n")
        return 1

    probe_key = f"sources/_check-{uuid.uuid4().hex[:8]}.txt"
    payload = b"seeding-cms storage check"

    scratch = mediastore.cache_dir() / "_check.txt"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_bytes(payload)

    steps: list[tuple[str, bool, str]] = []

    try:
        store.put(probe_key, scratch)
        steps.append(("ghi len kho", True, probe_key))
    except Exception as exc:
        steps.append(("ghi len kho", False, str(exc)))
        return _report(steps)

    try:
        steps.append(("kho bao la co", store.exists(probe_key), ""))
    except Exception as exc:
        steps.append(("kho bao la co", False, str(exc)))

    try:
        fetched = store.fetch(probe_key, Path(scratch))
        same = fetched.read_bytes() == payload
        steps.append(("doc ve va so byte", same, "" if same else "noi dung khong khop"))
    except Exception as exc:
        steps.append(("doc ve va so byte", False, str(exc)))

    try:
        store.delete(probe_key)
        gone = not store.exists(probe_key)
        steps.append(("xoa di", gone, "" if gone else "van con tren kho"))
    except Exception as exc:
        steps.append(("xoa di", False, str(exc)))

    scratch.unlink(missing_ok=True)
    return _report(steps)


def _report(steps: list[tuple[str, bool, str]]) -> int:
    print()
    for label, ok, note in steps:
        print(f"  [{'OK ' if ok else 'LOI'}] {label}{f' — {note}' if note else ''}")

    failed = [s for s in steps if not s[1]]
    print()
    if failed:
        print("  Kho chua dung. Vai cho hay sai:")
        print("    - bucket chua ton tai, hoac ten viet khac trong .env")
        print("    - dung anon/publishable key thay vi service key")
        print("    - policy cua bucket chan service role (hiem, nhung co)")
        print()
        return 1

    print("  Kho chay dung.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
