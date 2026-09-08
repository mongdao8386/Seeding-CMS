"""Cau hinh worker ARQ.  Chay bang:  arq seeding.worker.settings.WorkerSettings

Phan 2: dang bai (tick moi 30 giay, run_post_job, don media hang ngay). Nuoi tai
khoan vao o phan 3, kiem suc khoe phien o phan 4.
"""

from __future__ import annotations

import logging
import sys

import structlog
from arq import cron
from arq.connections import RedisSettings

from seeding.config import get_settings
from seeding.worker.tasks import prune_media, run_post_job, tick

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
    functions = [run_post_job]
    cron_jobs = [
        cron(tick, second={0, 30}, run_at_startup=True),
        cron(prune_media, hour={4}, minute={30}),
        cron(heartbeat, minute=set(range(0, 60, 5)), run_at_startup=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 5
    job_timeout = 300

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        configure_logging()
        log.info("worker.started")
