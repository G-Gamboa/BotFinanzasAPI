from typing import List

from pydantic import BaseModel


class CatalogosResponse(BaseModel):
    FUENTES_ING: List[str]
    CATEG_ING: List[str]
    METODOS: List[str]
    BANCOS: List[str]
    CATEG_EGR: List[str]
    CUENTAS: List[str]
    PERSONAS_PRESTAMO: List[str]
