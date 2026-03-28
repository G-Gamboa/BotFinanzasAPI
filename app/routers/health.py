from fastapi import APIRouter
from app.schemas.finance import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health():
    return {"ok": True}
