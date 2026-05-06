from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models import KnowledgePoint, ReviewAttempt, ReviewSession, ReviewSessionItem
from app.services.model_service import run_grading, run_question_generation
from app.services.mastery import update_mastery_and_schedule
from app.services.settings_service import get_or_create_settings


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", text.lower()))


def _split_reference_points(reference: str) -> list[str]:
    if not reference.strip():
        return []

    chunks: list[str] = []
    for line in reference.replace("\r\n", "\n").split("\n"):
        for part in re.split(r"[。；;！？!?]", line):
            for sub in re.split(r"[，,、]", part):
                clean = re.sub(r"^\s*[-*•\d\.\)]\s*", "", sub).strip()
                if clean:
                    chunks.append(clean)

    dedup: list[str] = []
    for c in chunks:
        if c not in dedup:
            dedup.append(c)
    return dedup


def _extract_missing_parts(reference: str, user_answer: str) -> list[str]:
    points = _split_reference_points(reference)
    if not points:
        return []

    answer_tokens = _tokenize(user_answer)
    missing: list[str] = []
    for p in points:
        point_tokens = _tokenize(p)
        # If no token can be matched, fall back to substring matching.
        covered = bool(point_tokens & answer_tokens) if point_tokens else p in user_answer
        if not covered:
            missing.append(p)
    return missing[:12]


def get_due_knowledge_points(db: Session, now: datetime) -> list[KnowledgePoint]:
    stmt: Select[tuple[KnowledgePoint]] = (
        select(KnowledgePoint)
        .where(KnowledgePoint.next_review_at <= now)
        .order_by(KnowledgePoint.next_review_at.asc(), KnowledgePoint.id.asc())
    )
    return list(db.scalars(stmt).all())


def start_review_session(db: Session, now: datetime) -> Tuple[ReviewSession, Optional[ReviewSessionItem]]:
    due_items = get_due_knowledge_points(db, now)
    cfg = get_or_create_settings(db)

    generated_questions: list[tuple[KnowledgePoint, str]] = []
    for kp in due_items:
        question = run_question_generation(db, cfg, kp.title, kp.content, now)
        generated_questions.append((kp, question))

    session = ReviewSession(status="in_progress", started_at=now)
    db.add(session)
    db.flush()

    for idx, row in enumerate(generated_questions):
        kp, question = row
        item = ReviewSessionItem(
            session_id=session.id,
            knowledge_point_id=kp.id,
            order_index=idx,
            question=question,
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

    cfg = get_or_create_settings(db)
    grade = run_grading(db, cfg, item.question, kp.content, answer, now)

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
        user_answer=answer,
        score_0_100=grade.score,
        star_0_5=star,
        correction=grade.correction,
        key_points=grade.key_points,
        created_at=now,
    )
    db.add(attempt)
    db.flush()

    item.answered_at = now
    item.attempt_id = attempt.id

    kp.mastery = new_mastery
    kp.stage = new_stage
    kp.next_review_at = next_review_at
    kp.last_reviewed_at = now

    # SessionLocal uses autoflush=False, so flush before looking up next pending item.
    db.flush()

    next_item = _get_next_item(db, session_id)
    completed = next_item is None
    if completed:
        session.status = "completed"
        session.completed_at = now

    db.commit()

    missing_parts = _extract_missing_parts(kp.content, answer)

    return {
        "session_id": session.id,
        "question_id": item.id,
        "score_0_100": grade.score,
        "star_0_5": star,
        "correction": grade.correction,
        "key_points": grade.key_points,
        "missing_parts": missing_parts,
        "correct_answer": kp.content,
        "mastery_before": old_mastery,
        "mastery_after": new_mastery,
        "next_review_at": next_review_at,
        "next_question_id": None if completed else next_item.id,
        "next_title": None if completed else next_item.knowledge_point.title,
        "next_question": None if completed else next_item.question,
        "completed": completed,
    }


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
