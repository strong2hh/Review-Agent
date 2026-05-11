from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import AppSetting

DEFAULT_PROVIDER = "mock" if app_settings.app_env == "test" else "deepseek"
DEFAULT_MODEL = "mock-v1" if app_settings.app_env == "test" else "deepseek-chat"
DEFAULT_QUESTION_MODEL = "mock-q-v1" if app_settings.app_env == "test" else "deepseek-chat"
DEFAULT_GRADING_MODEL = "mock-g-v1" if app_settings.app_env == "test" else "deepseek-chat"


def get_or_create_settings(db: Session) -> AppSetting:
    setting = db.get(AppSetting, 1)
    if setting:
        changed = False
        if not setting.question_provider:
            setting.question_provider = DEFAULT_PROVIDER
            changed = True
        if not setting.question_model:
            setting.question_model = DEFAULT_QUESTION_MODEL
            changed = True
        if not setting.grading_provider:
            setting.grading_provider = setting.model_provider or DEFAULT_PROVIDER
            changed = True
        if not setting.grading_model:
            setting.grading_model = setting.model_name or DEFAULT_GRADING_MODEL
            changed = True
        if changed:
            db.commit()
            db.refresh(setting)
        return setting

    setting = AppSetting(
        id=1,
        model_provider=DEFAULT_PROVIDER,
        model_name=DEFAULT_MODEL,
        question_provider=DEFAULT_PROVIDER,
        question_model=DEFAULT_QUESTION_MODEL,
        grading_provider=DEFAULT_PROVIDER,
        grading_model=DEFAULT_GRADING_MODEL,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting
