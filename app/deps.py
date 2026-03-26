
from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


def get_user_sheet_id(user_id: int, settings: Settings = Depends(get_app_settings)) -> str:
    sheet_id = settings.user_sheets.get(user_id)
    if not sheet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no configurado en USER_SHEETS",
        )
    return sheet_id
