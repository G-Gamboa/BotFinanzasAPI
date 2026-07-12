from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base




class Movement(Base):
    __tablename__ = "movements"
    __table_args__ = (
        CheckConstraint(
            "payment_method IN ('cash', 'transfer', 'credit_card')",
            name="movements_payment_method_check",
        ),
        Index("idx_movements_user_void", "user_id", "is_void"),
        Index("idx_movements_user_date", "user_id", "movement_date"),
        Index("idx_movements_cc_account", "credit_card_account_id", "is_void"),
        Index("idx_movements_installment_plan", "installment_plan_id", "is_void"),
        Index("idx_movements_savings_goal", "savings_goal_id", "is_void"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    movement_type: Mapped[str] = mapped_column(String, nullable=False)  # ING / EGR / MOV
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    destination_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    transfer_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    loan_person_id: Mapped[int | None] = mapped_column(ForeignKey("loan_people.id"), nullable=True)
    savings_goal_id: Mapped[int | None] = mapped_column(ForeignKey("savings_goals.id"), nullable=True)
    credit_card_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)

    # Visacuota: FK al plan que generó este cargo (EGR automático)
    installment_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("cc_installment_plans.id"), nullable=True
    )
    # Para TC MIXTO con cargo en USD: monto original en dólares (amount = Q equivalente)
    amount_foreign: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # True cuando el cargo a TC es un préstamo a tercero (no es gasto propio)
    is_third_party: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_use_loans: Mapped[bool] = mapped_column(Boolean, default=False)
    theme_key: Mapped[str] = mapped_column(String, default="neutral")
    # NULL = sin vencimiento (cuentas heredadas / admin). Fecha futura = suscripción activa.
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('cash', 'bank', 'investment', 'asset', 'savings', 'loan_pool', 'credit_card')",
            name="accounts_type_check",
        ),
        Index("idx_accounts_user_id", "user_id"),
        Index("idx_accounts_user_type_active", "user_id", "account_type", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Credit card fields (nullable, only used when account_type == "credit_card")
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    billing_close_day: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1–28
    payment_due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)     # 1–28
    # TC multi-moneda: 'GTQ' | 'USD' | 'MIXTO' — NULL se trata como 'GTQ'
    tc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Tipo de cambio por defecto para TC MIXTO (cargos en USD → Q)
    tc_exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    # Límite independiente para visacuotas; NULL = comparte el límite general
    visacuotas_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class LoanPerson(Base):
    __tablename__ = "loan_people"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
class Debt(Base):
    __tablename__ = "debts"
    __table_args__ = (
        Index("idx_debts_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    creditor: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # weekly | biweekly | monthly | none
    payment_frequency: Mapped[str] = mapped_column(String, nullable=False, default="monthly")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        Index("idx_budgets_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class UserSetting(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    preferred_currency: Mapped[str] = mapped_column(String, nullable=False, default="GTQ")
    usd_to_gtq: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=7.7000)
    hide_amounts_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_amounts_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_tab: Mapped[str] = mapped_column(String, nullable=False, default="movimientos")
    theme_key: Mapped[str | None] = mapped_column(String, nullable=True, default="default")
    tab_order: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: ["movimientos","historial",...]
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        Index("idx_loans_user_type", "user_id", "loan_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    loan_person_id: Mapped[int] = mapped_column(ForeignKey("loan_people.id"), nullable=False)
    loan_type: Mapped[str] = mapped_column(String, nullable=False)  # 'lent' | 'borrowed'
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    loan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    # Cuando el préstamo fue dado desde TC (no desde cuenta líquida)
    source_tc_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)


class LoanPayment(Base):
    __tablename__ = "loan_payments"
    __table_args__ = (
        Index("idx_loan_payments_user_void", "user_id", "is_void"),
        Index("idx_loan_payments_loan_id", "loan_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String, nullable=True)  # matches ahorro_por_cuenta key
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CreditCardPayment(Base):
    __tablename__ = "credit_card_payments"
    __table_args__ = (
        Index("idx_cc_payments_user_void", "user_id", "is_void"),
        Index("idx_cc_payments_cc_account", "credit_card_account_id", "is_void"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    credit_card_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # GTQ debitados de la cuenta líquida (siempre en Q, es lo que sale de tu bolsillo)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Dólares pagados a la tarjeta: reduce el saldo en $ de la TC.
    # Aplica a TC USD (todo el pago) y TC MIXTO (pago de la porción $).
    # Cuando IS NULL → pago en Q puro (GTQ TC, o porción Q de MIXTO).
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DebtPayment(Base):
    __tablename__ = "debt_payments"
    __table_args__ = (
        Index("idx_debt_payments_user_void", "user_id", "is_void"),
        Index("idx_debt_payments_user_date", "user_id", "payment_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



class VaultConfig(Base):
    """Configuración zero-knowledge del vault: solo salt y DEK envuelta. El servidor nunca ve KEK ni DEK en claro."""
    __tablename__ = "vault_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    salt: Mapped[str] = mapped_column(String, nullable=False)        # base64url, 16 bytes random
    dek_wrapped: Mapped[str] = mapped_column(String, nullable=False)  # base64url, AES-256-GCM(KEK, DEK)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VaultItem(Base):
    """Item cifrado del vault. El servidor solo almacena ciphertext opaco."""
    __tablename__ = "vault_items"
    __table_args__ = (Index("idx_vault_items_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)    # base64url, AES-256-GCM(DEK, JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CreditCardInstallmentPlan(Base):
    """Plan de cuotas (Visacuotas) vinculado a una tarjeta de crédito.

    Cada mes, en la fecha de corte de la TC, el sistema genera automáticamente
    un EGR movement con note='Visacuota: {name}' vinculado a este plan
    (Movement.installment_plan_id).  El campo paid_installments se calcula
    contando esos movements, nunca se almacena redundante.
    """

    __tablename__ = "cc_installment_plans"
    __table_args__ = (
        Index("idx_cc_plans_user_status", "user_id", "status", "is_active"),
        Index("idx_cc_plans_cc_account", "credit_card_account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    credit_card_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Monto total en la moneda de la TC (Q para GTQ/MIXTO, $ para USD)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    # Almacenado por conveniencia = total_amount / total_installments
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Fecha del primer cargo (primer corte donde aparece)
    first_charge_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active|completed|cancelled
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Visacuota de préstamo: cada cuota genera DAR_TC (EGR is_third_party + Loan) en vez de EGR propio
    is_loan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    loan_person_id: Mapped[int | None] = mapped_column(ForeignKey("loan_people.id"), nullable=True)
    # Categoría de egreso para planes propios (opcional, aplicada al EGR mensual)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
