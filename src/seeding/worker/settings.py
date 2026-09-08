"""Cau hinh worker ARQ.  Chay bang:  arq seeding.worker.settings.WorkerSettings

Phan 0/1 chua co job nao: worker chi giu nhip de Start.cmd va man hinh Tong quan
thay no song. Job dang bai va nuoi tai khoan vao o phan 2 va 3.
"""

from __future__ import annotations

import logging
import sys

import structlog
from arq import cron
from arq.connections import RedisSettings

from seeding.config import get_settings

log = structlog.get_logger(__name__)


def force_utf8_output() -> None:
    """Console Windows mac dinh la cp1252, khong ma hoa duoc tieng Viet - va tien trinh
    CHET voi UnicodeEncodeError thay vi in chu hong."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def configure_logging() -> None:
    force_utf8_output()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        )
    )


async def heartbeat(ctx: dict) -> None:
    log.info("worker.alive")


class WorkerSettings:
    functions: list = []
    cron_jobs = [cron(heartbeat, minute=set(range(0, 60, 5)), run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 5
    job_timeout = 300

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        configure_logging()
        log.info("worker.started")
