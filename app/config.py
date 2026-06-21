import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def resolve_app_url() -> str:
    app_url = os.getenv("APP_URL", "").strip().rstrip("/")
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    public_url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")

    if app_url and "trycloudflare.com" not in app_url.lower():
        return app_url
    if render_url:
        return render_url
    if app_url:
        return app_url
    if public_url:
        return public_url
    return "http://localhost:8000"


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Essay Pilot")
    app_url: str = resolve_app_url()
    database_path: Path = (BASE_DIR / os.getenv("DATABASE_PATH", "data/essay_pilot.db")).resolve()
    uploads_dir: Path = (BASE_DIR / os.getenv("UPLOADS_DIR", "uploads")).resolve()
    frontend_dir: Path = (BASE_DIR / "frontend").resolve()
    default_free_limit: int = int(os.getenv("DEFAULT_FREE_LIMIT", "5"))
    referral_bonus: int = int(os.getenv("REFERRAL_BONUS", "2"))
    ocr_provider: str = os.getenv("OCR_PROVIDER", "auto").strip().lower()
    paddle_ocr_lang: str = os.getenv("PADDLE_OCR_LANG", "en").strip()
    paddle_ocr_device: str = os.getenv("PADDLE_OCR_DEVICE", "cpu").strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_ocr_model: str = os.getenv("GEMINI_OCR_MODEL", "gemini-2.5-flash").strip()
    gemini_analysis_model: str = os.getenv("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash").strip()
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    run_bot_with_web: bool = os.getenv("RUN_BOT_WITH_WEB", "false").strip().lower() in {"1", "true", "yes"}
    telegram_bot_mode: str = os.getenv("TELEGRAM_BOT_MODE", "polling").strip().lower()
    telegram_webhook_secret: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    telegram_auth_max_age_seconds: int = int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400"))
    allow_demo_auth: bool = os.getenv("ALLOW_DEMO_AUTH", "false").strip().lower() in {"1", "true", "yes"}
    admin_telegram_ids: str = os.getenv("ADMIN_TELEGRAM_IDS", "").strip()
    payment_card: str = (
        os.getenv("PAYMENT_CARD")
        or os.getenv("CARD_NUMBER")
        or os.getenv("CARD")
        or os.getenv("CLICK_CARD")
        or ""
    ).strip()
    payment_card_holder: str = (
        os.getenv("PAYMENT_CARD_HOLDER")
        or os.getenv("CARD_HOLDER")
        or os.getenv("CARD_OWNER")
        or ""
    ).strip()
    payment_admin_username: str = (
        os.getenv("PAYMENT_ADMIN_USERNAME")
        or os.getenv("ADMIN_USERNAME")
        or os.getenv("PAYMENT_USERNAME")
        or ""
    ).strip()
    admin_secret: str = os.getenv("ADMIN_SECRET", "change-me").strip()

    def admin_telegram_id_set(self) -> set[str]:
        return {item.strip() for item in self.admin_telegram_ids.split(",") if item.strip()}

    def ensure_paths(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
