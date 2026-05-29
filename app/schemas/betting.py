from pydantic import BaseModel, Field


class BetItem(BaseModel):
    id: int
    fecha: str
    deporte: str
    partido: str
    pick: str
    cuota: float
    stake: float
    estado: str
    ganancia: float | None = None


class BettingConfigSchema(BaseModel):
    bank_inicial: float
    meta: float


class BettingResponse(BaseModel):
    items: list[BetItem]
    config: BettingConfigSchema


class CreateBetRequest(BaseModel):
    fecha: str = Field(min_length=1, max_length=50)
    deporte: str = Field(min_length=1, max_length=50)
    partido: str = Field(min_length=1, max_length=200)
    pick: str = Field(min_length=1, max_length=200)
    cuota: float = Field(gt=1.0)
    stake: float = Field(gt=0)
    estado: str = "pendiente"


class UpdateBetRequest(BaseModel):
    estado: str | None = None
    fecha: str | None = None
    deporte: str | None = None
    partido: str | None = None
    pick: str | None = None
    cuota: float | None = None
    stake: float | None = None


class UpdateConfigRequest(BaseModel):
    bank_inicial: float | None = None
    meta: float | None = None
