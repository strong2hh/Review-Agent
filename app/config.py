from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "dev")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./review_agent.db")
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    review_entry_url: str = os.getenv("REVIEW_ENTRY_URL", "http://localhost:8000/review")
    reminder_hour: int = int(os.getenv("REMINDER_HOUR", "8"))
    reminder_minute: int = int(os.getenv("REMINDER_MINUTE", "0"))
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    recipient_email: str = os.getenv("RECIPIENT_EMAIL", "").strip()
    smtp_from: str = os.getenv("SMTP_FROM", "").strip()
    smtp_user: str = os.getenv("SMTP_USER", "").strip()
    smtp_app_password: str = os.getenv("SMTP_APP_PASSWORD", "").replace(" ", "").strip()
    send_empty_digest: int = 1 if os.getenv("SEND_EMPTY_DIGEST", "0") == "1" else 0


settings = Settings()
