from fastapi import HTTPException, status

from app.config import get_settings
from app.integrations.gspread_client import get_gspread_client


def resolve_sheet_id(user_id: int) -> str:
    settings = get_settings()
    sheet_id = settings.user_sheets.get(user_id)
    if not sheet_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Usuario no configurado en USER_SHEETS',
        )
    return sheet_id


def get_gc():
    return get_gspread_client()
