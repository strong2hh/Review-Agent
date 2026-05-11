import os
import time

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_review_agent.db"

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete

from app.database import SessionLocal, init_db
from app.main import app
from app.models import (
    AppSetting,
    KnowledgePoint,
    ModelTaskFailure,
    ReviewAttempt,
    ReviewGradingJob,
    ReviewSession,
    ReviewSessionItem,
)
from app.services.llm import ModelCallError


client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_deepseek(monkeypatch):
    def _fake_chat_completion(self, messages, temperature):
        _ = self
        _ = messages
        _ = temperature
        return (
            '{"score":80,"correction":"回答基本正确。","key_points":"核心要点",'
            '"missing_parts":["补充一个实际例子"]}'
        )

    monkeypatch.setattr("app.services.llm.DeepSeekProvider._chat_completion", _fake_chat_completion)


def setup_function():
    init_db()
    db = SessionLocal()
    try:
        db.execute(delete(ReviewGradingJob))
        db.execute(delete(ReviewSessionItem))
        db.execute(delete(ReviewSession))
        db.execute(delete(ReviewAttempt))
        db.execute(delete(KnowledgePoint))
        db.execute(delete(ModelTaskFailure))
        db.execute(delete(AppSetting))
        db.commit()
    finally:
        db.close()


def wait_for_grading(job_id: int, expected_status: str = "completed") -> dict:
    last = {}
    for _ in range(50):
        resp = client.get(f"/api/review/grading-jobs/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] == expected_status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"grading job {job_id} did not reach {expected_status}: {last}")


def test_review_session_end_to_end():
    create_resp = client.post(
        "/api/knowledge-points",
        json={"title": "TCP 三次握手", "content": "SYN, SYN-ACK, ACK", "tags": ["network"]},
    )
    assert create_resp.status_code == 200

    due_resp = client.get("/api/review/due")
    assert due_resp.status_code == 200
    assert len(due_resp.json()) == 1

    start_resp = client.post("/api/review/session/start", json={})
    assert start_resp.status_code == 200
    session_data = start_resp.json()
    assert session_data["total_questions"] == 1

    session_id = session_data["session_id"]
    submit_resp = client.post(
        f"/api/review/session/{session_id}/answer",
        json={"answer": "先发 SYN，服务器返回 SYN-ACK，再回复 ACK"},
    )
    assert submit_resp.status_code == 200
    result = submit_resp.json()

    assert result["completed"] is True
    assert result["grading_status"] == "pending"
    assert result["next_question"] is None

    grading = wait_for_grading(result["grading_job_id"])
    assert 0 <= grading["score_0_100"] <= 100

    status_resp = client.get(f"/api/review/session/{session_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    db = SessionLocal()
    try:
        kp = db.query(KnowledgePoint).first()
        assert kp is not None
        assert kp.next_review_at > datetime.utcnow() - timedelta(seconds=1)
    finally:
        db.close()


def test_admin_page_and_knowledge_points_list_api():
    page_resp = client.get("/admin/knowledge-points")
    assert page_resp.status_code == 200
    assert "后台录入知识点" in page_resp.text

    create_resp = client.post(
        "/api/knowledge-points",
        json={"title": "SQL 索引", "content": "B+ 树可以加速查询", "tags": ["db", "sql"]},
    )
    assert create_resp.status_code == 200

    list_resp = client.get("/api/knowledge-points?limit=10")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) == 1
    assert rows[0]["title"] == "SQL 索引"
    assert rows[0]["tags"] == ["db", "sql"]


def test_submit_answer_returns_next_title_for_following_question():
    client.post(
        "/api/knowledge-points",
        json={"title": "缓存穿透", "content": "查询不存在数据导致穿透到数据库", "tags": []},
    )
    client.post(
        "/api/knowledge-points",
        json={"title": "缓存雪崩", "content": "大量缓存同一时间失效导致数据库压力激增", "tags": []},
    )

    start_resp = client.post("/api/review/session/start", json={})
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]

    submit_resp = client.post(
        f"/api/review/session/{session_id}/answer",
        json={"answer": "先说定义，再说常见治理手段。"},
    )
    assert submit_resp.status_code == 200
    body = submit_resp.json()
    assert body["completed"] is False
    assert isinstance(body["next_title"], str)
    assert len(body["next_title"]) > 0
    assert body["grading_status"] == "pending"
    assert wait_for_grading(body["grading_job_id"])["status"] == "completed"


def test_knowledge_point_update_and_delete():
    create_resp = client.post(
        "/api/knowledge-points",
        json={"title": "Redis", "content": "内存数据库", "tags": ["cache"]},
    )
    assert create_resp.status_code == 200
    kp_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/api/knowledge-points/{kp_id}",
        json={"title": "Redis 基础", "content": "高性能内存键值数据库", "tags": ["cache", "nosql"]},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["title"] == "Redis 基础"
    assert updated["tags"] == ["cache", "nosql"]

    delete_resp = client.delete(f"/api/knowledge-points/{kp_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["ok"] is True

    list_resp = client.get("/api/knowledge-points?limit=10")
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    missing_update_resp = client.put(
        f"/api/knowledge-points/{kp_id}",
        json={"title": "X", "content": "Y", "tags": []},
    )
    assert missing_update_resp.status_code == 404

    missing_delete_resp = client.delete(f"/api/knowledge-points/{kp_id}")
    assert missing_delete_resp.status_code == 404


def test_markdown_import_supports_hash_headings():
    payload = """# HTTP 缓存
ETag 和 Cache-Control 是核心机制。

## TCP 三次握手
SYN -> SYN-ACK -> ACK
"""
    import_resp = client.post(
        "/api/knowledge-points/import",
        json={"format": "markdown", "payload": payload},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["created"] == 2

    list_resp = client.get("/api/knowledge-points?limit=10")
    assert list_resp.status_code == 200
    titles = [row["title"] for row in list_resp.json()]
    assert "HTTP 缓存" in titles
    assert "TCP 三次握手" in titles


def test_model_settings_routes_are_removed():
    assert client.get("/admin/model-settings").status_code == 404
    assert client.get("/api/models/providers").status_code == 404
    assert client.get("/api/settings/models").status_code == 404


def test_grading_failure_does_not_update_mastery_and_records_failures(monkeypatch):
    def _generation_ok_grading_fails(self, messages, temperature):
        _ = self
        _ = messages
        _ = temperature
        raise ModelCallError("forced_deepseek_failure")

    monkeypatch.setattr("app.services.llm.DeepSeekProvider._chat_completion", _generation_ok_grading_fails)

    create_resp = client.post(
        "/api/knowledge-points",
        json={"title": "HTTP 缓存", "content": "ETag Cache-Control Last-Modified", "tags": []},
    )
    assert create_resp.status_code == 200

    start_resp = client.post("/api/review/session/start", json={})
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]

    submit_resp = client.post(
        f"/api/review/session/{session_id}/answer",
        json={"answer": "这是我的回答"},
    )
    assert submit_resp.status_code == 200
    job_id = submit_resp.json()["grading_job_id"]
    failed = wait_for_grading(job_id, expected_status="failed")
    assert "forced_deepseek_failure" in failed["error"]

    db = SessionLocal()
    try:
        kp = db.query(KnowledgePoint).first()
        assert kp is not None
        assert kp.mastery == 0.0
        failure = db.get(ModelTaskFailure, "grading")
        assert failure is not None
        assert failure.consecutive_failures == 3
    finally:
        db.close()
