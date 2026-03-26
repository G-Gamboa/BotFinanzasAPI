
from fastapi import Header, HTTPException, status
from app.config import settings

def authorize_user_id(user_id: int) -> int:
    allowed_ids = settings.allowed_user_ids
    if allowed_ids and user_id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario no autorizado")
    return user_id

def require_x_user_id(x_user_id: int | None = Header(default=None)) -> int:
    if x_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta header X-User-Id")
    return authorize_user_id(int(x_user_id))
