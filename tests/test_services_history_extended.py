"""Tests para history_service — loan_payments, debt_payments, void helpers."""
from datetime import date, datetime, timezone

import pytest

from app.db.models import Debt, DebtPayment, Loan, LoanPayment, LoanPerson, Movement
from app.services.history_service import (
    build_history,
    void_debt_payment,
    void_loan_payment,
)


USER_TID = 999_999_999


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def loan_setup(db, test_user, user_accounts):
    """Person + Loan + LoanPayment listo para usar."""
    person = LoanPerson(user_id=test_user.id, name="Carlos", is_active=True)
    db.add(person)
    db.flush()

    loan = Loan(
        user_id=test_user.id,
        loan_person_id=person.id,
        loan_type="lent",
        principal_amount=1000.0,
        loan_date=date(2026, 1, 1),
        status="active",
    )
    db.add(loan)
    db.flush()

    payment = LoanPayment(
        loan_id=loan.id,
        user_id=test_user.id,
        amount=250.0,
        payment_date=date(2026, 6, 10),
        account_id=user_accounts["efectivo"].id,
        is_void=False,
        note="Cobro parcial",
    )
    db.add(payment)
    db.commit()
    return {"person": person, "loan": loan, "payment": payment}


@pytest.fixture
def debt_setup(db, test_user, user_accounts):
    """Debt + DebtPayment listos para usar."""
    debt = Debt(
        user_id=test_user.id,
        name="Crédito banco",
        creditor="Banco Industrial",
        due_date=date(2026, 12, 31),
        installment_amount=300.0,
        total_installments=6,
        paid_installments=1,
        status="active",
        payment_frequency="monthly",
    )
    db.add(debt)
    db.flush()

    payment = DebtPayment(
        debt_id=debt.id,
        user_id=test_user.id,
        amount=300.0,
        payment_date=date(2026, 6, 5),
        account_id=user_accounts["efectivo"].id,
        is_void=False,
        note="Primera cuota",
    )
    db.add(payment)
    db.commit()
    return {"debt": debt, "payment": payment}


# ── build_history con loan_payments ──────────────────────────────────────────

class TestBuildHistoryLoanPayments:
    def test_loan_payment_appears_as_ing(self, db, test_user, loan_setup):
        result = build_history(db, USER_TID)
        cobros = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert len(cobros) == 1
        assert cobros[0]["movement_type"] == "ING"
        assert cobros[0]["subtype"] == "COBRO"
        assert cobros[0]["amount"] == 250.0

    def test_voided_loan_payment_excluded(self, db, test_user, loan_setup):
        loan_setup["payment"].is_void = True
        db.commit()
        result = build_history(db, USER_TID)
        cobros = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert cobros == []

    def test_loan_payment_excluded_when_filtering_egr(self, db, test_user, loan_setup):
        # LoanPayments son ING; filtrar por EGR no debe mostrarlos
        result = build_history(db, USER_TID, movement_type="EGR")
        cobros = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert cobros == []

    def test_loan_payment_excluded_when_filtering_by_category(self, db, test_user, loan_setup):
        # LoanPayments no tienen categoría; filtro por category_name los excluye
        result = build_history(db, USER_TID, category_name="Salario")
        cobros = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert cobros == []


# ── build_history con debt_payments ──────────────────────────────────────────

class TestBuildHistoryDebtPayments:
    def test_debt_payment_appears_as_egr(self, db, test_user, debt_setup):
        result = build_history(db, USER_TID)
        pagos = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert len(pagos) == 1
        assert pagos[0]["movement_type"] == "EGR"
        assert pagos[0]["subtype"] == "PAGO_DEUDA"
        assert pagos[0]["amount"] == 300.0
        assert pagos[0]["debt_name"] == "Crédito banco"

    def test_voided_debt_payment_excluded(self, db, test_user, debt_setup):
        debt_setup["payment"].is_void = True
        db.commit()
        result = build_history(db, USER_TID)
        pagos = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert pagos == []

    def test_debt_payment_excluded_when_filtering_ing(self, db, test_user, debt_setup):
        result = build_history(db, USER_TID, movement_type="ING")
        pagos = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert pagos == []

    def test_debt_payment_has_correct_date(self, db, test_user, debt_setup):
        result = build_history(db, USER_TID)
        pagos = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert pagos[0]["movement_date"] == "2026-06-05"


# ── void_loan_payment ─────────────────────────────────────────────────────────

class TestVoidLoanPayment:
    def test_void_ok(self, db, test_user, loan_setup):
        lp = void_loan_payment(db, USER_TID, loan_setup["payment"].id, "Error cobro")
        assert lp.is_void is True
        assert lp.void_reason == "Error cobro"
        assert lp.voided_at is not None

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Cobro no encontrado"):
            void_loan_payment(db, USER_TID, 99999, None)

    def test_already_voided_raises(self, db, test_user, loan_setup):
        void_loan_payment(db, USER_TID, loan_setup["payment"].id, "Primera")
        with pytest.raises(ValueError, match="ya está anulado"):
            void_loan_payment(db, USER_TID, loan_setup["payment"].id, "Segunda")


# ── void_debt_payment ─────────────────────────────────────────────────────────

class TestVoidDebtPayment:
    def test_void_ok_reverts_installment(self, db, test_user, debt_setup):
        debt = debt_setup["debt"]
        initial_paid = debt.paid_installments  # 1

        dp = void_debt_payment(db, USER_TID, debt_setup["payment"].id, "Anulación")
        assert dp.is_void is True
        assert dp.void_reason == "Anulación"

        db.refresh(debt)
        assert debt.paid_installments == initial_paid - 1  # 0

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Pago de deuda no encontrado"):
            void_debt_payment(db, USER_TID, 99999, None)

    def test_already_voided_raises(self, db, test_user, debt_setup):
        void_debt_payment(db, USER_TID, debt_setup["payment"].id, "Primera")
        with pytest.raises(ValueError, match="ya está anulado"):
            void_debt_payment(db, USER_TID, debt_setup["payment"].id, "Segunda")

    def test_debt_status_reverts_to_active(self, db, test_user, debt_setup):
        debt = debt_setup["debt"]
        # Forzar que la deuda esté "paid"
        debt.paid_installments = debt.total_installments
        debt.status = "paid"
        db.commit()

        void_debt_payment(db, USER_TID, debt_setup["payment"].id, None)
        db.refresh(debt)
        # Después de anular 1 pago, paid < total → vuelve a active
        assert debt.status == "active"
