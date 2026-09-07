"""Mo hinh du lieu loi.

Nguyen tac dat ra tu ban thiet ke:
  - Persona la "nhan vat", Account la tai khoan cua nhan vat do tren mot nen tang.
  - Moi Account nhan mot Variant RIENG. Nhieu acc dang cung mot chuoi text
    giong het nhau la tin hieu spam ro nhat.
  - PostJob co idempotency_key duy nhat -> retry khong bao gio hoa thanh dang trung.
  - Attempt ghi tung lan thu; metric gan vao Attempt chu khong gan vao Campaign.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Platform(enum.StrEnum):
    REDDIT = "reddit"
    THREADS = "threads"
    X = "x"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"


class AccountStatus(enum.StrEnum):
    NEW = "new"
    WARMING = "warming"
    ACTIVE = "active"
    NEEDS_HUMAN = "needs_human"  # checkpoint / captcha / xac minh
    SUSPENDED = "suspended"
    DEAD = "dead"


class BrowserEngine(enum.StrEnum):
    CAMOUFOX = "camoufox"  # Firefox, sua fingerprint o tang C++ - mac dinh
    PATCHRIGHT = "patchright"  # Chromium, du phong khi trang chi chay tot tren Chrome


class ProxyKind(enum.StrEnum):
    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    DATACENTER = "datacenter"  # gan nhu luon bi phat hien - chi dung de test


class ProxyStatus(enum.StrEnum):
    UNTESTED = "untested"
    OK = "ok"
    FAILING = "failing"
    RETIRED = "retired"


class SessionEventKind(enum.StrEnum):
    CREATED = "created"
    LOGIN = "login"  # dang nhap tay lan dau
    HEALTH_OK = "health_ok"
    HEALTH_FAIL = "health_fail"
    CHECKPOINT = "checkpoint"  # gap captcha / xac minh
    TAKEOVER = "takeover"  # nguoi van hanh tiep quan
    COOKIES_SAVED = "cookies_saved"


class PostKind(enum.StrEnum):
    """Dang bai moi, hay binh luan vao bai co san.

    Seeding ngoai doi phan lon la BINH LUAN chu khong phai dang len tuong minh: binh
    luan muon duoc luong nguoi xem cua bai goc, con bai tren tuong mot acc moi thi gan
    nhu khong ai thay.
    """

    POST = "post"
    COMMENT = "comment"


class Repeat(enum.StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"


class MediaKind(enum.StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class ActivityKind(enum.StrEnum):
    """Viec khong dang gi ca. Phai nhieu gap 5-10 lan job dang bai.

    Mot tai khoan chi dang bai roi bien mat la mau hinh bot ro nhat.
    """

    BROWSE_FEED = "browse_feed"
    READ_POST = "read_post"
    REACT = "react"
    WATCH_VIDEO = "watch_video"

    # Ba loai duoi day NHAM VAO MOT DICH CU THE, khac han bon loai tren. Chung tao ra
    # canh trong do thi tai khoan - va do thi moi la thu lam ca cum chet cung mot lan,
    # chu khong phai fingerprint. Xem core/graph.py.
    FOLLOW = "follow"
    ENGAGE = "engage"  # tha cam xuc vao mot bai cu the
    REPOST = "repost"


# Ba loai tren nham vao mot dich; bon loai con lai thi khong.
TARGETED_KINDS = frozenset({ActivityKind.FOLLOW, ActivityKind.ENGAGE, ActivityKind.REPOST})


class RelationStatus(enum.StrEnum):
    PLANNED = "planned"
    DONE = "done"
    FAILED = "failed"


class DeviceOS(enum.StrEnum):
    ANDROID = "android"
    # iOS co trong enum vi mo hinh du lieu chiu duoc no, KHONG phai vi chay duoc tren
    # may nay. Tu dong hoa app iOS bat buoc phai co macOS + Xcode de build va ky
    # WebDriverAgent; iOS Simulator thi khong cai duoc app tu App Store. Do la buc
    # tuong nen tang, khong phai chuyen bo them cong suc.
    IOS = "ios"


class DeviceStatus(enum.StrEnum):
    OFFLINE = "offline"  # khong thay qua adb
    READY = "ready"
    BUSY = "busy"
    UNAUTHORIZED = "unauthorized"  # da cam nhung chua bam "cho phep go loi USB"
    ERROR = "error"


class TakeoverStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"  # tai khoan bo luon


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"  # giai doan 03 moi dung, khai bao san
    SKIPPED = "skipped"  # bi rate governor chan


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Workspace(UUIDPk, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120))

    personas: Mapped[list[Persona]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )


class Persona(UUIDPk, Base):
    """Nhan vat: ten, giong van, chu de quan tam. Mot persona co nhieu Account."""

    __tablename__ = "personas"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    voice: Mapped[str | None] = mapped_column(Text, default=None)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)

    workspace: Mapped[Workspace] = relationship(back_populates="personas")
    accounts: Mapped[list[Account]] = relationship(
        back_populates="persona", cascade="all, delete-orphan", passive_deletes=True
    )


class Account(UUIDPk, Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "handle", name="uq_account_platform_handle"),)

    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False))
    handle: Mapped[str] = mapped_column(String(190))
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False), default=AccountStatus.NEW
    )

    # JSON da ma hoa. Reddit: client_id, client_secret, username, password.
    # Nen tang automation: password, totp_seed, recovery_email.
    # Doc/ghi qua account.get_secrets() / set_secrets(), dung cham thang vao cot.
    secrets_enc: Mapped[str | None] = mapped_column(Text, default=None)

    daily_cap: Mapped[int] = mapped_column(Integer, default=3)
    warmup_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    persona: Mapped[Persona] = relationship(back_populates="accounts")
    profile: Mapped[Profile | None] = relationship(
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def get_secrets(self) -> dict:
        from seeding.core import vault

        return vault.decrypt_json(self.secrets_enc)

    def set_secrets(self, data: dict) -> None:
        from seeding.core import vault

        self.secrets_enc = vault.encrypt_json(data)


class Proxy(UUIDPk, Base):
    """Mot loi ra Internet. Gan cung voi mot Profile va khong xoay."""

    __tablename__ = "proxies"

    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ProxyKind] = mapped_column(
        Enum(ProxyKind, native_enum=False), default=ProxyKind.RESIDENTIAL
    )
    scheme: Mapped[str] = mapped_column(String(10), default="http")  # http | socks5
    host: Mapped[str] = mapped_column(String(190))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(190), default=None)
    password_enc: Mapped[str | None] = mapped_column(Text, default=None)
    region: Mapped[str | None] = mapped_column(String(80), default=None)
    sticky: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus, native_enum=False), default=ProxyStatus.UNTESTED
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_exit_ip: Mapped[str | None] = mapped_column(String(64), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    def set_password(self, value: str | None) -> None:
        from seeding.core import vault

        self.password_enc = vault.encrypt(value) if value else None

    def get_password(self) -> str | None:
        from seeding.core import vault

        return vault.decrypt(self.password_enc) if self.password_enc else None

    def as_playwright_proxy(self) -> dict:
        # `default=` cua SQLAlchemy chi dien luc INSERT, nen object vua tao ra ma
        # chua flush thi scheme van la None. Doc phong thu o day de khong bao gio
        # dung ra chuoi "None://host:port".
        scheme = (self.scheme or "http").lower()
        proxy = {"server": f"{scheme}://{self.host}:{self.port}"}
        if self.username:
            proxy["username"] = self.username
            proxy["password"] = self.get_password() or ""
        return proxy


class Profile(UUIDPk, Base):
    """Danh tinh trinh duyet cua mot tai khoan: fingerprint + cookie jar + proxy.

    Bat bien cua ca he thong: mot account <-> mot profile <-> mot proxy, VINH VIEN.
    Xoay IP giua cac phien cua cung mot tai khoan gay hai nhieu hon la dung mot IP
    dan cu co dinh. Rang buoc unique o duoi la de ep dieu do.
    """

    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("account_id", name="uq_profile_account"),)

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proxies.id"), default=None)
    engine: Mapped[BrowserEngine] = mapped_column(
        Enum(BrowserEngine, native_enum=False), default=BrowserEngine.CAMOUFOX
    )

    # Sinh mot lan luc tao profile roi KHONG BAO GIO sinh lai. Fingerprint doi giua
    # cac phien cua cung mot tai khoan la tin hieu bat thuong ro rang.
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict)
    os_family: Mapped[str] = mapped_column(String(20), default="windows")
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    timezone: Mapped[str | None] = mapped_column(String(60), default=None)

    # storage_state cua Playwright, da ma hoa. Day chinh la phien dang nhap.
    cookies_enc: Mapped[str | None] = mapped_column(Text, default=None)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    session_alive: Mapped[bool] = mapped_column(Boolean, default=False)
    consecutive_health_failures: Mapped[int] = mapped_column(Integer, default=0)

    account: Mapped[Account] = relationship(back_populates="profile")
    proxy: Mapped[Proxy | None] = relationship(lazy="joined")

    def set_cookies(self, storage_state: dict) -> None:
        from seeding.core import vault

        self.cookies_enc = vault.encrypt_json(storage_state)

    def get_cookies(self) -> dict | None:
        from seeding.core import vault

        return vault.decrypt_json(self.cookies_enc) if self.cookies_enc else None


class SessionEvent(UUIDPk, Base):
    """Nhat ky vong doi phien.

    Muc tieu cua giai doan 02 la chung minh phien song duoc nhieu ngay lien tuc;
    bang nay la bang chung cho dieu do, va la thu dau tien can nhin khi mot nhom
    tai khoan chet cung luc.
    """

    __tablename__ = "session_events"
    __table_args__ = (Index("ix_session_event_profile", "profile_id", "created_at"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    kind: Mapped[SessionEventKind] = mapped_column(Enum(SessionEventKind, native_enum=False))
    detail: Mapped[str | None] = mapped_column(Text, default=None)


class ActivityJob(UUIDPk, Base):
    """Mot lan "song" tren nen tang ma khong dang gi.

    Tach khoi PostJob co chu y: activity khong co Variant, khong thuoc Campaign, va
    khong bao gio duoc tinh vao tran dang bai cua rate governor.
    """

    __tablename__ = "activity_jobs"
    __table_args__ = (Index("ix_activity_due", "status", "scheduled_at"),)

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    kind: Mapped[ActivityKind] = mapped_column(Enum(ActivityKind, native_enum=False))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.SCHEDULED
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Bao lau thi du. Worker dung con so nay lam ngan sach thoi gian.
    duration_seconds: Mapped[int] = mapped_column(Integer, default=90)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    # Dich cua cac loai FOLLOW / ENGAGE / REPOST. Rong voi bon loai khong nham dich.
    # SET NULL khi tai khoan dich bi xoa: job da chay xong van la lich su co that, xoa
    # no di thi khong con doi chieu duoc vi sao mot tai khoan co canh nay.
    target_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), default=None
    )
    target_url: Mapped[str | None] = mapped_column(Text, default=None)

    account: Mapped[Account] = relationship(lazy="joined", foreign_keys=[account_id])


class Device(UUIDPk, Base):
    """Mot dien thoai that (hoac may ao) chay app that.

    Song song voi Profile chu khong thay the: Profile la mot danh tinh TRINH DUYET,
    Device la mot danh tinh THIET BI. Mot tai khoan di theo mot trong hai duong, khong
    phai ca hai - chay cung mot acc luc tren web luc tren app tu hai IP khac nhau la
    dau vet ro hon bat ky thu gi ma ca he thong nay dang tranh.

    Bat bien giu nguyen nhu ben Profile: mot acc <-> mot thiet bi <-> mot proxy, va
    khong xoay. Thiet bi doi chu so huu giua chung la thu nen tang nhin thay ngay.
    """

    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("serial", name="uq_device_serial"),
        UniqueConstraint("account_id", name="uq_device_account"),
    )

    # Serial cua adb (Android) hoac UDID (iOS). Day la thu duy nhat nhan dang duoc mot
    # may khi cam nhieu may cung luc.
    serial: Mapped[str] = mapped_column(String(190))
    label: Mapped[str] = mapped_column(String(120))
    os: Mapped[DeviceOS] = mapped_column(
        Enum(DeviceOS, native_enum=False), default=DeviceOS.ANDROID
    )
    model: Mapped[str | None] = mapped_column(String(190), default=None)
    os_version: Mapped[str | None] = mapped_column(String(40), default=None)

    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False), default=DeviceStatus.OFFLINE
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    # Rong = da cam nhung chua gan cho tai khoan nao.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), default=None
    )
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proxies.id"), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    account: Mapped[Account | None] = relationship(lazy="joined")
    proxy: Mapped[Proxy | None] = relationship(lazy="joined")


class Relationship(UUIDPk, Base):
    """Mot canh trong do thi: A theo doi B.

    Ton tai de KIEM SOAT do thi, khong phai de ghi chep cho vui. Nen tang bat trai
    tai khoan bang do thi hanh vi de hon nhieu so voi bang fingerprint: mot cum trong
    do ai cung theo doi tat ca moi nguoi va khong theo doi ai ben ngoai la hinh dang
    khong ton tai trong doi that, va no lo ra chi bang mot cau truy van.

    Co bang nay thi `core/graph.py` moi tra loi duoc "do thi hien tai day den dau",
    "co bao nhieu cap theo doi lan nhau" - nhung con so quyet dinh ca cum song hay chet.
    """

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint("follower_id", "target_id", name="uq_relationship_edge"),
        Index("ix_relationship_target", "target_id", "status"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    status: Mapped[RelationStatus] = mapped_column(
        Enum(RelationStatus, native_enum=False), default=RelationStatus.PLANNED
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    follower: Mapped[Account] = relationship(foreign_keys=[follower_id], lazy="joined")
    target: Mapped[Account] = relationship(foreign_keys=[target_id], lazy="joined")


class TakeoverRequest(UUIDPk, Base):
    """Mot tai khoan dang cho nguoi vao giai.

    Ton tai rieng thay vi chi dua vao Account.status vi can biet CHUYEN GI da xay ra,
    ai da xu ly, va bao lau - do la so lieu de biet co che nay co chiu noi quy mo khong.
    """

    __tablename__ = "takeover_requests"
    __table_args__ = (Index("ix_takeover_open", "status", "created_at"),)

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[TakeoverStatus] = mapped_column(
        Enum(TakeoverStatus, native_enum=False), default=TakeoverStatus.OPEN
    )
    reason: Mapped[str] = mapped_column(Text)
    # Job nao da cham vao no. Giai xong thi thu lai dung job do.
    post_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_jobs.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_by: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # Da bao ra ngoai chua. Mot tai khoan hong mot lan thi bao mot lan, khong bao lai
    # moi vong quet - bao dong lap lai la cach nhanh nhat de nguoi ta tat thong bao.
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    account: Mapped[Account] = relationship(lazy="joined")


class MediaAsset(UUIDPk, Base):
    """Mot file goc trong kho.

    Ban ghi rieng thay vi chi quet thu muc: can biet ten goc nguoi dung dat, kich
    thuoc, do dai, va anh xem truoc - de man hinh soan bai chon duoc file ma khong
    phai mo tung cai ra xem.
    """

    __tablename__ = "media_assets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    # Ten file trong media/sources/. Chinh la thu dien vao ContentItem.media_ref.
    filename: Mapped[str] = mapped_column(String(300))
    original_name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind, native_enum=False))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    # Anh xem truoc, luon la .jpg, nam trong media/thumbs/.
    thumbnail: Mapped[str | None] = mapped_column(String(300), default=None)


class HashtagSet(UUIDPk, Base):
    """Mot tui hashtag de rut ngau nhien.

    KHONG phai mot khoi hashtag co dinh dan vao moi bai: dung y het nhau tren nhieu
    tai khoan thi cung la mot dau vet trung lap nhu van ban giong nhau. Trong bai soan,
    ban dat mot cho danh [[tags:ten-tui:3]] va planner rut 3 the khac nhau cho tung
    tai khoan, bang dung RNG co seed nhu spintax.
    """

    __tablename__ = "hashtag_sets"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_hashtag_set_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    # None = dung cho moi nen tang.
    platform: Mapped[Platform | None] = mapped_column(
        Enum(Platform, native_enum=False), default=None
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class PlatformWindow(UUIDPk, Base):
    """Khung gio thuc cua tung nen tang.

    Truoc day dung chung 7h-23h cho tat ca. Nhung gio cao diem cua TikTok va Facebook
    khac han nhau, va mot tai khoan hoat dong lech han voi nhip cua nen tang do la mot
    dau vet - it ro hon fingerprint, nhung van la mot dau vet.

    Khong co ban ghi cho nen tang nao thi dung mac dinh trong core/activity.py.
    """

    __tablename__ = "platform_windows"
    __table_args__ = (UniqueConstraint("platform", "weekday", name="uq_platform_window_day"),)

    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False))
    # Thu trong tuan, theo cach danh so cua Python: 0 = thu Hai ... 6 = Chu nhat.
    #
    # Moi ngay mot ban ghi rieng, thay vi mot ban ghi cho ca tuan. Nguoi that khong
    # thuc day va di ngu dung mot khung gio bay ngay lien - dung mot khung cho ca tuan
    # chinh la mot mau hinh, chi la mau hinh kin dao hon gio 3 gio sang.
    #
    # Khong co ban ghi cho (nen tang, thu) nao thi ngay do dung mac dinh trong
    # core/activity.py. Khong co tang trung gian "mac dinh cua nen tang": hai tang
    # fallback la du, ba tang thi khong ai doan duoc gio thuc te la bao nhieu.
    weekday: Mapped[int] = mapped_column(Integer)
    # Gio trong ngay, theo gio he thong. 0-23.
    active_from_hour: Mapped[int] = mapped_column(Integer, default=7)
    active_to_hour: Mapped[int] = mapped_column(Integer, default=23)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class ContentItem(UUIDPk, Base):
    """Y tuong goc. Sinh ra N Variant, moi Variant di toi mot Account."""

    __tablename__ = "content_items"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    title_template: Mapped[str] = mapped_column(Text)
    body_template: Mapped[str] = mapped_column(Text, default="")
    media_ref: Mapped[str | None] = mapped_column(String(500), default=None)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    variants: Mapped[list[Variant]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan", passive_deletes=True
    )


class Variant(UUIDPk, Base):
    __tablename__ = "variants"

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    # File goc, dung chung cho moi bien the.
    media_ref: Mapped[str | None] = mapped_column(String(500), default=None)
    # Ban media rieng cua tai khoan nay, render sat luc dang. Muoi acc upload cung mot
    # file giong het tung byte la bi bat ngay.
    media_variant_ref: Mapped[str | None] = mapped_column(String(500), default=None)
    # pHash cua ban da render - de tu kiem tra cac ban that su khac nhau den dau.
    media_phash: Mapped[str | None] = mapped_column(String(64), default=None)
    # Hash cua noi dung da render -> de tu kiem tra cac ban that su khac nhau.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    content_item: Mapped[ContentItem] = relationship(back_populates="variants")


class Campaign(UUIDPk, Base):
    __tablename__ = "campaigns"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"))
    name: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Cua so rai job. 0 = dang cung luc that (khong khuyen khich).
    stagger_window_seconds: Mapped[int] = mapped_column(Integer, default=3600)

    # Lap lai: sinh mot chien dich con moi ky, cung noi dung va cung nhom tai khoan.
    # Bien the van khac nhau moi lan vi seed co ca id chien dich con.
    repeat: Mapped[Repeat] = mapped_column(Enum(Repeat, native_enum=False), default=Repeat.NONE)
    repeat_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Ban sao tro ve ban goc, de biet ca chuoi thuoc ve dau.
    repeat_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), default=None
    )
    last_repeated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # passive_deletes de ORM khong tu set campaign_id = NULL khi xoa chien dich -
    # cot do NOT NULL, va database da co ON DELETE CASCADE lam dung viec roi.
    groups: Mapped[list[CampaignGroup]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True
    )


class CampaignGroup(UUIDPk, Base):
    """Don vi "dang cung luc". Nhom theo nen tang, theo cum persona, hoac theo vung."""

    __tablename__ = "campaign_groups"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False))
    post_kind: Mapped[PostKind] = mapped_column(
        Enum(PostKind, native_enum=False), default=PostKind.POST
    )
    # Tham so rieng cua nen tang.
    #   dang bai  - Reddit: {"subreddit": "test"}
    #   binh luan - moi nen tang: {"url": "https://..."} tro toi bai can vao
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    account_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    campaign: Mapped[Campaign] = relationship(back_populates="groups")


class PostJob(UUIDPk, Base):
    __tablename__ = "post_jobs"
    __table_args__ = (
        # Day la thu ngan retry bien thanh dang trung.
        UniqueConstraint("idempotency_key", name="uq_post_job_idem"),
        Index("ix_post_job_due", "status", "scheduled_at"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_groups.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variants.id"))

    idempotency_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.PENDING
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    attempts: Mapped[list[Attempt]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    variant: Mapped[Variant] = relationship(lazy="joined")
    account: Mapped[Account] = relationship(lazy="joined")


class Attempt(UUIDPk, Base):
    """Mot lan thu. Metric gan vao day chu khong gan vao Campaign."""

    __tablename__ = "attempts"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("post_jobs.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_id: Mapped[str | None] = mapped_column(String(200), default=None)
    remote_url: Mapped[str | None] = mapped_column(String(500), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[PostJob] = relationship(back_populates="attempts")
