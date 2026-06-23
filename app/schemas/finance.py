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
    payment_frequency: str = "monthly"


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
    compromiso_visacuotas: float = 0.0
    patrimonio_neto_ajustado: float = 0.0


class PeriodSummary(BaseModel):
    periodo: str
    fecha_inicio: str
    fecha_fin: str
    ingresos: float
    egresos: float
    balance: float
    gastos_por_categoria: dict[str, float]
    detalle_por_categoria: dict[str, list[dict]] = {}
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


class CreditCardBalanceItem(BaseModel):
    id: int
    name: str
    tc_type: str                        # 'GTQ' | 'USD' | 'MIXTO'
    balance: float                      # saldo en moneda nativa ($ para USD, Q para GTQ/MIXTO)
    balance_gtq: float                  # saldo total convertido a GTQ (para networth/pasivos)
    # Desglose por moneda (relevante para MIXTO; para GTQ/USD uno de los dos es 0)
    balance_gtq_portion: float = 0.0   # saldo de cargos en Q
    balance_usd_portion: float = 0.0   # saldo de cargos en $ (en dólares)
    regular_balance: float              # saldo total − visacuotas (unidades nativas)
    visacuota_balance: float            # cargos ya generados de planes de cuotas (unidades nativas)
    visacuota_remaining: float = 0.0   # cuotas futuras pendientes × monthly_amount (compromiso restante)
    credit_limit: float | None = None
    visacuotas_limit: float | None = None
    tc_exchange_rate: float | None = None
    billing_close_day: int | None = None
    payment_due_day: int | None = None
    last_close_date: str | None = None
    balance_at_close_gtq: float | None = None
    pending_to_pay_gtq: float | None = None
    pending_usd_portion: float | None = None


class CreditCardBalancesResponse(BaseModel):
    items: list[CreditCardBalanceItem]