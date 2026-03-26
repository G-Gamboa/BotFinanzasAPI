
from fastapi import APIRouter, Depends
from app.auth import require_x_user_id
from app.schemas.common import MessageResponse
from app.schemas.deudas import DeudaCreateRequest, PagarDeudaRequest
from app.services.deuda_service import create_deuda, get_deudas, get_deudas_activas, pagar_deuda

router = APIRouter()

@router.get("/deudas/{user_id}")
def deudas(user_id: int, _: int = Depends(require_x_user_id)):
    return get_deudas(user_id)

@router.get("/deudas/activas/{user_id}")
def deudas_activas(user_id: int, _: int = Depends(require_x_user_id)):
    return get_deudas_activas(user_id)

@router.post("/deudas", response_model=MessageResponse)
def nueva_deuda(payload: DeudaCreateRequest, _: int = Depends(require_x_user_id)):
    return create_deuda(payload)

@router.post("/deudas/pagar", response_model=MessageResponse)
def pagar(payload: PagarDeudaRequest, _: int = Depends(require_x_user_id)):
    return pagar_deuda(payload)
