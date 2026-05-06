from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(String(500), default="")
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    attempts: Mapped[list[ReviewAttempt]] = relationship(back_populates="knowledge_point")


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    score_0_100: Mapped[int] = mapped_column(Integer, nullable=False)
    star_0_5: Mapped[int] = mapped_column(Integer, nullable=False)
    correction: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="attempts")


class ReviewSession(Base):
    __tablename__ = "review_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    items: Mapped[list[ReviewSessionItem]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ReviewSessionItem(Base):
    __tablename__ = "review_session_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("review_sessions.id"), nullable=False)
    knowledge_point_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("review_attempts.id"), nullable=True)

    session: Mapped[ReviewSession] = relationship(back_populates="items")
    knowledge_point: Mapped[KnowledgePoint] = relationship()


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    due_count: Mapped[int] = mapped_column(Integer, default=0)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class AppSetting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    model_provider: Mapped[str] = mapped_column(String(50), default="deepseek")
    model_name: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    question_provider: Mapped[str] = mapped_column(String(50), default="deepseek")
    question_model: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    grading_provider: Mapped[str] = mapped_column(String(50), default="deepseek")
    grading_model: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    recipient_email: Mapped[str] = mapped_column(String(255), default="")
    smtp_from: Mapped[str] = mapped_column(String(255), default="")
    smtp_user: Mapped[str] = mapped_column(String(255), default="")
    smtp_app_password: Mapped[str] = mapped_column(String(255), default="")
    send_empty_digest: Mapped[int] = mapped_column(Integer, default=0)


class ModelTaskFailure(Base):
    __tablename__ = "model_task_failures"

    task_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_alert_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
