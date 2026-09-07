"""Cau hinh worker ARQ.

Chay bang:  arq seeding.worker.settings.WorkerSettings
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
    graph_tick,
    health_sweep,
    plan_activity,
    prune_media,
    repeat_tick,
    run_activity_job,
    run_post_job,
    tick,
)


def _force_utf8_output() -> None:
    """Ep stdout/stderr sang UTF-8.

    Console Windows mac dinh la cp1252, ma cp1252 KHONG ma hoa duoc tieng Viet. Hau qua
    khong phai la chu bi hong - la worker CHET giua chung voi UnicodeEncodeError.

    Va no chet o dung cho te nhat: `detect()` doc chu tu trang web that de nhan dien
    checkpoint, roi ghi doan chu do vao log. Mot tai khoan Facebook dat ngon ngu tieng
    Viet gap checkpoint se lam do luon vong xu ly, nen tai khoan khong bao gio vao duoc
    hang doi cho nguoi - dung luc no can nguoi nhat.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                # Stream bi thay the (vd dang chay trong test) thi bo qua - khong dang
                # de viec cau hinh log lam hong tien trinh.
                pass


def _configure_logging() -> None:
    _force_utf8_output()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        )
    )


class WorkerSettings:
    functions = [run_post_job, run_activity_job]
    cron_jobs = [
        cron(tick, second={0, 30}, run_at_startup=True),
        # Quet suc khoe phien moi tieng. Moi lan kiem la mot lan mo trinh duyet
        # that, nen thua hon nhieu so voi tick.
        cron(health_sweep, minute={7}),
        # Job hoat dong nen thua hon job dang bai, moi phut mot lan la du.
        cron(activity_tick, second={15}),
        # Lap lich hoat dong nen cho ngay moi, chay som truoc khung gio thuc.
        cron(plan_activity, hour={6}, minute={0}),
        # Do thi tuong tac cheo lon len mot it moi ngay, luc sang som.
        cron(graph_tick, hour={6}, minute={20}),
        # Chien dich lap lai. Moi gio mot lan: ky duoc tinh tu lan sinh truoc nen
        # chay day hon khong sinh them ban sao, chi lam chung dung gio hon.
        cron(repeat_tick, minute={11}),
        # Don kho bien the media, chay luc it viec nhat.
        cron(prune_media, hour={4}, minute={30}),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

    # Tran concurrency thap la co y. Da co stagger roi thi hiem khi can chay song song
    # nhieu; tu giai doan 03 moi phien trinh duyet ton ~400MB RAM nen day la tai nguyen
    # huu han chu khong phai thu de toi da hoa.
    max_jobs = 5
    job_timeout = 300

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        _configure_logging()
        structlog.get_logger(__name__).info("worker.started")
