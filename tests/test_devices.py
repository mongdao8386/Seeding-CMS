"""Duong thiet bi that.

Cai kiem duoc o day ma khong can cam may: doc dau ra cua `adb devices -l`. Do la cho
de sai am tham nhat - dong tieu de, dong rac cua daemon, va may `unauthorized` deu
trong gan giong mot may binh thuong, va nham mot cai la worker giao viec cho mot may
khong nhan viec duoc.
"""

import pytest

from seeding.core import devices
from seeding.models import DeviceStatus

REAL = """List of devices attached
R3CT90ABCDE            device usb:1-4 product:a52qnaxx model:SM_A525F device:a52q transport_id:3
emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 transport_id:5
"""


def test_reads_a_normal_listing():
    seen = devices.parse_devices(REAL)
    assert [d.serial for d in seen] == ["R3CT90ABCDE", "emulator-5554"]
    assert seen[0].model == "SM_A525F"


def test_the_header_line_is_not_a_device():
    """`List of devices attached` bi doc thanh mot may thi no se hien ra trong danh
    sach nhu mot thiet bi ma - va no khong bao gio bien mat."""
    assert devices.parse_devices("List of devices attached\n") == []


def test_daemon_noise_is_ignored():
    noisy = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n" + REAL
    assert len(devices.parse_devices(noisy)) == 2


def test_an_empty_listing_is_not_an_error():
    assert devices.parse_devices("") == []


def test_a_device_in_device_state_is_ready():
    assert devices.parse_devices(REAL)[0].status is DeviceStatus.READY


def test_an_unauthorized_phone_is_not_ready():
    """Cam day nhung chua bam "cho phep go loi USB". No hien ra trong `adb devices` gan
    giong may binh thuong, nhung khong nhan duoc lenh nao - coi no la READY nghia la
    giao viec cho no roi doi mai."""
    seen = devices.parse_devices("List of devices attached\nR3CT90ABCDE\tunauthorized\n")
    assert seen[0].status is DeviceStatus.UNAUTHORIZED


def test_an_offline_phone_is_not_ready():
    seen = devices.parse_devices("List of devices attached\nR3CT90ABCDE\toffline\n")
    assert seen[0].status is DeviceStatus.OFFLINE


def test_a_line_with_no_state_is_skipped_rather_than_guessed():
    assert devices.parse_devices("List of devices attached\nR3CT90ABCDE\n") == []


# ------------------------------------------------------------------ preflight


def test_preflight_lists_everything_missing_at_once():
    """Bao mot thu thieu roi dung nghia la nguoi dung cai xong lai chay lai de gap thu
    tiep theo. Voi mot chuoi cong cu Android thi do la ca buoi chieu."""
    result = devices.preflight()
    assert isinstance(result["problems"], list)
    assert result["ready"] == (len(result["problems"]) == 0)


def test_preflight_says_ios_is_impossible_here_rather_than_just_missing():
    """Thieu adb thi cai them la xong. iOS tren Windows thi khong co duong nao - do la
    buc tuong nen tang, va noi ro no ra tiet kiem cho nguoi dung mot ngay."""
    note = devices.preflight()["note"].lower()
    assert "ios" in note
    assert "macos" in note or "xcode" in note


# ------------------------------------------------------- adb thieu thi noi ro


def test_calling_adb_without_adb_installed_says_what_to_install(monkeypatch):
    monkeypatch.setattr(devices, "adb_path", lambda: None)
    with pytest.raises(devices.AdbMissing, match="PATH"):
        devices.list_attached()


async def test_sync_without_adb_reports_instead_of_exploding(monkeypatch):
    """Vong quet khong duoc chet chi vi chua cam may nao. Do la trang thai binh thuong
    cua mot he thong dang chay hoan toan bang trinh duyet."""
    monkeypatch.setattr(devices, "adb_path", lambda: None)
    result = await devices.sync(None)
    assert result["ok"] is False
    assert "PATH" in result["detail"]
