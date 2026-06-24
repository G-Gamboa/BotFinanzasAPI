# Backward-compatibility shim — logic moved to domain routers in this package.
# Kept so that any external tooling importing from here no longer breaks.
from app.dependencies import get_current_app_user, ensure_same_user, ensure_payload_user  # noqa: F401
from fastapi import APIRouter

router = APIRouter(tags=["finance"])
