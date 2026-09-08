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
    # Cac host TINH (JS/CSS/anh, khong cookie) cua nen tang duoc di thang, khong qua proxy
    # cua profile. Do that 08/09/2026: qua proxy dan cu, 53 file JS cua TikTok tren
    # ttwstatic.com bi huy va trang video trong suot 5 phut; cho CDN di thang thi trang
    # ve. HTML, API, video (mang cookie) van di qua proxy - danh tinh khong ro ri. De
    # trong = tat.
    browser_static_bypass: str = ""

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
    # Tha tim / follow / binh luan / dang lai TikTok bang gi: browser | http. Do that
    # 08/09/2026: cong ghi cua web TikTok tra 200 rong cho moi bien the HTTP, con doc thi
    # tot - nen doc/lap lich van HTTP, bam thi mo trang video trong trinh duyet cua
    # profile (trang tu phat video = TikTok thay 30-45 giay xem that).
    tiktok_actions: str = "browser"
    # Instagram qua aiograpi (API rieng cua app, cookie sessionid, khong trinh duyet):
    # dang bai, nuoi va kiem phien. Tat thi tai khoan Instagram chi con mo tay.
    instagram_enabled: bool = True
    # X qua twifork (fork con bao tri cua twikit; cookie auth_token + ct0, proxy cua
    # profile, khong trinh duyet). X xoay query id vai tuan mot lan - khi thu vien lech,
    # worker bao "thu vien X lech" o Cai dat thay vi do loi len tai khoan.
    x_enabled: bool = True
    # Reddit qua API chinh thuc (PRAW): moi tai khoan mot script app, bi mat trong
    # Account.secrets. Khong can trinh duyet.
    reddit_enabled: bool = True
    # Facebook bang trinh duyet that (Camoufox + proxy cua profile): cham, de gay theo
    # A/B test, nhung la duong duy nhat cho trang ca nhan. Khong co nuoi tu dong.
    facebook_enabled: bool = True

    # Chatbot: tu tra loi binh luan duoi bai cua tai khoan va tin nhan. TAT mac dinh -
    # no gui noi dung that ra ngoai; bat khi da xem thu cau tra loi.
    chatbot_enabled: bool = False
    chatbot_comments: bool = True
    chatbot_dms: bool = True
    chatbot_interval_minutes: int = 10
    chatbot_max_per_hour: int = 8
    chatbot_reply_ratio: float = 0.8
    chatbot_lookback_hours: int = 48
    # Viet cau tra loi bang Claude khi co ANTHROPIC_API_KEY; khong co thi dung cau mau.
    chatbot_model: str = "claude-sonnet-5"
    anthropic_api_key: str = ""

    # Tuong tac cheo noi bo: moi bai cua tai khoan xay kenh nhan toi da bao nhieu luot
    # tha tim tu doi booster MOI NGAY. Nghin tai khoan dap vao mot bai trong mot gio la
    # dau vet ro nhat.
    boost_per_post_cap: int = 30

    # Nuoi: binh luan kieu gi - sticker (chi emoji, mac dinh), text (cau tieng Viet), mixed.
    warm_comment_style: str = "sticker"
    # Nuoi: tu khoa tim kiem de chon dich (cach nhau bang dau phay), cong them chu de
    # (interests) cua persona. Trong = chi lay tu For You.
    warm_keywords: str = ""

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
