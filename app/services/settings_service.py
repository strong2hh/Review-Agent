from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import AppSetting

LEGACY_MODEL_FIELDS = {
    "model_provider": "deepseek",
    "model_name": app_settings.deepseek_model,
    "question_provider": "deepseek",
    "question_model": app_settings.deepseek_model,
    "grading_provider": "deepseek",
    "grading_model": app_settings.deepseek_model,
}


def get_or_create_settings(db: Session) -> AppSetting:
    setting = db.get(AppSetting, 1)
    if setting:
        changed = False
        for field, value in LEGACY_MODEL_FIELDS.items():
            if getattr(setting, field) != value:
                setattr(setting, field, value)
                changed = True
        if changed:
            db.commit()
            db.refresh(setting)
        return setting

    setting = AppSetting(id=1, **LEGACY_MODEL_FIELDS)
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting
