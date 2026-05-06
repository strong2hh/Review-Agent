from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppSetting, KnowledgePoint, ReminderLog
from app.services.settings_service import get_or_create_settings


class EmailSender:
    def send(self, to_email: str, from_email: str, subject: str, html_body: str, settings: AppSetting) -> str:
        raise NotImplementedError


class GmailSmtpSender(EmailSender):
    def send(self, to_email: str, from_email: str, subject: str, html_body: str, settings: AppSetting) -> str:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_app_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        return f"smtp-{int(datetime.utcnow().timestamp())}"


class DummySender(EmailSender):
    def send(self, to_email: str, from_email: str, subject: str, html_body: str, settings: AppSetting) -> str:
        return "dummy-message-id"


def build_digest_html(due_items: list[KnowledgePoint], review_entry_url: str) -> str:
    list_html = "".join([f"<li>{kp.title}（掌握度: {kp.mastery}）</li>" for kp in due_items[:30]])
    if not list_html:
        list_html = "<li>今天没有到期复习项</li>"

    return (
        "<h2>今日复习提醒</h2>"
        f"<p>到期/逾期知识点数量：<strong>{len(due_items)}</strong></p>"
        f"<ul>{list_html}</ul>"
        f"<p><a href=\"{review_entry_url}\">点击进入 Web 应用开始逐题复习</a></p>"
    )


def run_daily_reminder(
    db: Session,
    now: datetime,
    review_entry_url: str,
    sender: EmailSender,
) -> tuple[str, int, str]:
    settings = get_or_create_settings(db)

    existing_today = db.scalar(
        select(func.count(ReminderLog.id)).where(
            func.date(ReminderLog.sent_at) == now.date(),
            ReminderLog.status == "sent",
        )
    )
    if existing_today and existing_today > 0:
        return "already_sent", 0, "today digest already sent"

    due_items = list(
        db.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.next_review_at <= now)
            .order_by(KnowledgePoint.next_review_at.asc())
        ).all()
    )

    if not due_items and settings.send_empty_digest == 0:
        db.add(ReminderLog(sent_at=now, status="skipped", due_count=0, notes="no due items"))
        db.commit()
        return "skipped", 0, "no due items"

    if not settings.recipient_email:
        db.add(ReminderLog(sent_at=now, status="failed", due_count=len(due_items), notes="recipient missing"))
        db.commit()
        return "failed", len(due_items), "recipient email is not configured"

    if not (settings.smtp_user and settings.smtp_app_password and settings.smtp_from):
        db.add(
            ReminderLog(sent_at=now, status="failed", due_count=len(due_items), notes="smtp credentials missing")
        )
        db.commit()
        return "failed", len(due_items), "smtp settings are incomplete"

    subject = f"复习提醒：你有 {len(due_items)} 个知识点待复习"
    body = build_digest_html(due_items, review_entry_url)

    try:
        message_id = sender.send(
            to_email=settings.recipient_email,
            from_email=settings.smtp_from,
            subject=subject,
            html_body=body,
            settings=settings,
        )
        db.add(ReminderLog(sent_at=now, status="sent", due_count=len(due_items), message_id=message_id))
        db.commit()
        return "sent", len(due_items), "daily digest email sent"
    except Exception as exc:  # pragma: no cover
        db.add(ReminderLog(sent_at=now, status="failed", due_count=len(due_items), notes=str(exc)))
        db.commit()
        return "failed", len(due_items), f"send failed: {exc}"
