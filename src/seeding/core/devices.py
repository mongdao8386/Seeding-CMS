"""Thiet bi that: tim, doi soat, va rang buoc.

Duong nay song song voi Profile chu khong thay the no. Profile la mot danh tinh TRINH
DUYET (fingerprint + cookie jar); Device la mot danh tinh THIET BI (may that, app that).

Ly do ton tai: app that gui len nhung tin hieu ma trinh duyet khong co cach nao gia -
cam bien, do nghieng, ID thiet bi, nhip cham man hinh. Gia lap mobile bang cach doi
user-agent tren trinh duyet desktop khong cho ban nhung tin hieu do; no chi cho ban mot
chuoi chu, va mot fingerprint TU MAU THUAN (UA noi la iPhone, WebGL noi la card do hoa
may ban) de bi bat hon la mot profile desktop trung thuc.

MOT SU THAT VE iOS, ghi o day de khong ai mat mot ngay moi phat hien ra: tu dong hoa
app iOS bat buoc phai co macOS + Xcode de build va ky WebDriverAgent, va iOS Simulator
thi khong cai duoc app tu App Store. Tren Windows khong co duong nao. `DeviceOS.IOS`
ton tai vi mo hinh du lieu chiu duoc no, khong phai vi chay duoc.

Module nay chi lam phan KHONG can Appium: tim may qua adb, doc model, doi soat voi
database. Phan dieu khien app nam trong adapters/android.py va can Appium that.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import Device, DeviceOS, DeviceStatus

log = structlog.get_logger(__name__)

ADB_TIMEOUT = 15


@dataclass(slots=True)
class SeenDevice:
    """Mot may adb dang nhin thay ngay bay gio."""

    serial: str
    state: str  # device | unauthorized | offline
    model: str | None = None
    os_version: str | None = None

    @property
    def status(self) -> DeviceStatus:
        if self.state == "device":
            return DeviceStatus.READY
        if self.state == "unauthorized":
            return DeviceStatus.UNAUTHORIZED
        return DeviceStatus.OFFLINE


class AdbMissing(RuntimeError):
    """adb chua duoc cai hoac chua nam trong PATH."""


def adb_path() -> str | None:
    return shutil.which("adb")


def _run(args: list[str]) -> str:
    exe = adb_path()
    if exe is None:
        raise AdbMissing(
            "adb is not on PATH. Install Android Platform Tools and add it, then plug the "
            "phone in with USB debugging turned on."
        )
    result = subprocess.run(
        [exe, *args],
        capture_output=True,
        text=True,
        timeout=ADB_TIMEOUT,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {result.stderr.strip() or 'no output'}")
    return result.stdout


def parse_devices(output: str) -> list[SeenDevice]:
    """Doc dau ra cua `adb devices -l`.

    Tach rieng khoi phan goi lenh de kiem duoc ma khong can may that cam vao - va vi
    day la cho de sai am tham nhat: dong tieu de, dong trong, va may `unauthorized`
    deu trong gan giong may binh thuong.
    """
    seen: list[SeenDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        if line.startswith("*"):
            continue  # "* daemon started successfully *"

        parts = line.split()
        if len(parts) < 2:
            continue

        serial, state = parts[0], parts[1]
        extras = dict(piece.split(":", 1) for piece in parts[2:] if ":" in piece)
        seen.append(SeenDevice(serial=serial, state=state, model=extras.get("model")))
    return seen


def list_attached() -> list[SeenDevice]:
    """Cac may dang cam. Khong cham vao database."""
    return parse_devices(_run(["devices", "-l"]))


def android_version(serial: str) -> str | None:
    try:
        return _run(["-s", serial, "shell", "getprop", "ro.build.version.release"]).strip() or None
    except Exception as exc:
        log.warning("adb.getprop_failed", serial=serial, error=str(exc))
        return None


async def sync(session: AsyncSession) -> dict:
    """Doi soat may dang cam voi bang `devices`.

    Khong tu them may moi vao database: mot may cam vao de sac cung hien ra trong
    `adb devices`, va tu tao ban ghi cho no se lam danh sach day rac. Nguoi van hanh
    them tay mot lan, sau do ham nay chi cap nhat trang thai.
    """
    now = datetime.now(UTC)

    try:
        attached = await asyncio.to_thread(list_attached)
    except AdbMissing as exc:
        return {"ok": False, "detail": str(exc), "attached": 0, "updated": 0, "unknown": []}
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "attached": 0,
            "updated": 0,
            "unknown": [],
        }

    by_serial = {d.serial: d for d in attached}
    known = list((await session.execute(select(Device))).unique().scalars().all())

    updated = 0
    for device in known:
        found = by_serial.pop(device.serial, None)
        if found is None:
            # Rut day ra thi phai thanh offline. De nguyen READY nghia la worker se giao
            # viec cho mot may khong con o do, roi job that bai vi mot ly do khong lien
            # quan gi den ly do that.
            if device.status is not DeviceStatus.OFFLINE:
                device.status = DeviceStatus.OFFLINE
                device.last_error = "not attached"
                updated += 1
            continue

        device.status = found.status
        device.last_seen_at = now
        device.last_error = None if found.status is DeviceStatus.READY else found.state
        if found.model and not device.model:
            device.model = found.model
        if device.os is DeviceOS.ANDROID and not device.os_version:
            device.os_version = await asyncio.to_thread(android_version, device.serial)
        updated += 1

    await session.commit()

    return {
        "ok": True,
        "attached": len(attached),
        "updated": updated,
        # May dang cam ma chua co trong database - de nguoi van hanh them, khong tu them.
        "unknown": [
            {"serial": d.serial, "state": d.state, "model": d.model} for d in by_serial.values()
        ],
    }


async def usable(session: AsyncSession) -> list[Device]:
    """May san sang nhan viec: dang cam, va da gan cho mot tai khoan."""
    stmt = select(Device).where(
        Device.status == DeviceStatus.READY,
        Device.account_id.isnot(None),
    )
    return list((await session.execute(stmt)).unique().scalars().all())


def preflight() -> dict:
    """Nhung gi con thieu de duong thiet bi chay duoc.

    Tra ve mot danh sach thay vi nem loi o buoc dau tien: nguoi dung can thay HET moi
    thu con thieu trong mot lan, chu khong phai cai mot thu roi phat hien ra thu tiep.
    """
    problems: list[str] = []

    if adb_path() is None:
        problems.append(
            "adb is not on PATH — install Android Platform Tools "
            "(https://developer.android.com/tools/releases/platform-tools)"
        )

    try:
        import appium  # noqa: F401
    except ImportError:
        problems.append(
            "the Appium Python client is not installed — pip install Appium-Python-Client"
        )

    return {
        "ready": not problems,
        "problems": problems,
        "adb": adb_path(),
        "note": (
            "iOS cannot be driven from Windows at all: automating an iOS app needs macOS and "
            "Xcode to build and sign WebDriverAgent, and the iOS Simulator cannot install App "
            "Store apps. Android only on this machine."
        ),
    }
