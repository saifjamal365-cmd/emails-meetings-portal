"""Read the single row of user settings (created with defaults the first time)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings


def get_app_settings(db: Session) -> AppSettings:
    row = db.scalar(select(AppSettings).limit(1))
    if row is None:
        row = AppSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row
