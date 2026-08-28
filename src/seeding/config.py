from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://seeding:seeding@localhost:5433/seeding"
    redis_url: str = "redis://localhost:6380"

    stagger_window_seconds: int = 3600
    default_daily_cap: int = 3
    warmup_days: int = 14

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
