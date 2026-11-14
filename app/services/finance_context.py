"""Datos financieros de un usuario cargados una sola vez por request.

Cada colección se consulta la primera vez que se pide y queda en memoria,
de modo que varios cálculos (saldos, tarjetas, patrimonio, calendario)
comparten las mismas filas en vez de repetir consultas.
"""
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Account, Category, CreditCardInstallmentPlan, CreditCardPayment, Debt,
    DebtPayment, Loan, LoanPayment, LoanPerson, Movement, User, UserSetting,
)


class FinanceContext:
    def __init__(self, db: Session, telegram_user_id: int, user: User | None = None):
        self.db = db
        self.telegram_user_id = telegram_user_id
        self._user = user
        self.memo: dict = {}

    @cached_property
    def user(self) -> User:
        if self._user is not None:
            return self._user
        user = self.db.scalar(select(User).where(User.telegram_user_id == self.telegram_user_id))
        if not user:
            raise ValueError("Usuario no encontrado.")
        return user

    def _all(self, model, *where):
        return list(self.db.scalars(select(model).where(model.user_id == self.user.id, *where)).all())

    @cached_property
    def setting(self) -> UserSetting | None:
        return self.db.scalar(select(UserSetting).where(UserSetting.user_id == self.user.id))

    @cached_property
    def accounts(self) -> list[Account]:
        return self._all(Account)

    @cached_property
    def account_by_id(self) -> dict[int, Account]:
        return {a.id: a for a in self.accounts}

    @cached_property
    def categories(self) -> list[Category]:
        return self._all(Category)

    @cached_property
    def loan_people(self) -> list[LoanPerson]:
        return self._all(LoanPerson)

    @cached_property
    def movements(self) -> list[Movement]:
        """Movimientos no anulados."""
        return self._all(Movement, Movement.is_void == False)

    @cached_property
    def loans(self) -> list[Loan]:
        return sorted(self._all(Loan), key=lambda x: x.id)

    @cached_property
    def loan_payments(self) -> list[LoanPayment]:
        return sorted(self._all(LoanPayment, LoanPayment.is_void == False), key=lambda x: x.id)

    @cached_property
    def debts(self) -> list[Debt]:
        return sorted(self._all(Debt), key=lambda x: (x.due_date, x.id))

    @cached_property
    def debt_payments(self) -> list[DebtPayment]:
        return self._all(DebtPayment, DebtPayment.is_void == False)

    @cached_property
    def cc_payments(self) -> list[CreditCardPayment]:
        return self._all(CreditCardPayment, CreditCardPayment.is_void == False)

    @cached_property
    def plans(self) -> list[CreditCardInstallmentPlan]:
        return self._all(CreditCardInstallmentPlan)

    @cached_property
    def paid_by_plan(self) -> dict[int, int]:
        """Cuotas ya generadas por plan (movimientos vigentes ligados al plan)."""
        counts: dict[int, int] = {}
        for m in self.movements:
            if m.installment_plan_id is not None:
                counts[m.installment_plan_id] = counts.get(m.installment_plan_id, 0) + 1
        return counts


def resolve_context(db: Session, telegram_user_id: int, ctx: FinanceContext | None) -> FinanceContext:
    return ctx if ctx is not None else FinanceContext(db, telegram_user_id)
