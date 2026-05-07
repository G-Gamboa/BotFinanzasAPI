from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool


class SaldoItem(BaseModel):
    cuenta: str
    saldo: float


class AhorroCuentaItem(BaseModel):
    cuenta: str
    saldo: float


class DebtItem(BaseModel):
    id: int
    name: str
    creditor: str
    due_date: str
    installment_amount: float
    total_installments: int
    paid_installments: int
    pending_installments: int
    saldo_pendiente: float
    status: str


class DebtsResponse(BaseModel):
    total_pendiente: float
    items: list[DebtItem]


class NetworthResponse(BaseModel):
    liquid_map: dict[str, float]
    liquidez_gtq: float

    ahorro_total_gtq: float
    ahorro_por_cuenta: list[AhorroCuentaItem]

    prestamos_map: dict[str, float]
    prestamos_gtq: float

    inv_map: dict[str, float]
    inv_total_usd: float

    total_gtq: float
    tc: float


class NetoResponse(BaseModel):
    patrimonio_bruto: float
    pasivos: float
    patrimonio_neto: float


class PeriodSummary(BaseModel):
    periodo: str
    fecha_inicio: str
    fecha_fin: str
    ingresos: float
    egresos: float
    balance: float
    gastos_por_categoria: dict[str, float]
    top_gastos: list[dict[str, float | str]]


class LoanConceptItem(BaseModel):
    concept: str
    balance: float


class LoanPersonSummary(BaseModel):
    person: str
    total_balance: float
    concepts: list[LoanConceptItem]


class PrestamosResumen(BaseModel):
    items: list[LoanPersonSummary]
    total_people: int


class SavingsGoalDashItem(BaseModel):
    id: int
    name: str
    target_amount: float
    account_name: str | None = None
    current_amount: float
    is_active: bool


class DashboardResponse(BaseModel):
    networth: NetworthResponse
    neto: NetoResponse
    resumen_dia: PeriodSummary
    resumen_semana: PeriodSummary
    resumen_mes: PeriodSummary
    prestamos_resumen: PrestamosResumen
    savings_goals: list[SavingsGoalDashItem]