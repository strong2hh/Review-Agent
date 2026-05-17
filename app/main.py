from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import KnowledgePoint
from app.schemas import (
    GradingResultResponse,
    KnowledgePointCreate,
    KnowledgePointImportRequest,
    KnowledgePointOut,
    ReminderRunResponse,
    ReviewDueItem,
    SessionStatusResponse,
    StartSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.services.reminder_service import DummySender, GmailSmtpSender, run_daily_reminder
from app.services.review_service import (
    complete_grading_job,
    get_due_knowledge_points,
    get_grading_result,
    get_session_status,
    start_challenge_session,
    start_review_session,
    submit_answer,
)
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


def _run_grading_job_async(job_id: int) -> None:
    db = SessionLocal()
    try:
        complete_grading_job(db=db, job_id=job_id, now=_now())
    finally:
        db.close()


def _schedule_grading_job(job_id: int) -> None:
    thread = threading.Thread(target=_run_grading_job_async, args=(job_id,), daemon=True)
    thread.start()


@app.on_event("startup")
def on_startup() -> None:
    global scheduler
    init_db()

    db = SessionLocal()
    try:
        get_or_create_settings(db)
        pending_jobs = []
        try:
            from app.models import ReviewGradingJob

            pending_jobs = [row.id for row in db.query(ReviewGradingJob).filter(ReviewGradingJob.status == "pending")]
        except Exception:
            pending_jobs = []
    finally:
        db.close()

    for job_id in pending_jobs:
        _schedule_grading_job(job_id)

    if settings.app_env == "test":
        return

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger(hour=settings.reminder_hour, minute=settings.reminder_minute, timezone=settings.timezone),
        id="daily_digest",
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
def list_knowledge_points(
    limit: int = Query(default=100, ge=1, le=500),
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgePoint)
    search_term = q.strip() if q else ""
    if search_term:
        pattern = f"%{search_term}%"
        query = query.filter(
            or_(
                KnowledgePoint.title.ilike(pattern),
                KnowledgePoint.content.ilike(pattern),
                KnowledgePoint.tags.ilike(pattern),
            )
        )

    rows = query.order_by(KnowledgePoint.id.desc()).limit(limit).all()
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
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _start_session_response(session, current)


@app.post("/api/review/challenge/start", response_model=StartSessionResponse)
def start_challenge(db: Session = Depends(get_db)):
    session, current = start_challenge_session(db, now=_now())
    return _start_session_response(session, current)


def _start_session_response(session, current) -> StartSessionResponse:
    total = len(session.items)
    if not current:
        return StartSessionResponse(
            session_id=session.id,
            total_questions=total,
            current_index=total,
            question_id=None,
            knowledge_point_id=None,
            title=None,
            question=None,
        )

    return StartSessionResponse(
        session_id=session.id,
        total_questions=total,
        current_index=current.order_index + 1,
        question_id=current.id,
        knowledge_point_id=current.knowledge_point_id,
        title=current.knowledge_point.title,
        question=current.question,
    )


@app.post("/api/review/session/{session_id}/answer", response_model=SubmitAnswerResponse)
def submit_session_answer(session_id: int, payload: SubmitAnswerRequest, db: Session = Depends(get_db)):
    try:
        result = submit_answer(db=db, session_id=session_id, answer=payload.answer, now=_now())
        _schedule_grading_job(result["grading_job_id"])
        return SubmitAnswerResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review/grading-jobs/{job_id}", response_model=GradingResultResponse)
def review_grading_result(job_id: int, db: Session = Depends(get_db)):
    try:
        result = get_grading_result(db, job_id)
        return GradingResultResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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

    heading_re = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
    chunks: list[tuple[str, str]] = []
    title: Optional[str] = None
    body_lines: list[str] = []

    for raw_line in raw.splitlines():
        line = raw_line.lstrip("\ufeff")
        match = heading_re.match(line)
        if match:
            if title:
                content = "\n".join(body_lines).strip()
                if content:
                    chunks.append((title, content))
            title = match.group(1).strip()
            body_lines = []
            continue

        if title:
            body_lines.append(raw_line)

    if title:
        content = "\n".join(body_lines).strip()
        if content:
            chunks.append((title, content))

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
