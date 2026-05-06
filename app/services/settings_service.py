from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import AppSetting


def _apply_env_email_defaults(setting: AppSetting) -> bool:
    changed = False
    if not setting.recipient_email and app_settings.recipient_email:
        setting.recipient_email = app_settings.recipient_email
        changed = True
    if not setting.smtp_from and app_settings.smtp_from:
        setting.smtp_from = app_settings.smtp_from
        changed = True
    if not setting.smtp_user and app_settings.smtp_user:
        setting.smtp_user = app_settings.smtp_user
        changed = True
    if not setting.smtp_app_password and app_settings.smtp_app_password:
        setting.smtp_app_password = app_settings.smtp_app_password
        changed = True
    return changed


def get_or_create_settings(db: Session) -> AppSetting:
    setting = db.get(AppSetting, 1)
    if setting:
        changed = False
        if not setting.question_provider:
            setting.question_provider = "mock"
            changed = True
        if not setting.question_model:
            setting.question_model = "mock-q-v1"
            changed = True
        if not setting.grading_provider:
            setting.grading_provider = setting.model_provider or "mock"
            changed = True
        if not setting.grading_model:
            setting.grading_model = setting.model_name or "mock-g-v1"
            changed = True
        changed = _apply_env_email_defaults(setting) or changed
        if changed:
            db.commit()
            db.refresh(setting)
        return setting

    setting = AppSetting(
        id=1,
        model_provider="mock",
        model_name="mock-v1",
        question_provider="mock",
        question_model="mock-q-v1",
        grading_provider="mock",
        grading_model="mock-g-v1",
        recipient_email=app_settings.recipient_email,
        smtp_from=app_settings.smtp_from,
        smtp_user=app_settings.smtp_user,
        smtp_app_password=app_settings.smtp_app_password,
        send_empty_digest=app_settings.send_empty_digest,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting
