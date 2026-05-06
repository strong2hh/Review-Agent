from __future__ import annotations

from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import KnowledgePoint
from app.schemas import (
    KnowledgePointCreate,
    KnowledgePointImportRequest,
    KnowledgePointOut,
    ModelChannelsOut,
    ModelChannelsUpdate,
    ModelConfigUpdate,
    ProviderSpecOut,
    ReminderRunResponse,
    ReviewDueItem,
    SessionStatusResponse,
    StartSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.services.llm import list_provider_specs
from app.services.model_service import ModelExecutionError
from app.services.reminder_service import DummySender, GmailSmtpSender, run_daily_reminder
from app.services.review_service import get_due_knowledge_points, get_session_status, start_review_session, submit_answer
from app.services.settings_service import get_or_create_settings

app = FastAPI(title="Review Agent", version="1.1.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

scheduler: Optional[BackgroundScheduler] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _now() -> datetime:
    return datetime.utcnow()


def _run_daily_job() -> None:
    db = SessionLocal()
    try:
        sender = GmailSmtpSender()
        run_daily_reminder(
            db=db,
            now=_now(),
            review_entry_url=settings.review_entry_url,
            sender=sender,
        )
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    global scheduler
    init_db()

    db = SessionLocal()
    try:
        get_or_create_settings(db)
    finally:
        db.close()

    if settings.app_env == "test":
        return

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger(hour=9, minute=30, timezone=settings.timezone),
        id="daily_0930_digest",
        replace_existing=True,
    )
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request):
    return templates.TemplateResponse("review.html", {"request": request})


@app.get("/admin/knowledge-points", response_class=HTMLResponse)
def knowledge_point_admin_page(request: Request):
    return templates.TemplateResponse("knowledge_points_admin.html", {"request": request})


@app.post("/api/knowledge-points", response_model=KnowledgePointOut)
def create_knowledge_point(payload: KnowledgePointCreate, db: Session = Depends(get_db)):
    clean_tags = [tag.strip() for tag in payload.tags if tag.strip()]
    now = _now()
    kp = KnowledgePoint(
        title=payload.title,
        content=payload.content,
        tags=",".join(clean_tags),
        mastery=0.0,
        stage=0,
        next_review_at=now,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return _kp_out(kp)


@app.get("/api/knowledge-points", response_model=list[KnowledgePointOut])
def list_knowledge_points(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.query(KnowledgePoint).order_by(KnowledgePoint.id.desc()).limit(limit).all()
    return [_kp_out(kp) for kp in rows]


@app.put("/api/knowledge-points/{knowledge_point_id}", response_model=KnowledgePointOut)
def update_knowledge_point(knowledge_point_id: int, payload: KnowledgePointCreate, db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, knowledge_point_id)
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    clean_tags = [tag.strip() for tag in payload.tags if tag.strip()]
    kp.title = payload.title
    kp.content = payload.content
    kp.tags = ",".join(clean_tags)
    db.commit()
    db.refresh(kp)
    return _kp_out(kp)


@app.delete("/api/knowledge-points/{knowledge_point_id}")
def delete_knowledge_point(knowledge_point_id: int, db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, knowledge_point_id)
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    try:
        db.delete(kp)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该知识点已有复习记录，暂不支持删除") from exc

    return {"ok": True}


@app.post("/api/knowledge-points/import")
def import_knowledge_points(payload: KnowledgePointImportRequest, db: Session = Depends(get_db)):
    records = _parse_import_payload(payload.format, payload.payload)
    now = _now()
    created = 0

    for title, content in records:
        if not title.strip() or not content.strip():
            continue
        kp = KnowledgePoint(
            title=title.strip(),
            content=content.strip(),
            tags="",
            mastery=0.0,
            stage=0,
            next_review_at=now,
        )
        db.add(kp)
        created += 1

    db.commit()
    return {"created": created}


@app.get("/api/review/due", response_model=list[ReviewDueItem])
def get_due(db: Session = Depends(get_db)):
    due = get_due_knowledge_points(db, _now())
    return [
        ReviewDueItem(
            knowledge_point_id=kp.id,
            title=kp.title,
            mastery=kp.mastery,
            stage=kp.stage,
            next_review_at=kp.next_review_at,
        )
        for kp in due
    ]


@app.post("/api/review/session/start", response_model=StartSessionResponse)
def start_session(db: Session = Depends(get_db)):
    try:
        session, current = start_review_session(db, now=_now())
    except ModelExecutionError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    total = len(session.items)
    if not current:
        return StartSessionResponse(
            session_id=session.id,
            total_questions=total,
            current_index=0,
            question_id=None,
            knowledge_point_id=None,
            title=None,
            question=None,
        )

    return StartSessionResponse(
        session_id=session.id,
        total_questions=total,
        current_index=1,
        question_id=current.id,
        knowledge_point_id=current.knowledge_point_id,
        title=current.knowledge_point.title,
        question=current.question,
    )


@app.post("/api/review/session/{session_id}/answer", response_model=SubmitAnswerResponse)
def submit_session_answer(session_id: int, payload: SubmitAnswerRequest, db: Session = Depends(get_db)):
    try:
        result = submit_answer(db=db, session_id=session_id, answer=payload.answer, now=_now())
        return SubmitAnswerResponse(**result)
    except ModelExecutionError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review/session/{session_id}", response_model=SessionStatusResponse)
def review_session_status(session_id: int, db: Session = Depends(get_db)):
    try:
        status = get_session_status(db, session_id)
        return SessionStatusResponse(**status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/reminder/run-daily", response_model=ReminderRunResponse)
def run_daily(db: Session = Depends(get_db)):
    sender = GmailSmtpSender()
    status, due_count, message = run_daily_reminder(
        db=db,
        now=_now(),
        review_entry_url=settings.review_entry_url,
        sender=sender,
    )
    return ReminderRunResponse(status=status, due_count=due_count, message=message)


@app.get("/api/models/providers", response_model=list[ProviderSpecOut])
def model_providers():
    return [ProviderSpecOut(**x) for x in list_provider_specs()]


@app.post("/api/settings/models", response_model=ModelChannelsOut)
def update_model_channels(payload: ModelChannelsUpdate, db: Session = Depends(get_db)):
    setting = get_or_create_settings(db)
    setting.question_provider = payload.question_provider.strip().lower()
    setting.question_model = payload.question_model.strip()
    setting.grading_provider = payload.grading_provider.strip().lower()
    setting.grading_model = payload.grading_model.strip()

    # keep legacy fields synced for backward compatibility
    setting.model_provider = setting.grading_provider
    setting.model_name = setting.grading_model

    db.commit()
    return ModelChannelsOut(
        question_provider=setting.question_provider,
        question_model=setting.question_model,
        grading_provider=setting.grading_provider,
        grading_model=setting.grading_model,
    )


@app.post("/api/settings/model")
def update_model_config(payload: ModelConfigUpdate, db: Session = Depends(get_db)):
    # deprecated compatibility route: now maps to grading_* channel
    setting = get_or_create_settings(db)
    setting.model_provider = payload.model_provider.strip().lower()
    setting.model_name = payload.model_name.strip()
    setting.grading_provider = setting.model_provider
    setting.grading_model = setting.model_name
    db.commit()
    return {
        "ok": True,
        "deprecated": True,
        "model_provider": setting.model_provider,
        "model_name": setting.model_name,
        "grading_provider": setting.grading_provider,
        "grading_model": setting.grading_model,
    }


@app.post("/api/settings/email")
def update_email_settings(
    recipient_email: str,
    smtp_from: str,
    smtp_user: str,
    smtp_app_password: str,
    send_empty_digest: int = 0,
    db: Session = Depends(get_db),
):
    setting = get_or_create_settings(db)
    setting.recipient_email = recipient_email
    setting.smtp_from = smtp_from
    setting.smtp_user = smtp_user
    setting.smtp_app_password = smtp_app_password
    setting.send_empty_digest = 1 if send_empty_digest else 0
    db.commit()
    return {"ok": True}


@app.post("/api/reminder/run-daily-debug", response_model=ReminderRunResponse)
def run_daily_debug(db: Session = Depends(get_db)):
    status, due_count, message = run_daily_reminder(
        db=db,
        now=_now(),
        review_entry_url=settings.review_entry_url,
        sender=DummySender(),
    )
    return ReminderRunResponse(status=status, due_count=due_count, message=message)


def _parse_import_payload(fmt: str, raw: str) -> list[tuple[str, str]]:
    if fmt == "csv":
        out: list[tuple[str, str]] = []
        lines = [line for line in raw.splitlines() if line.strip()]
        for line in lines:
            parts = line.split(",", 1)
            if len(parts) != 2:
                continue
            out.append((parts[0].strip(), parts[1].strip()))
        return out

    chunks: list[tuple[str, str]] = []
    title: Optional[str] = None
    body_lines: list[str] = []

    for line in raw.splitlines():
        if line.strip().startswith("## "):
            if title and body_lines:
                chunks.append((title, "\n".join(body_lines).strip()))
            title = line.strip()[3:].strip()
            body_lines = []
        else:
            body_lines.append(line)

    if title and body_lines:
        chunks.append((title, "\n".join(body_lines).strip()))

    return chunks


def _kp_out(kp: KnowledgePoint) -> KnowledgePointOut:
    return KnowledgePointOut(
        id=kp.id,
        title=kp.title,
        content=kp.content,
        tags=[x for x in kp.tags.split(",") if x],
        mastery=kp.mastery,
        stage=kp.stage,
        next_review_at=kp.next_review_at,
    )
