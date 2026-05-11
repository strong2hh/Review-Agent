import os
import time
from types import SimpleNamespace

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_review_agent.db"

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database import SessionLocal, init_db
from app.main import app
from app.models import (
    AppSetting,
    KnowledgePoint,
    ModelTaskFailure,
    ReminderLog,
    ReviewAttempt,
    ReviewGradingJob,
    ReviewSession,
    ReviewSessionItem,
)
from app.services.llm import ModelCallError


class DummySMTP:
    send_count = 0

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        return None

    def login(self, user: str, pwd: str):
        _ = user
        _ = pwd
        return None

    def sendmail(self, from_email: str, to_emails: list[str], payload: str):
        _ = from_email
        _ = to_emails
        _ = payload
        DummySMTP.send_count += 1


client = TestClient(app)


def setup_function():
    DummySMTP.send_count = 0
    init_db()
    db = SessionLocal()
    try:
        db.execute(delete(ReviewGradingJob))
        db.execute(delete(ReviewSessionItem))
        db.execute(delete(ReviewSession))
        db.execute(delete(ReviewAttempt))
        db.execute(delete(ReminderLog))
        db.execute(delete(ModelTaskFailure))
        db.execute(delete(KnowledgePoint))
        db.execute(delete(AppSetting))
        db.commit()
    finally:
        db.close()


def wait_for_grading(job_id: int, expected_status: str = "failed") -> dict:
    last = {}
    for _ in range(50):
        resp = client.get(f"/api/review/grading-jobs/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] == expected_status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"grading job {job_id} did not reach {expected_status}: {last}")


def test_failure_alert_sent_once_within_cooldown(monkeypatch):
    monkeypatch.setattr("app.services.model_service.smtplib.SMTP", DummySMTP)
    monkeypatch.setattr(
        "app.services.model_service.app_settings",
        SimpleNamespace(
            recipient_email="alert@example.com",
            smtp_from="alert@example.com",
            smtp_user="alert@example.com",
            smtp_app_password="dummy-pass",
            deepseek_model="deepseek-chat",
        ),
    )

    def _generation_ok_grading_fails(self, messages, temperature):
        _ = self
        _ = messages
        _ = temperature
        raise ModelCallError("forced_deepseek_failure")

    monkeypatch.setattr("app.services.llm.DeepSeekProvider._chat_completion", _generation_ok_grading_fails)

    create_resp = client.post(
        "/api/knowledge-points",
        json={"title": "缓存一致性", "content": "Cache Invalidation, TTL, Version", "tags": []},
    )
    assert create_resp.status_code == 200
    create_resp_2 = client.post(
        "/api/knowledge-points",
        json={"title": "缓存淘汰", "content": "LRU, LFU, TTL", "tags": []},
    )
    assert create_resp_2.status_code == 200

    start_resp = client.post("/api/review/session/start", json={})
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]

    fail_1 = client.post(
        f"/api/review/session/{session_id}/answer",
        json={"answer": "第一次失败"},
    )
    fail_2 = client.post(
        f"/api/review/session/{session_id}/answer",
        json={"answer": "第二次失败"},
    )
    assert fail_1.status_code == 200
    assert fail_2.status_code == 200
    wait_for_grading(fail_1.json()["grading_job_id"])
    wait_for_grading(fail_2.json()["grading_job_id"])

    db = SessionLocal()
    try:
        failure = db.get(ModelTaskFailure, "grading")
        assert failure is not None
        assert failure.consecutive_failures == 6
        assert failure.last_alert_at is not None
        assert DummySMTP.send_count == 1
    finally:
        db.close()
