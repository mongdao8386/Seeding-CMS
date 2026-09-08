"""Cau hinh worker ARQ.  Chay bang:  arq seeding.worker.settings.WorkerSettings

Dang bai (tick moi 30 giay), nuoi tai khoan (activity_tick moi phut, plan_activity moi
sang), don media hang ngay. Kiem suc khoe phien vao o phan 4.
"""

from __future__ import annotations

import logging
import sys

import structlog
from arq import cron
from arq.connections import RedisSettings

from seeding.config import get_settings
from seeding.worker.tasks import (
    activity_tick,
    chatbot_tick,
    health_sweep,
    plan_activity,
    prune_media,
    run_activity_job,
    run_chatbot,
    run_post_job,
    tick,
)

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
    functions = [run_post_job, run_activity_job, run_chatbot]
    cron_jobs = [
        cron(tick, second={0, 30}, run_at_startup=True),
        # Nuoi: quet moi phut; lap lich moi sang som va luc khoi dong (ngay da co thi bo qua).
        cron(activity_tick, second={15}),
        cron(plan_activity, hour={6}, minute={0}, run_at_startup=True),
        cron(prune_media, hour={4}, minute={30}),
        # Kiem phien moi tieng; moi lan chi 10 profile qua han nhat.
        cron(health_sweep, minute={7}),
        # Chatbot: moi N phut (CHATBOT_INTERVAL_MINUTES), tat thi tick tra ve 0 ngay.
        cron(
            chatbot_tick,
            minute=set(range(0, 60, max(1, get_settings().chatbot_interval_minutes))),
            second={40},
        ),
        cron(heartbeat, minute=set(range(0, 60, 5)), run_at_startup=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 5
    job_timeout = 300

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        configure_logging()
        log.info("worker.started")
