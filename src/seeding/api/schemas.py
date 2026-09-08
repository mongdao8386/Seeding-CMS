"""Hinh dang du lieu di qua API. Chi nhung gi giao dien moi dung."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from seeding.domain.models import (
    AccountStatus,
    JobStatus,
    MediaKind,
    Platform,
    ProxyKind,
    ProxyStatus,
    TakeoverStatus,
)


class Page[T](BaseModel):
    """Mot trang ket qua. `total` la so ban ghi KHOP DIEU KIEN LOC, khong phai trong trang."""

    items: list[T]
    total: int
    limit: int
    offset: int


class DeleteOut(BaseModel):
    deleted: bool
    detail: str


# ------------------------------------------------------------------ tai khoan


class AccountRow(BaseModel):
    """Mot dong o man hinh Tai khoan. Du de tra loi 'acc nay con song khong' ma
    khong phai bam vao."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    handle: str
    status: AccountStatus
    daily_cap: int
    warmup_started_at: datetime | None
    last_posted_at: datetime | None
    # Tu profile, neu co.
    proxy_label: str | None = None
    session_alive: bool | None = None  # None = chua bao gio dang nhap
    # Tu domain/readiness.py.
    ready: bool = True
    blocked_reason: str | None = None
    # Ngay thu may cua warm-up (1-based); None neu chua bat dau.
    warm_day: int | None = None


class AccountDetail(AccountRow):
    """Them phan 'danh tinh' cho man hinh chi tiet."""

    proxy_host: str | None = None
    proxy_exit_ip: str | None = None
    cookie_count: int = 0
    session_cookie: bool = False
    user_agent: str | None = None
    timezone: str | None = None
    last_login_at: datetime | None = None
    last_health_at: datetime | None = None
    profile_id: uuid.UUID | None = None


class AccountPatch(BaseModel):
    status: AccountStatus | None = None
    daily_cap: int | None = None


class ImportResult(BaseModel):
    created: int
    handles: list[str]
    profiles_with_session: int
    skipped: int
    warnings: list[str]
    problems: list[dict]


# --------------------------------------------------------------------- proxy


class ProxyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    kind: ProxyKind
    scheme: str
    host: str
    port: int
    region: str | None
    status: ProxyStatus
    last_exit_ip: str | None
    last_error: str | None
    username: str | None
    # Gan cho acc nao roi, neu co.
    bound_handle: str | None = None


class ProxyTestOut(BaseModel):
    ok: bool
    exit_ip: str | None
    latency_ms: int | None
    error: str | None


class ProxyImportOut(BaseModel):
    created: int
    labels: list[str]
    tested: int
    passed: int
    duplicate_exit_ips: list[str]
    results: list[dict]
    skipped: list[dict]
    problems: list[dict]


# ------------------------------------------------------------------- profile


class OpenProfileIn(BaseModel):
    url: str | None = None


class OpenProfileOut(BaseModel):
    profile_id: uuid.UUID
    handle: str
    pid: int
    url: str | None
    detail: str


# -------------------------------------------------------------------- he thong


class StatsOut(BaseModel):
    accounts: int
    ready: int
    blocked: int
    dead: int
    needs_human: int
    warming: int
    proxies: int
    proxies_free: int


class SystemOut(BaseModel):
    api: bool
    database: bool
    signer: bool
    signer_detail: str | None
    # None = chua kiem lan nao (chua co tai khoan X, hoac worker chua quet).
    x_library: bool | None = None
    x_library_detail: str | None = None


# ------------------------------------------------------------------- noi dung


class MediaOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    filename: str
    original_name: str
    kind: MediaKind
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    has_thumbnail: bool
    used_by: int


class ContentIn(BaseModel):
    title: str
    body: str = ""
    media_id: uuid.UUID | None = None


class ContentPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    media_id: uuid.UUID | None = None
    clear_media: bool = False


class ContentOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    title: str
    body: str
    media: MediaOut | None
    jobs_total: int
    jobs_succeeded: int
    jobs_scheduled: int
    # So bien the khac nhau ma spintax + tui hashtag co the sinh ra.
    combinations: int


class PreviewIn(BaseModel):
    title: str
    body: str = ""


class PreviewOut(BaseModel):
    samples: list[dict]
    combinations: int


# ----------------------------------------------------------------------- lich


class ScheduleIn(BaseModel):
    content_id: uuid.UUID
    account_ids: list[uuid.UUID]
    # Ngay bat dau (gio dia phuong). None hoac hom nay = tu bay gio.
    start_date: date | None = None
    stagger_seconds: int = 3600
    # Chi Reddit: dang vao subreddit nao. Bat buoc voi tai khoan Reddit.
    subreddit: str | None = None


class JobMove(BaseModel):
    date: date
    hour: int | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    content_id: uuid.UUID | None
    account_id: uuid.UUID
    handle: str
    platform: Platform
    status: JobStatus
    scheduled_at: datetime
    title: str
    body: str
    remote_url: str | None
    last_error: str | None
    attempt_count: int


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    started_at: datetime
    finished_at: datetime | None
    ok: bool
    remote_url: str | None
    error: str | None


# ------------------------------------------------------------------- gio vang


class SlotTime(BaseModel):
    hour: int
    minute: int = 0


class SlotIn(BaseModel):
    platform: Platform
    weekdays: list[int]  # 0 = Thu Hai ... 6 = Chu Nhat
    times: list[SlotTime] = []
    # Dang ngan: chi gio chan. `hours: [6, 10, 22]` == times 06:00, 10:00, 22:00.
    hours: list[int] = []

    def all_times(self) -> list[SlotTime]:
        return [*self.times, *(SlotTime(hour=h) for h in self.hours)]


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform: Platform
    weekday: int
    hour: int
    minute: int


class SlotMeta(BaseModel):
    timezone: str
    weekdays: list[str]


# ----------------------------------------------------------- dong thoi gian


class TimelineItem(BaseModel):
    at: datetime
    # post | like | follow | comment | repost | browse | session | identity | delete | edit
    kind: str
    status: JobStatus | None
    title: str
    detail: str | None
    url: str | None


class KindCount(BaseModel):
    planned: int
    done: int
    failed: int


class ActivitySummary(BaseModel):
    date: date
    likes: KindCount
    follows: KindCount
    comments: KindCount
    accounts_warming: int


# ------------------------------------------------------------------ bai da dang


class PostOut(BaseModel):
    attempt_id: uuid.UUID
    job_id: uuid.UUID
    account_id: uuid.UUID
    handle: str
    platform: Platform
    title: str
    caption: str
    remote_id: str | None
    remote_url: str | None
    posted_at: datetime
    deleted_at: datetime | None
    edited_at: datetime | None
    # 'delete' | 'edit' dang cho worker, hoac None
    pending: str | None
    # None = lam duoc; khong thi ly do (nen tang khong ho tro)
    can_delete: str | None
    can_edit: str | None


class PostEditIn(BaseModel):
    caption: str


# --------------------------------------------------------------- doi danh tinh


class IdentitySuggestions(BaseModel):
    names: list[str]
    usernames: list[str]


class IdentityJobOut(BaseModel):
    id: uuid.UUID
    scheduled_at: datetime
    status: JobStatus
    plan: str


class IdentityOut(BaseModel):
    handle: str
    platform: Platform
    supported: bool
    why_not: str | None
    min_days: int
    last_username_change_at: datetime | None
    next_username_change_at: datetime | None
    pending: IdentityJobOut | None
    suggestions: IdentitySuggestions


class IdentityIn(BaseModel):
    username: str | None = None
    display_name: str | None = None
    avatar_media_id: uuid.UUID | None = None


# ------------------------------------------------------------------- cho nguoi


class TakeoverOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    account_id: uuid.UUID
    profile_id: uuid.UUID | None
    handle: str
    platform: Platform
    reason: str
    status: TakeoverStatus
    has_stuck_job: bool
    alerted: bool


class ResolveIn(BaseModel):
    by: str = "dashboard"
    note: str | None = None


class SettingsOut(BaseModel):
    warmup_quiet_days: int
    warmup_days: int
    default_daily_cap: int
    health_check_interval_hours: int
    health_fail_threshold: int
    schedule_timezone: str
    alert_kind: str
    alert_configured: bool
    tiktok_post_via_http: bool
    tiktok_interact_via_http: bool
    instagram_enabled: bool
    x_enabled: bool
    reddit_enabled: bool
    facebook_enabled: bool
