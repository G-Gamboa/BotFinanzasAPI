"""Tests para debt_service.pay_debt (lines 107-159)."""
from datetime import date

import pytest

from app.db.models import Account, Movement
from app.services.debt_service import create_debt, pay_debt


USER_TID = 999_999_999


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_debt(db, test_user, total=3, paid=0, frequency="monthly", amount=500.0):
    return create_debt(
        db, USER_TID,
        name="Tarjeta Visa",
        creditor="Banco Industrial",
        due_date="2026-06-15",
        installment_amount=amount,
        total_installments=total,
        paid_installments=paid,
        payment_frequency=frequency,
    )


def _fund(db, user_id, account_id, amount=2000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


# ── TestPayDebt ───────────────────────────────────────────────────────────────

class TestPayDebt:
    def test_success_increments_paid_installments(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.paid_installments == 1
        assert result.status == "active"

    def test_last_payment_sets_status_paid(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=2, paid=1)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.paid_installments == 2
        assert result.status == "paid"

    def test_due_date_advances_monthly(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0, frequency="monthly")
        original_due = debt.due_date  # 2026-06-15
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.due_date == date(2026, 7, 15)

    def test_due_date_advances_weekly(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=4, paid=0, frequency="weekly")
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.due_date == date(2026, 6, 22)

    def test_due_date_advances_biweekly(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=4, paid=0, frequency="biweekly")
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.due_date == date(2026, 6, 29)

    def test_due_date_unchanged_for_none_frequency(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0, frequency="none")
        original_due = debt.due_date
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.due_date == original_due

    def test_last_payment_does_not_advance_due_date(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=1, paid=0, frequency="monthly")
        original_due = debt.due_date
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        result = pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        assert result.status == "paid"
        # El due_date no debe avanzar cuando se termina de pagar
        assert result.due_date == original_due

    def test_custom_note_stored(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
            note="Pago extra",
        )

        from app.db.models import DebtPayment
        from sqlalchemy import select
        payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id))
        assert payment.note == "Pago extra"

    def test_default_note_when_none(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        from app.db.models import DebtPayment
        from sqlalchemy import select
        payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id))
        assert "Tarjeta Visa" in payment.note

    def test_debt_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Deuda no encontrada"):
            pay_debt(
                db, USER_TID, debt_id=99999,
                payment_date="2026-06-15",
                payment_method="cash",
                account_name="Efectivo",
            )

    def test_already_paid_raises(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=2, paid=2)  # ya pagada
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        with pytest.raises(ValueError, match="ya está pagada"):
            pay_debt(
                db, USER_TID,
                debt_id=debt.id,
                payment_date="2026-06-15",
                payment_method="cash",
                account_name="Efectivo",
            )

    def test_account_not_found_raises(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        with pytest.raises(ValueError, match="La cuenta no existe"):
            pay_debt(
                db, USER_TID,
                debt_id=debt.id,
                payment_date="2026-06-15",
                payment_method="cash",
                account_name="NoExiste",
            )

    def test_non_liquid_account_raises(self, db, test_user, user_accounts):
        # Crear una cuenta de tipo inversión (no líquida)
        inv = Account(
            user_id=test_user.id, name="Binance",
            account_type="investment", currency="USD",
            is_active=True, is_system=False, sort_order=5,
        )
        db.add(inv)
        db.commit()

        debt = _make_debt(db, test_user, total=3, paid=0)

        with pytest.raises(ValueError, match="debe ser líquida"):
            pay_debt(
                db, USER_TID,
                debt_id=debt.id,
                payment_date="2026-06-15",
                payment_method="cash",
                account_name="Binance",
            )

    def test_insufficient_balance_raises(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0, amount=1000.0)
        # No fondear Efectivo → saldo 0 < 1000

        with pytest.raises(ValueError, match="Saldo insuficiente"):
            pay_debt(
                db, USER_TID,
                debt_id=debt.id,
                payment_date="2026-06-15",
                payment_method="cash",
                account_name="Efectivo",
            )

    def test_creates_debt_payment_record(self, db, test_user, user_accounts):
        debt = _make_debt(db, test_user, total=3, paid=0, amount=300.0)
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        pay_debt(
            db, USER_TID,
            debt_id=debt.id,
            payment_date="2026-06-15",
            payment_method="cash",
            account_name="Efectivo",
        )

        from app.db.models import DebtPayment
        from sqlalchemy import select
        payment = db.scalar(select(DebtPayment).where(DebtPayment.debt_id == debt.id))
        assert payment is not None
        assert float(payment.amount) == pytest.approx(300.0)
        assert payment.payment_date == date(2026, 6, 15)
