
from typing import Optional

from fastapi import Header, HTTPException, status


def get_optional_user_id(x_user_id: Optional[str] = Header(default=None)) -> Optional[int]:
    if x_user_id is None or x_user_id == "":
        return None
    try:
        return int(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id debe ser numérico",
        ) from exc
