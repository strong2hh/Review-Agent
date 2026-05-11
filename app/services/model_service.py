from __future__ import annotations

import os
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Callable, Optional, TypeVar

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import AppSetting, ModelTaskFailure
from app.services.llm import GradeResult, ModelCallError, ProviderFactory

T = TypeVar("T")

MAX_RETRIES = 3
ALERT_COOLDOWN_HOURS = int(os.getenv("MODEL_FAILURE_ALERT_COOLDOWN_HOURS", "6"))
BACKOFF_BASE_SEC = 0.0 if app_settings.app_env == "test" else float(os.getenv("MODEL_RETRY_BACKOFF_SEC", "0.2"))


class TaskType:
    QUESTION_GENERATION = "question_generation"
    GRADING = "grading"


class ModelExecutionError(Exception):
    pass


def run_question_generation(db: Session, cfg: AppSetting, title: str, content: str, now: datetime) -> str:
    def _op() -> str:
        provider = ProviderFactory.build(cfg.question_provider)
        return provider.generate_question(cfg.question_model, title, content)

    return _run_with_retry(
        db=db,
        cfg=cfg,
        task_type=TaskType.QUESTION_GENERATION,
        provider_name=cfg.question_provider,
        model_name=cfg.question_model,
        now=now,
        operation=_op,
    )


def run_grading(
    db: Session,
    cfg: AppSetting,
    question: str,
    reference: str,
    user_answer: str,
    now: datetime,
) -> GradeResult:
    def _op() -> GradeResult:
        provider = ProviderFactory.build(cfg.grading_provider)
        return provider.grade_answer(cfg.grading_model, question, reference, user_answer)

    return _run_with_retry(
        db=db,
        cfg=cfg,
        task_type=TaskType.GRADING,
        provider_name=cfg.grading_provider,
        model_name=cfg.grading_model,
        now=now,
        operation=_op,
    )


def _run_with_retry(
    db: Session,
    cfg: AppSetting,
    task_type: str,
    provider_name: str,
    model_name: str,
    now: datetime,
    operation: Callable[[], T],
) -> T:
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = operation()
            _record_success(db, task_type)
            return result
        except Exception as exc:
            if isinstance(exc, ModelCallError):
                last_error = str(exc)
            else:
                last_error = f"unexpected:{exc}"

            _record_failure(
                db=db,
                cfg=cfg,
                task_type=task_type,
                provider_name=provider_name,
                model_name=model_name,
                error=last_error,
                now=now,
            )

            if attempt < MAX_RETRIES and BACKOFF_BASE_SEC > 0:
                time.sleep(BACKOFF_BASE_SEC * (2 ** (attempt - 1)))

    raise ModelExecutionError(
        f"{task_type} failed after {MAX_RETRIES} retries"
        f" [provider={provider_name}, model={model_name}, error={last_error}]"
    )


def _record_success(db: Session, task_type: str) -> None:
    row = db.get(ModelTaskFailure, task_type)
    if not row:
        return
    if row.consecutive_failures == 0 and not row.last_error:
        return
    row.consecutive_failures = 0
    row.last_error = ""
    db.commit()


def _record_failure(
    db: Session,
    cfg: AppSetting,
    task_type: str,
    provider_name: str,
    model_name: str,
    error: str,
    now: datetime,
) -> None:
    row = db.get(ModelTaskFailure, task_type)
    if not row:
        row = ModelTaskFailure(task_type=task_type)
        db.add(row)
        db.flush()

    row.consecutive_failures = int(row.consecutive_failures or 0) + 1
    row.last_error = error[:2000]
    row.last_failed_at = now

    should_alert = row.consecutive_failures >= MAX_RETRIES and _alert_window_open(row.last_alert_at, now)
    if should_alert:
        sent = _send_failure_alert(cfg, task_type, provider_name, model_name, row.consecutive_failures, row.last_error)
        if sent:
            row.last_alert_at = now

    db.commit()


def _alert_window_open(last_alert_at: Optional[datetime], now: datetime) -> bool:
    if not last_alert_at:
        return True
    return now - last_alert_at >= timedelta(hours=ALERT_COOLDOWN_HOURS)


def _send_failure_alert(
    cfg: AppSetting,
    task_type: str,
    provider_name: str,
    model_name: str,
    consecutive_failures: int,
    error: str,
) -> bool:
    if not app_settings.recipient_email:
        return False
    if not (app_settings.smtp_user and app_settings.smtp_app_password and app_settings.smtp_from):
        return False

    subject = f"[Review Agent] 模型任务失败告警: {task_type}"
    body = (
        "<h3>模型调用连续失败告警</h3>"
        f"<p><strong>任务类型:</strong> {task_type}</p>"
        f"<p><strong>Provider:</strong> {provider_name}</p>"
        f"<p><strong>Model:</strong> {model_name}</p>"
        f"<p><strong>连续失败次数:</strong> {consecutive_failures}</p>"
        f"<p><strong>最近错误:</strong> {error}</p>"
    )

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = app_settings.smtp_from
    msg["To"] = app_settings.recipient_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(app_settings.smtp_user, app_settings.smtp_app_password)
            server.sendmail(app_settings.smtp_from, [app_settings.recipient_email], msg.as_string())
        return True
    except Exception:
        return False
