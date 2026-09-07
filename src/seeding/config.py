from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://seeding:seeding@localhost:5433/seeding"
    redis_url: str = "redis://localhost:6380"

    stagger_window_seconds: int = 3600
    default_daily_cap: int = 3
    # Tai khoan moi len tu 1 bai/ngay toi daily_cap trong bay nhieu ngay. Nguoi van hanh
    # nuoi acc 2-3 ngay (tuong tac cheo, follow, binh luan) roi moi dang - 3 la du.
    warmup_days: int = 3
    # Bao nhieu ngay dau cua warm-up KHONG dang bai nao - chi tuong tac (cuon feed,
    # follow, binh luan). Quy tac cua nguoi van hanh: "nuoi 2-3 ngay roi moi dang".
    # Ramp o tren tinh tu ngay 0 nhung tran chi mo sau khi het quiet_days.
    warmup_quiet_days: int = 2
    # Mui gio cua bang khung gio vang dang bai (post_slots). Gio nguoi van hanh nhap la
    # gio dia phuong cua KHAN GIA, khong phai UTC cua may chu.
    schedule_timezone: str = "Asia/Ho_Chi_Minh"

    reddit_user_agent: str = "seeding-cms/0.1"

    # Khoa Fernet cho ket bi mat. Sinh bang: python scripts/gen_vault_key.py
    vault_key: str = ""

    # Token bao ve API va dashboard. Sinh bang: python scripts/gen_api_token.py
    # De trong thi API tu choi moi request - co y fail-closed.
    api_token: str = ""

    # Kho media: file goc o media_root/sources, ban bien the o media_root/variants.
    media_root: str = "./media"
    # Muc do bien doi media: subtle | moderate | aggressive.
    # Xem core/media.py de biet danh doi that su giua chung.
    media_strength: str = "moderate"
    # Giu ban bien the bao nhieu ngay roi don. Ban goc khong bao gio bi dong toi.
    media_variant_keep_days: int = 14

    # Noi cat file goc: local | supabase. Ban bien the LUON o may, du chon gi.
    media_backend: str = "local"
    supabase_url: str = ""
    # Service key, khong phai anon key. No khong bao gio roi khoi may chu API.
    supabase_service_key: str = ""
    supabase_bucket: str = "seeding-media"

    # Kiem tra phien con song moi bao nhieu gio.
    health_check_interval_hours: int = 12
    # Sau bao nhieu lan health check that bai lien tiep thi danh dau can nguoi xu ly.
    health_fail_threshold: int = 2
    # Mo trinh duyet an khi kiem tra suc khoe; dang nhap tay thi luon hien.
    headless_health_check: bool = True
    # Mo trinh duyet an khi CHAY JOB (dang bai, hoat dong nen, tuong tac cheo).
    # De True khi chay that: mot chuc phien hien cua so thi may khong dung duoc nua.
    # Dat False khi can nhin mot job chay bang mat - lan dau chay tren tai khoan that,
    # hoac khi selector khong khop va can biet trang dang hien cai gi.
    headless_jobs: bool = True

    # Dang bai TikTok bang HTTP (7 buoc, khong mo trinh duyet) thay vi TikTok Studio
    # trong Camoufox. Do that 07/09/2026: HTTP ~4 giay qua proxy dan cu, trang Studio
    # 90-300 giay hoac timeout. Binh luan van di bang trinh duyet.
    tiktok_post_via_http: bool = True
    # Signer ky X-Bogus/X-Gnarly cho buoc publish - tools/tiktok-signer, Start.cmd tu bat.
    signer_url: str = "http://127.0.0.1:8080"
    # Tha tim / theo doi / binh luan tren TikTok bang HTTP (core/tiktok_interact) thay vi
    # trinh duyet, va lap lich nuoi huong ra ngoai tren For You (core/outreach).
    tiktok_interact_via_http: bool = True

    # Bao ra ngoai khi co tai khoan can nguoi. De trong = tat.
    # discord | slack | telegram | generic
    alert_kind: str = "generic"
    alert_webhook_url: str = ""
    # Chi Telegram can: URL la .../bot<TOKEN>/sendMessage, con chat_id di trong payload.
    alert_telegram_chat_id: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
