import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import get_settings
from app.db.database import get_db
from app.db.models import User
from app.security.telegram_auth import validate_init_data
from app.ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])


@router.websocket("/ws/{telegram_user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    telegram_user_id: int,
    initData: str = Query(...),
):
    settings = get_settings()

    # Validar initData (same HMAC check as HTTP auth, but close instead of 401)
    try:
        auth = validate_init_data(
            init_data_raw=initData,
            bot_token=settings.telegram_bot_token,
            max_age_seconds=3600,
        )
    except Exception:
        await websocket.close(code=4001)
        return

    if auth["user"]["id"] != telegram_user_id:
        await websocket.close(code=4003)
        return

    # Verify user exists and is active
    db = next(get_db())
    try:
        user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        if not user or not user.is_active:
            await websocket.close(code=4003)
            return
    finally:
        db.close()

    await manager.connect(telegram_user_id, websocket)
    try:
        while True:
            # Keep connection alive; client may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(telegram_user_id, websocket)
    except Exception:
        manager.disconnect(telegram_user_id, websocket)
