from pydantic import BaseModel


class ResumenPeriodoResponse(BaseModel):
    periodo: str
    fecha_inicio: str
    fecha_fin: str
    ingresos: float
    egresos: float
    balance: float
    gastos_por_categoria: dict[str, float]
    top_gastos: list[dict]
