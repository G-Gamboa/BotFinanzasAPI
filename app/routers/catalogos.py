from fastapi import APIRouter

from app.deps import resolve_sheet_id
from app.schemas.catalogos import CatalogosResponse
from app.services.catalog_service import get_catalogos_for_user

router = APIRouter(prefix='/catalogos', tags=['catalogos'])


@router.get('/{user_id}', response_model=CatalogosResponse)
def catalogos(user_id: int):
    sheet_id = resolve_sheet_id(user_id)
    return get_catalogos_for_user(sheet_id)
