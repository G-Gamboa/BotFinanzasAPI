from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.dashboard_service import get_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/{user_id}")
def dashboard(user_id: int):
    settings = get_settings()
    sheet_id = settings.user_sheets_map.get(str(user_id))
    if not sheet_id:
        raise HTTPException(status_code=404, detail="Usuario no configurado.")

    try:
        return get_dashboard(sheet_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))