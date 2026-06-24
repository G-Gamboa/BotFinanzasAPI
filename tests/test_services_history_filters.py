"""Tests para history_service.build_history — filtros: note, amount_min/max,
payment_method; y los mismos sobre LoanPayments y DebtPayments."""
from datetime import date

import pytest

from app.db.models import (
    Debt, DebtPayment, Loan, LoanPayment, LoanPerson, Movement,
)
from app.services.history_service import build_history
from app.services.debt_service import create_debt, pay_debt


USER_TID = 999_999_999


# ── helpers ───────────────────────────────────────────────────────────────────

def _ing(db, user_id, account_id, amount=500.0, note=None, method="cash"):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 10), amount=amount,
        target_account_id=account_id, payment_method=method,
        note=note, is_void=False,
    )
    db.add(m)
    db.commit()
    return m


# ── Movement filters ──────────────────────────────────────────────────────────

class TestBuildHistoryNoteFilter:
    def test_note_filter_matches(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, note="Pago arriendo")
        _ing(db, test_user.id, user_accounts["efectivo"].id, note="Bono anual")

        result = build_history(db, USER_TID, note="arriendo")
        items = [i for i in result["items"] if i["record_type"] == "movement"]
        assert len(items) == 1
        assert items[0]["note"] == "Pago arriendo"

    def test_note_filter_case_insensitive(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, note="SALARIO Junio")

        result = build_history(db, USER_TID, note="salario")
        items = [i for i in result["items"] if i["record_type"] == "movement"]
        assert len(items) == 1


class TestBuildHistoryAmountFilter:
    def test_amount_min_excludes_smaller(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=100.0)
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=900.0)

        result = build_history(db, USER_TID, amount_min=500.0)
        amounts = [i["amount"] for i in result["items"] if i["record_type"] == "movement"]
        assert all(a >= 500.0 for a in amounts)
        assert 900.0 in amounts
        assert 100.0 not in amounts

    def test_amount_max_excludes_larger(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=200.0)
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=800.0)

        result = build_history(db, USER_TID, amount_max=400.0)
        amounts = [i["amount"] for i in result["items"] if i["record_type"] == "movement"]
        assert 200.0 in amounts
        assert 800.0 not in amounts

    def test_amount_min_and_max_combined(self, db, test_user, user_accounts):
        for amt in [100.0, 300.0, 600.0, 900.0]:
            _ing(db, test_user.id, user_accounts["efectivo"].id, amount=amt)

        result = build_history(db, USER_TID, amount_min=200.0, amount_max=700.0)
        amounts = [i["amount"] for i in result["items"] if i["record_type"] == "movement"]
        assert set(amounts) == {300.0, 600.0}


class TestBuildHistoryPaymentMethodFilter:
    def test_payment_method_filter(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=100.0, method="cash")
        _ing(db, test_user.id, user_accounts["efectivo"].id, amount=200.0, method="transfer")

        result = build_history(db, USER_TID, payment_method="transfer")
        items = [i for i in result["items"] if i["record_type"] == "movement"]
        assert len(items) == 1
        assert items[0]["amount"] == pytest.approx(200.0)


# ── LoanPayment filters ───────────────────────────────────────────────────────

@pytest.fixture
def loan_setup(db, test_user, user_accounts):
    person = LoanPerson(user_id=test_user.id, name="Héctor", is_active=True)
    db.add(person)
    db.commit()

    db.add(Movement(
        user_id=test_user.id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=5000.0,
        target_account_id=user_accounts["efectivo"].id,
        payment_method="cash", is_void=False,
    ))
    db.commit()

    loan = Loan(
        user_id=test_user.id,
        loan_person_id=person.id,
        loan_type="lent",
        principal_amount=2000.0,
        loan_date=date(2026, 6, 5),
        status="active",
        source_account_id=user_accounts["efectivo"].id,
    )
    db.add(loan)
    db.flush()

    return {"loan": loan, "person": person}


def _lp(db, user_id, loan_id, account_id, amount=500.0, note=None):
    lp = LoanPayment(
        loan_id=loan_id,
        user_id=user_id,
        amount=amount,
        payment_date=date(2026, 6, 15),
        account_id=account_id,
        note=note,
        is_void=False,
    )
    db.add(lp)
    db.commit()
    return lp


class TestBuildHistoryLoanPaymentFilters:
    def test_note_filter_on_loan_payment(self, db, test_user, user_accounts, loan_setup):
        loan = loan_setup["loan"]
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, note="primera cuota")
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, note="segunda cuota")

        result = build_history(db, USER_TID, note="primera")
        items = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert len(items) == 1
        assert items[0]["note"] == "primera cuota"

    def test_amount_min_on_loan_payment(self, db, test_user, user_accounts, loan_setup):
        loan = loan_setup["loan"]
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, amount=100.0)
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, amount=800.0)

        result = build_history(db, USER_TID, amount_min=500.0)
        lp_items = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert len(lp_items) == 1
        assert lp_items[0]["amount"] == pytest.approx(800.0)

    def test_amount_max_on_loan_payment(self, db, test_user, user_accounts, loan_setup):
        loan = loan_setup["loan"]
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, amount=200.0)
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id, amount=700.0)

        result = build_history(db, USER_TID, amount_max=400.0)
        lp_items = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        assert len(lp_items) == 1
        assert lp_items[0]["amount"] == pytest.approx(200.0)


# ── DebtPayment filters ───────────────────────────────────────────────────────

@pytest.fixture
def debt_with_balance(db, test_user, user_accounts):
    db.add(Movement(
        user_id=test_user.id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=5000.0,
        target_account_id=user_accounts["efectivo"].id,
        payment_method="cash", is_void=False,
    ))
    db.commit()
    return create_debt(
        db, USER_TID,
        name="Cuota casa",
        creditor="Banco",
        due_date="2026-06-20",
        installment_amount=400.0,
        total_installments=6,
        paid_installments=0,
    )


class TestBuildHistoryDebtPaymentFilters:
    def test_note_filter_on_debt_payment(self, db, test_user, user_accounts, debt_with_balance):
        debt = debt_with_balance
        # Pagar y luego insertar un segundo pago manual con nota diferente
        pay_debt(db, USER_TID, debt.id, "2026-06-10", "cash", "Efectivo", note="junio")

        # Segundo DebtPayment directo con nota diferente
        debt.paid_installments = 1  # ya contado arriba
        dp2 = DebtPayment(
            debt_id=debt.id,
            user_id=test_user.id,
            amount=400.0,
            payment_date=date(2026, 6, 20),
            account_id=user_accounts["efectivo"].id,
            note="julio",
            is_void=False,
        )
        db.add(dp2)
        db.commit()

        result = build_history(db, USER_TID, note="junio")
        dp_items = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert len(dp_items) == 1
        assert dp_items[0]["note"] == "junio"

    def test_amount_min_on_debt_payment(self, db, test_user, user_accounts):
        # Dos deudas con distinto installment_amount
        debt_small = create_debt(
            db, USER_TID, name="Pequeña", creditor="X",
            due_date="2026-06-20", installment_amount=100.0,
            total_installments=3, paid_installments=0,
        )
        debt_large = create_debt(
            db, USER_TID, name="Grande", creditor="Y",
            due_date="2026-06-20", installment_amount=800.0,
            total_installments=3, paid_installments=0,
        )

        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 1), amount=5000.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        pay_debt(db, USER_TID, debt_small.id, "2026-06-10", "cash", "Efectivo")
        pay_debt(db, USER_TID, debt_large.id, "2026-06-10", "cash", "Efectivo")

        result = build_history(db, USER_TID, amount_min=500.0)
        dp_items = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert len(dp_items) == 1
        assert dp_items[0]["amount"] == pytest.approx(800.0)

    def test_amount_max_on_debt_payment(self, db, test_user, user_accounts):
        debt = create_debt(
            db, USER_TID, name="Cuota", creditor="Z",
            due_date="2026-06-20", installment_amount=600.0,
            total_installments=3, paid_installments=0,
        )
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 1), amount=5000.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        pay_debt(db, USER_TID, debt.id, "2026-06-10", "cash", "Efectivo")

        result = build_history(db, USER_TID, amount_max=300.0)
        dp_items = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        assert len(dp_items) == 0  # 600 > 300 → excluido


# ── Date filters — líneas 108, 177, 179, 222, 224 ────────────────────────────

class TestBuildHistoryDateFilters:
    """Ejercita las ramas date_to (mov) y date_from/date_to (loan/debt payments)."""

    def test_date_to_excludes_later_movements(self, db, test_user, user_accounts):
        """line 108: Movement.movement_date <= parsed_date_to."""
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 5), amount=100.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 20), amount=200.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        result = build_history(db, USER_TID, date_to="2026-06-10")
        mov_items = [i for i in result["items"] if i["record_type"] == "movement"]
        assert len(mov_items) == 1
        assert mov_items[0]["amount"] == pytest.approx(100.0)

    def test_date_from_excludes_earlier_loan_payments(self, db, test_user, user_accounts, loan_setup):
        """line 177: LoanPayment.payment_date >= parsed_date_from."""
        loan = loan_setup["loan"]
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id,
            amount=300.0)  # 2026-06-15 (de helper)
        early_lp = LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=400.0,
            payment_date=date(2026, 5, 1),  # antes de date_from
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        )
        db.add(early_lp)
        db.commit()

        result = build_history(db, USER_TID, date_from="2026-06-01")
        lp_items = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        amounts = [i["amount"] for i in lp_items]
        assert 300.0 in amounts
        assert 400.0 not in amounts

    def test_date_to_excludes_later_loan_payments(self, db, test_user, user_accounts, loan_setup):
        """line 179: LoanPayment.payment_date <= parsed_date_to."""
        loan = loan_setup["loan"]
        _lp(db, test_user.id, loan.id, user_accounts["efectivo"].id,
            amount=300.0)  # 2026-06-15
        late_lp = LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=500.0,
            payment_date=date(2026, 7, 1),  # después de date_to
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        )
        db.add(late_lp)
        db.commit()

        result = build_history(db, USER_TID, date_to="2026-06-30")
        lp_items = [i for i in result["items"] if i["record_type"] == "loan_payment"]
        amounts = [i["amount"] for i in lp_items]
        assert 300.0 in amounts
        assert 500.0 not in amounts

    def test_date_from_excludes_earlier_debt_payments(self, db, test_user, user_accounts):
        """line 222: DebtPayment.payment_date >= parsed_date_from."""
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 5, 1), amount=5000.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        debt = create_debt(
            db, USER_TID, name="Deuda Fechas", creditor="X",
            due_date="2026-05-10", installment_amount=300.0,
            total_installments=4, paid_installments=0,
        )
        # Pago en mayo (antes del filtro)
        pay_debt(db, USER_TID, debt.id, "2026-05-10", "cash", "Efectivo")
        # Pago en junio (dentro del filtro)
        pay_debt(db, USER_TID, debt.id, "2026-06-10", "cash", "Efectivo")

        result = build_history(db, USER_TID, date_from="2026-06-01")
        dp_items = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        dates = [i["movement_date"] for i in dp_items]
        assert all(d >= "2026-06-01" for d in dates)
        assert len(dp_items) == 1

    def test_date_to_excludes_later_debt_payments(self, db, test_user, user_accounts):
        """line 224: DebtPayment.payment_date <= parsed_date_to."""
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 1), amount=5000.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        debt = create_debt(
            db, USER_TID, name="Deuda Fechas2", creditor="Y",
            due_date="2026-06-10", installment_amount=250.0,
            total_installments=4, paid_installments=0,
        )
        pay_debt(db, USER_TID, debt.id, "2026-06-10", "cash", "Efectivo")
        pay_debt(db, USER_TID, debt.id, "2026-07-10", "cash", "Efectivo")

        result = build_history(db, USER_TID, date_to="2026-06-30")
        dp_items = [i for i in result["items"] if i["record_type"] == "debt_payment"]
        dates = [i["movement_date"] for i in dp_items]
        assert all(d <= "2026-06-30" for d in dates)
        assert len(dp_items) == 1
