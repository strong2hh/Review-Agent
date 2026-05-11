from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models import KnowledgePoint, ReviewAttempt, ReviewGradingJob, ReviewSession, ReviewSessionItem
from app.services.mastery import update_mastery_and_schedule
from app.services.model_service import ModelExecutionError, run_grading


def get_due_knowledge_points(db: Session, now: datetime) -> list[KnowledgePoint]:
    pending_kp_ids = (
        select(ReviewSessionItem.knowledge_point_id)
        .join(ReviewGradingJob, ReviewGradingJob.session_item_id == ReviewSessionItem.id)
        .where(ReviewGradingJob.status == "pending")
    )
    stmt: Select[tuple[KnowledgePoint]] = (
        select(KnowledgePoint)
        .where(KnowledgePoint.next_review_at <= now, KnowledgePoint.id.not_in(pending_kp_ids))
        .order_by(KnowledgePoint.next_review_at.asc(), KnowledgePoint.id.asc())
    )
    return list(db.scalars(stmt).all())


def start_review_session(db: Session, now: datetime) -> Tuple[ReviewSession, Optional[ReviewSessionItem]]:
    due_items = get_due_knowledge_points(db, now)

    session = ReviewSession(status="in_progress", started_at=now)
    db.add(session)
    db.flush()

    for idx, kp in enumerate(due_items):
        item = ReviewSessionItem(
            session_id=session.id,
            knowledge_point_id=kp.id,
            order_index=idx,
            question=kp.title,
        )
        db.add(item)

    db.commit()
    db.refresh(session)
    current_item = _get_next_item(db, session.id)
    return session, current_item


def _get_next_item(db: Session, session_id: int) -> Optional[ReviewSessionItem]:
    stmt = (
        select(ReviewSessionItem)
        .where(ReviewSessionItem.session_id == session_id, ReviewSessionItem.answered_at.is_(None))
        .order_by(ReviewSessionItem.order_index.asc())
        .limit(1)
    )
    return db.scalar(stmt)


def submit_answer(db: Session, session_id: int, answer: str, now: datetime) -> dict:
    session = db.get(ReviewSession, session_id)
    if not session:
        raise ValueError("session not found")
    if session.status == "completed":
        raise ValueError("session already completed")

    item = _get_next_item(db, session_id)
    if not item:
        session.status = "completed"
        session.completed_at = now
        db.commit()
        raise ValueError("no pending question")

    kp = db.get(KnowledgePoint, item.knowledge_point_id)
    if not kp:
        raise ValueError("knowledge point not found")

    job = ReviewGradingJob(
        session_item_id=item.id,
        user_answer=answer,
        status="pending",
        created_at=now,
    )
    db.add(job)
    db.flush()

    item.answered_at = now

    # SessionLocal uses autoflush=False, so flush before looking up next pending item.
    db.flush()

    next_item = _get_next_item(db, session_id)
    completed = next_item is None
    if completed:
        session.status = "completed"
        session.completed_at = now

    db.commit()

    return {
        "session_id": session.id,
        "question_id": item.id,
        "grading_job_id": job.id,
        "grading_status": job.status,
        "score_0_100": None,
        "star_0_5": None,
        "correction": None,
        "key_points": None,
        "missing_parts": None,
        "correct_answer": None,
        "mastery_before": None,
        "mastery_after": None,
        "next_review_at": None,
        "next_question_id": None if completed else next_item.id,
        "next_title": None if completed else next_item.knowledge_point.title,
        "next_question": None if completed else next_item.question,
        "completed": completed,
    }


def complete_grading_job(db: Session, job_id: int, now: datetime) -> None:
    job = db.get(ReviewGradingJob, job_id)
    if not job or job.status != "pending":
        return

    item = db.get(ReviewSessionItem, job.session_item_id)
    if not item:
        job.status = "failed"
        job.error = "session item not found"
        job.completed_at = now
        db.commit()
        return

    kp = db.get(KnowledgePoint, item.knowledge_point_id)
    if not kp:
        job.status = "failed"
        job.error = "knowledge point not found"
        job.completed_at = now
        db.commit()
        return

    try:
        grade = run_grading(db, item.question, kp.content, job.user_answer, now)
    except ModelExecutionError as exc:
        job.status = "failed"
        job.error = str(exc)[:2000]
        job.completed_at = now
        db.commit()
        return

    old_mastery = kp.mastery
    new_mastery, new_stage, next_review_at, star = update_mastery_and_schedule(
        old_mastery=kp.mastery,
        old_stage=kp.stage,
        score_0_100=grade.score,
        now=now,
    )

    attempt = ReviewAttempt(
        knowledge_point_id=kp.id,
        question=item.question,
        user_answer=job.user_answer,
        score_0_100=grade.score,
        star_0_5=star,
        correction=grade.correction,
        key_points=grade.key_points,
        created_at=now,
    )
    db.add(attempt)
    db.flush()

    item.attempt_id = attempt.id
    kp.mastery = new_mastery
    kp.stage = new_stage
    kp.next_review_at = next_review_at
    kp.last_reviewed_at = now
    job.missing_parts = json.dumps(grade.missing_parts, ensure_ascii=False)
    job.mastery_before = old_mastery
    job.mastery_after = new_mastery
    job.next_review_at = next_review_at
    job.status = "completed"
    job.completed_at = now
    db.commit()


def get_grading_result(db: Session, job_id: int) -> dict:
    job = db.get(ReviewGradingJob, job_id)
    if not job:
        raise ValueError("grading job not found")

    item = db.get(ReviewSessionItem, job.session_item_id)
    if not item:
        raise ValueError("session item not found")

    kp = db.get(KnowledgePoint, item.knowledge_point_id)
    if not kp:
        raise ValueError("knowledge point not found")

    if job.status != "completed":
        return {
            "grading_job_id": job.id,
            "status": job.status,
            "error": job.error,
            "question_id": item.id,
            "title": kp.title,
            "score_0_100": None,
            "star_0_5": None,
            "correction": None,
            "key_points": None,
            "missing_parts": None,
            "correct_answer": None,
            "mastery_before": job.mastery_before,
            "mastery_after": job.mastery_after,
            "next_review_at": None,
        }

    attempt = db.get(ReviewAttempt, item.attempt_id) if item.attempt_id else None
    if not attempt:
        return {
            "grading_job_id": job.id,
            "status": "pending",
            "error": "",
            "question_id": item.id,
            "title": kp.title,
            "score_0_100": None,
            "star_0_5": None,
            "correction": None,
            "key_points": None,
            "missing_parts": None,
            "correct_answer": None,
            "mastery_before": job.mastery_before,
            "mastery_after": job.mastery_after,
            "next_review_at": None,
        }

    return {
        "grading_job_id": job.id,
        "status": job.status,
        "error": "",
        "question_id": item.id,
        "title": kp.title,
        "score_0_100": attempt.score_0_100,
        "star_0_5": attempt.star_0_5,
        "correction": attempt.correction,
        "key_points": attempt.key_points,
        "missing_parts": _load_missing_parts(job.missing_parts),
        "correct_answer": kp.content,
        "mastery_before": job.mastery_before,
        "mastery_after": job.mastery_after,
        "next_review_at": job.next_review_at,
    }


def _load_missing_parts(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def get_session_status(db: Session, session_id: int) -> dict:
    session = db.scalar(
        select(ReviewSession)
        .options(selectinload(ReviewSession.items))
        .where(ReviewSession.id == session_id)
    )
    if not session:
        raise ValueError("session not found")

    total = len(session.items)
    completed = len([i for i in session.items if i.answered_at is not None])

    scores: list[int] = []
    for i in session.items:
        if i.attempt_id:
            attempt = db.get(ReviewAttempt, i.attempt_id)
            if attempt:
                scores.append(attempt.score_0_100)
    average_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    return {
        "session_id": session.id,
        "status": session.status,
        "completed_questions": completed,
        "total_questions": total,
        "average_score": average_score,
    }
