"""Mo cua so trinh duyet cua mot profile tu dashboard.

Trinh duyet KHONG duoc mo ben trong tien trinh API. Hai ly do, ca hai deu tung lam
hong that:

  - Mot phien Camoufox song vai chuc phut va ton ~400MB. Giu no trong uvicorn nghia
    la vong doi cua no gan voi vong doi may chu API - `--reload` khoi dong lai la
    cua so bien mat giua chung, con cookie thi chua kip luu.
  - API phai tra loi ngay. Mo trinh duyet mat hang chuc giay qua proxy dan cu.

Nen o day chi SINH mot tien trinh rieng roi buong tay. Tien trinh do tu luu cookie
va tu ket thuc khi nguoi dung dong cua so.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "open_profile.py"


def command(profile_id: uuid.UUID, url: str | None = None) -> list[str]:
    """Dong lenh se duoc chay. Tach ra de kiem duoc ma khong sinh tien trinh that."""
    cmd = [sys.executable, str(SCRIPT), str(profile_id)]
    if url:
        cmd.append(url)
    return cmd


def spawn(profile_id: uuid.UUID, url: str | None = None) -> int:
    """Sinh tien trinh mo profile, tra ve PID. Khong cho no chay xong.

    `start_new_session` / `DETACHED_PROCESS` de tien trinh con song tiep khi may chu
    API khoi dong lai - nguoi dung dang go do trong cua so do, dung giet no giua chung.
    """
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "cwd": str(SCRIPT.parent.parent),
    }
    if sys.platform == "win32":
        # CREATE_NO_WINDOW: khong hien them mot cua so console den ben canh trinh duyet.
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(command(profile_id, url), **kwargs)
    log.info("desktop.spawned", profile=str(profile_id), pid=proc.pid, url=url)
    return proc.pid
