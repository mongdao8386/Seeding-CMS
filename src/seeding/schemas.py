from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from seeding.models import (
    AccountStatus,
    ActivityKind,
    BrowserEngine,
    JobStatus,
    MediaKind,
    Platform,
    PostKind,
    ProxyKind,
    ProxyStatus,
    Repeat,
    SessionEventKind,
    TakeoverStatus,
)


class WorkspaceIn(BaseModel):
    name: str


class PersonaIn(BaseModel):
    workspace_id: uuid.UUID
    name: str
    voice: str | None = None
    interests: list[str] = Field(default_factory=list)


class AccountIn(BaseModel):
    persona_id: uuid.UUID
    platform: Platform
    handle: str
    # Duoc ma hoa truoc khi ghi xuong DB, va khong bao gio doc nguoc ra qua API.
    # Reddit: client_id, client_secret, username, password
    # Nen tang automation: password, totp_seed, recovery_email
    secrets: dict = Field(default_factory=dict)
    daily_cap: int = 3
    start_warmup: bool = True


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    handle: str
    status: AccountStatus
    daily_cap: int
    warmup_started_at: datetime | None
    last_posted_at: datetime | None


class ProxyIn(BaseModel):
    label: str
    host: str
    port: int
    kind: ProxyKind = ProxyKind.RESIDENTIAL
    scheme: str = "http"
    username: str | None = None
    password: str | None = None
    region: str | None = None
    sticky: bool = True


class ProxyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    kind: ProxyKind
    scheme: str
    host: str
    port: int
    region: str | None
    sticky: bool
    status: ProxyStatus
    last_exit_ip: str | None
    # Co y khong tra ve mat khau proxy.


class ProfileIn(BaseModel):
    account_id: uuid.UUID
    proxy_id: uuid.UUID | None = None
    engine: BrowserEngine = BrowserEngine.CAMOUFOX
    os_family: str = "windows"
    locale: str = "en-US"


class ProfileOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    handle: str
    platform: Platform
    engine: BrowserEngine
    fingerprint: str  # dang tom tat mot dong, khong tra ve nguyen config
    proxy_label: str | None
    session_alive: bool
    last_login_at: datetime | None
    last_health_at: datetime | None
    consecutive_health_failures: int


class SessionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    kind: SessionEventKind
    detail: str | None


class PreviewIn(BaseModel):
    title_template: str
    body_template: str = ""
    # Xem truoc cho bao nhieu tai khoan. Dung de uoc luong nguy co trung bai.
    account_count: int = Field(default=5, ge=1, le=200)
    # Can de nap cac tui hashtag ma bai co nhac toi.
    workspace_id: uuid.UUID | None = None


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class HashtagSetIn(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    platform: Platform | None = None
    tags: list[str] = Field(default_factory=list)
    note: str | None = None


class HashtagSetPatch(BaseModel):
    platform: Platform | None = None
    tags: list[str] | None = None
    note: str | None = None


class HashtagSetOut(BaseModel):
    id: uuid.UUID
    name: str
    platform: Platform | None
    tags: list[str]
    note: str | None
    # Cho danh de dan thang vao bai soan.
    placeholder: str


class AccountPatch(BaseModel):
    handle: str | None = None
    status: AccountStatus | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=100)
    # Ghi de tung khoa, khong xoa nhung khoa khong gui len.
    secrets: dict | None = None


class ProxyPatch(BaseModel):
    label: str | None = None
    kind: ProxyKind | None = None
    scheme: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    region: str | None = None
    sticky: bool | None = None
    status: ProxyStatus | None = None


class ProxyTestOut(BaseModel):
    ok: bool
    exit_ip: str | None
    latency_ms: int | None
    error: str | None


class ProxyTestAllRow(ProxyTestOut):
    id: uuid.UUID
    label: str


class ProxyTestAllOut(BaseModel):
    tested: int
    passed: int
    results: list[ProxyTestAllRow]
    # Hai proxy khac nhau ma ra cung mot IP la khong con la hai loi ra rieng biet.
    duplicate_exit_ips: list[str]


class ProfilePatch(BaseModel):
    # Doi proxy vi pham bat bien mot acc mot IP, nen phai noi ro y dinh.
    proxy_id: uuid.UUID | None = None
    force_rebind: bool = False
    rebind_reason: str | None = None
    engine: BrowserEngine | None = None
    locale: str | None = None


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    platform: Platform
    post_kind: PostKind
    target: dict
    account_count: int
    total_jobs: int
    succeeded: int
    failed: int
    needs_human: int


class GroupIn2(BaseModel):
    """Them mot nhom vao chien dich da co."""

    name: str
    platform: Platform
    post_kind: PostKind = PostKind.POST
    target: dict = Field(default_factory=dict)
    account_ids: list[uuid.UUID]


class ContentPatch(BaseModel):
    title_template: str | None = None
    body_template: str | None = None
    media_ref: str | None = None
    approved: bool | None = None


class CampaignPatch(BaseModel):
    name: str | None = None
    starts_at: datetime | None = None
    stagger_window_seconds: int | None = Field(default=None, ge=0, le=86_400)
    repeat: Repeat | None = None
    repeat_until: datetime | None = None


class DeleteOut(BaseModel):
    deleted: bool
    detail: str | None = None


class PreviewSample(BaseModel):
    title: str
    body: str
    content_hash: str


class PreviewOut(BaseModel):
    samples: list[PreviewSample]
    # So to hop template co the sinh ra. Day moi la con so quyet dinh.
    combinations: int
    # Rieng phan do cac tui hashtag dong gop - de thay ro tac dung cua chung.
    hashtag_combinations: int
    unique_in_sample: int
    # Xac suat co it nhat hai tai khoan trung bai, theo bai toan sinh nhat.
    collision_risk: float
    warning: str | None
    # Tui duoc nhac toi nhung khong ton tai - go sai ten thi phai bao ngay.
    unknown_pools: list[str]


class CampaignSummary(BaseModel):
    id: uuid.UUID
    name: str
    starts_at: datetime
    stagger_window_seconds: int
    repeat: Repeat
    repeat_until: datetime | None
    # Co cha nghia la ban sao cua mot ky, khong phai chien dich nguoi tao tay.
    repeat_parent_id: uuid.UUID | None
    next_run: datetime | None
    total_jobs: int
    succeeded: int
    failed: int
    needs_human: int


class ContentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    title_template: str
    body_template: str
    media_ref: str | None
    approved: bool


class NamedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class StatsOut(BaseModel):
    accounts: int
    accounts_needing_human: int
    profiles_alive: int
    profiles_total: int
    jobs_scheduled: int
    jobs_succeeded: int
    jobs_failed: int
    activity_scheduled_today: int


class TakeoverOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    handle: str
    platform: Platform
    reason: str
    status: TakeoverStatus
    has_stuck_job: bool


class ResolveIn(BaseModel):
    by: str
    note: str | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ActivityKind
    status: JobStatus
    scheduled_at: datetime
    duration_seconds: int
    detail: str | None


class ContentIn(BaseModel):
    workspace_id: uuid.UUID
    # Ho tro spintax: "Chao {ban|cac ban}, {hom nay|toi nay} the nao?"
    title_template: str
    body_template: str = ""
    media_ref: str | None = None


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_template: str
    body_template: str
    approved: bool


class GroupIn(BaseModel):
    name: str
    platform: Platform
    post_kind: PostKind = PostKind.POST
    # dang bai  - Reddit: {"subreddit": "test"}
    # binh luan - moi nen tang: {"url": "https://..."} tro toi bai can vao
    target: dict = Field(default_factory=dict)
    account_ids: list[uuid.UUID]


class CampaignIn(BaseModel):
    workspace_id: uuid.UUID
    content_item_id: uuid.UUID
    name: str
    starts_at: datetime | None = None
    stagger_window_seconds: int | None = None
    repeat: Repeat = Repeat.NONE
    repeat_until: datetime | None = None
    groups: list[GroupIn]


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts_at: datetime
    stagger_window_seconds: int
    repeat: Repeat
    repeat_until: datetime | None
    repeat_parent_id: uuid.UUID | None
    last_repeated_at: datetime | None


class JobOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    status: JobStatus
    scheduled_at: datetime
    handle: str
    title: str
    content_hash: str
    attempt_count: int
    last_error: str | None
    remote_url: str | None = None


class WindowIn(BaseModel):
    """Khung gio thuc cua mot nen tang. Gio he thong, 0-23."""

    platform: Platform
    active_from_hour: int = Field(ge=0, le=23)
    active_to_hour: int = Field(ge=0, le=23)
    note: str | None = None


class WindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    active_from_hour: int
    active_to_hour: int
    note: str | None
