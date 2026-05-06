import os
from datetime import datetime, timedelta

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_review_agent.db"

from sqlalchemy import delete

from app.database import SessionLocal, init_db
from app.models import AppSetting, KnowledgePoint, ReminderLog
from app.services.reminder_service import DummySender, run_daily_reminder


def setup_function():
    init_db()
    db = SessionLocal()
    try:
        db.execute(delete(ReminderLog))
        db.execute(delete(KnowledgePoint))
        db.execute(delete(AppSetting))
        db.commit()
    finally:
        db.close()


def test_daily_digest_only_once_per_day():
    db = SessionLocal()
    now = datetime(2026, 4, 14, 1, 30, 0)

    try:
        db.add(
            KnowledgePoint(
                title="HTTP 状态码",
                content="200 成功, 404 未找到",
                tags="",
                mastery=0.0,
                stage=0,
                next_review_at=now - timedelta(days=1),
            )
        )
        setting = AppSetting(
            id=1,
            recipient_email="test@example.com",
            smtp_from="test@example.com",
            smtp_user="test@example.com",
            smtp_app_password="app-pass",
            send_empty_digest=0,
        )
        db.add(setting)
        db.commit()

        status_1, due_count_1, _ = run_daily_reminder(
            db=db,
            now=now,
            review_entry_url="http://localhost:8000/review",
            sender=DummySender(),
        )
        status_2, due_count_2, _ = run_daily_reminder(
            db=db,
            now=now,
            review_entry_url="http://localhost:8000/review",
            sender=DummySender(),
        )

        assert status_1 == "sent"
        assert due_count_1 == 1
        assert status_2 == "already_sent"
        assert due_count_2 == 0
    finally:
        db.close()
