"""Cua so trinh duyet tu dong khong duoc chen vao viec cua nguoi dang ngoi may.

Do that 21/09/2026 (Camoufox, Windows 11), trang trong, cung mot cu bam vao o nhap:

    cua so bi cua so khac che      rAF 0/giay   click() treo den het gio
    ... + tat occlusion tracking   rAF 60/giay  click() 0.09 giay     <- session.launch_options
    cua so bi thu nho              rAF 0/giay   click() treo, pref nao cung vay

Firefox tren Windows ngung ve cua so bi che/thu nho; Playwright doi hai khung hinh de coi mot
phan tu la "dung yen" nen cho mai. Nguoi van hanh chi can Alt+Tab la luong dang nhap dung.
Vi vay: (1) pref tat occlusion tracking, (2) module nay: day cua so ra SAU ma khong lay focus,
thay no bi thu nho thi bat lai (khong lay focus), va chi dua no len TREN CUNG khi co captcha
can nguoi - van khong lay focus, de phim dang go o ung dung khac khong roi vao trang.

Chi co tac dung tren Windows; he khac thi moi ham la no-op.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
import time

import structlog

log = structlog.get_logger(__name__)

WINDOW_CLASS = "MozillaWindowClass"
_IS_WINDOWS = sys.platform == "win32"

SW_SHOWNOACTIVATE, SW_MINIMIZE = 4, 6
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040
# Cua so thuoc tien trinh KHAC: gui yeu cau roi di tiep, khong dung cho giao dien trinh
# duyet dang ban/treo - ham nay chay ngay trong vong lap asyncio cua worker.
SWP_ASYNCWINDOWPOS = 0x4000
HWND_BOTTOM, HWND_TOPMOST, HWND_NOTOPMOST = 1, -1, -2
FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC
TH32CS_SNAPPROCESS = 0x2
MB_ICONEXCLAMATION = 0x30
# Cua so moi mo co the gianh focus TRE vai tram ms sau khi tao: trong khoang nay keep_alive
# cung tra focus ve. Qua khoang nay ma cua so la foreground thi la do NGUOI bam vao - de yen.
STARTUP_GRAB_S = 20.0

if _IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class _FLASHWINFO(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.UINT),
            ("hwnd", wintypes.HWND),
            ("dwFlags", wintypes.DWORD),
            ("uCount", wintypes.UINT),
            ("dwTimeout", wintypes.DWORD),
        )

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    _user32.EnumWindows.argtypes = (_ENUM_PROC, wintypes.LPARAM)
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = (wintypes.HWND,)
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = ()
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.argtypes = ()
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.ShowWindowAsync.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.FlashWindowEx.argtypes = (ctypes.POINTER(_FLASHWINFO),)
    _user32.FlashWindowEx.restype = wintypes.BOOL
    _user32.MessageBeep.argtypes = (wintypes.UINT,)
    _user32.MessageBeep.restype = wintypes.BOOL
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL


def _descendants(root_pid: int) -> set[int]:
    """Moi tien trinh con chau cua `root_pid` (worker -> driver Playwright -> Firefox -> tab)."""
    parents: dict[int, int] = {}
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return set()
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    found: set[int] = set()
    frontier = {root_pid}
    while frontier:
        frontier = {pid for pid, parent in parents.items() if parent in frontier} - found
        found |= frontier
    return found


def browser_windows() -> set[int]:
    """Cua so Firefox/Camoufox DANG HIEN do chinh tien trinh nay (va con chau) mo ra.

    Loc theo cay tien trinh de khong dung vao cua so nguoi van hanh tu mo ("Mo trinh duyet"
    chay tu tien trinh API) hay Firefox ca nhan cua ho."""
    if not _IS_WINDOWS:
        return set()
    try:
        family = _descendants(os.getpid())
        found: set[int] = set()

        def visit(hwnd, _lparam):
            if not _user32.IsWindowVisible(hwnd):
                return True
            name = ctypes.create_unicode_buffer(64)
            _user32.GetClassNameW(hwnd, name, 64)
            if name.value != WINDOW_CLASS:
                return True
            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in family:
                found.add(int(hwnd))
            return True

        _user32.EnumWindows(_ENUM_PROC(visit), 0)
        return found
    except Exception as exc:  # khong bao gio de viec sap xep cua so lam hong mot lan dang nhap
        log.warning("winfocus.enum_failed", error=type(exc).__name__)
        return set()


class WindowMinder:
    """Giu cua so cua MOT phien trinh duyet o phia sau; dua len khi can nguoi.

    Tao doi tuong nay TRUOC khi mo trinh duyet: no chup cac cua so dang co (cua so moi xuat
    hien sau do la cua phien nay) va cua so nguoi van hanh dang dung (de tra focus ve).
    Moi ham deu nuot loi: day la tien nghi, khong phai dieu kien de chay."""

    def __init__(self, before: set[int] | None = None, *, enabled: bool = True):
        self.enabled = enabled and _IS_WINDOWS
        self.before = set(before) if before is not None else set()
        self.previous = 0
        if self.enabled:
            if before is None:
                self.before = browser_windows()
            try:
                self.previous = int(_user32.GetForegroundWindow() or 0)
            except Exception:
                self.previous = 0
        self.windows: set[int] = set()
        self.surfaced = False
        self.seen_at: float | None = None  # luc cua so cua phien nay hien ra lan dau

    def _give_focus_back(self, hwnd: int) -> None:
        """Cua so moi mo co the GIANH focus: chi day no ra sau thi phim nguoi van hanh dang go van
        roi vao no. Tra focus ve cua so ho dang dung truoc do.

        Tien trinh nen khong duoc tuy y SetForegroundWindow; nhung khi gan luong nhap cua minh vao
        luong cua cua so DANG la foreground (cua so trinh duyet nay) thi Windows cho phep. Khong
        con cua so cu de tra ve (ho dong no roi) thi thu nho + bat lai khong kich hoat."""
        if int(_user32.GetForegroundWindow() or 0) != hwnd:
            return
        previous = self.previous
        if previous and previous != hwnd and _user32.IsWindow(wintypes.HWND(previous)):
            owner = _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
            me = _kernel32.GetCurrentThreadId()
            attached = bool(owner and owner != me and _user32.AttachThreadInput(me, owner, True))
            try:
                _user32.SetForegroundWindow(wintypes.HWND(previous))
            finally:
                if attached:
                    _user32.AttachThreadInput(me, owner, False)
        if int(_user32.GetForegroundWindow() or 0) == hwnd:
            _user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_MINIMIZE)
            _user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
        log.info(
            "winfocus.focus_returned",
            ok=int(_user32.GetForegroundWindow() or 0) != hwnd,
        )

    def _refresh(self) -> set[int]:
        if not self.enabled:
            return set()
        self.windows |= browser_windows() - self.before
        self.windows = {h for h in self.windows if _user32.IsWindow(wintypes.HWND(h))}
        if self.windows and self.seen_at is None:
            self.seen_at = time.monotonic()
        return self.windows

    def _place(self, hwnd: int, after: int, extra: int = 0) -> None:
        _user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(after),
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS | extra,
        )

    def tuck(self) -> None:
        """Ra sau moi cua so khac, khong lay focus. Goi lai bao nhieu lan cung duoc."""
        if not self.enabled:
            return
        try:
            for hwnd in self._refresh():
                if _user32.IsIconic(wintypes.HWND(hwnd)):
                    _user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                if self.surfaced:
                    self._place(hwnd, HWND_NOTOPMOST)
                self._give_focus_back(hwnd)
                self._place(hwnd, HWND_BOTTOM)
            self.surfaced = False
        except Exception as exc:
            log.warning("winfocus.tuck_failed", error=type(exc).__name__)

    def keep_alive(self) -> None:
        """Cua so bi THU NHO la Firefox ngung ve, moi cu bam treo: bat lai (khong lay focus)
        roi day ra sau. Cua so chi bi che thi khong sao - da co pref trong launch_options."""
        if not self.enabled or self.surfaced:
            return
        try:
            windows = self._refresh()
            grabbing = self.seen_at is not None and time.monotonic() - self.seen_at < STARTUP_GRAB_S
            for hwnd in windows:
                restored = bool(_user32.IsIconic(wintypes.HWND(hwnd)))
                if restored:
                    _user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                # Bat lai cua so co the keo theo focus (khi khong con cua so nao dang active).
                if (restored or grabbing) and int(_user32.GetForegroundWindow() or 0) == hwnd:
                    self._give_focus_back(hwnd)
                    restored = True
                if restored:
                    self._place(hwnd, HWND_BOTTOM)
        except Exception as exc:
            log.warning("winfocus.keep_alive_failed", error=type(exc).__name__)

    async def watch(self, interval: float = 1.0) -> None:
        """Chay nen suot phien: nguoi van hanh thu nho cua so GIUA mot thao tac (dang go 12 ky
        tu, dang cho mot cu bam) thi cu bam do treo den het gio - khong doi toi buoc ke tiep moi
        bat lai. Cung bat duoc luc cua so moi mo gianh focus tre."""
        while True:
            self.keep_alive()
            await asyncio.sleep(interval)

    def surface(self) -> None:
        """Captcha can nguoi: dua cua so len tren cung + nhay thanh tac vu + keu mot tieng.
        KHONG lay focus: nguoi dang go do o ung dung khac thi chu khong roi vao trang."""
        if not self.enabled:
            return
        try:
            for hwnd in self._refresh():
                if _user32.IsIconic(wintypes.HWND(hwnd)):
                    _user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                self._place(hwnd, HWND_TOPMOST, SWP_SHOWWINDOW)
                info = _FLASHWINFO(
                    ctypes.sizeof(_FLASHWINFO),
                    wintypes.HWND(hwnd),
                    FLASHW_ALL | FLASHW_TIMERNOFG,
                    0,
                    0,
                )
                _user32.FlashWindowEx(ctypes.byref(info))
            if not self.surfaced:
                _user32.MessageBeep(MB_ICONEXCLAMATION)
            self.surfaced = True
        except Exception as exc:
            log.warning("winfocus.surface_failed", error=type(exc).__name__)
