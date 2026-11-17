"""Deudas sin fecha fija: la fecha puede quedar vacía."""
from datetime import date

import pytest
from pydantic import ValidationError

from app.db.models import Movement
from app.schemas.debts import DebtCreateRequest, DebtUpdateRequest
from app.services.calendar_service import build_calendar
from app.services.debt_service import create_debt, pay_debt, update_debt
from app.services.finance_db_service import build_debts, today_gt

USER_TID = 999_999_999


def _undated(db, total=3):
    return create_debt(
        db, USER_TID, name="Equipo Sonido", creditor="Tienda", due_date=None,
        installment_amount=200.0, total_installments=total, paid_installments=0,
        payment_frequency="none",
    )


def test_schema_accepts_empty_date_only_without_fixed_frequency():
    base = dict(telegram_user_id=1, name="X", creditor="Y", installment_amount=10,
                total_installments=1, paid_installments=0)
    assert DebtCreateRequest(**base, due_date="", payment_frequency="none").due_date is None
    assert DebtCreateRequest(**base, payment_frequency="none").due_date is None
    with pytest.raises(ValidationError):
        DebtCreateRequest(**base, due_date="", payment_frequency="monthly")
    upd = dict(name="X", creditor="Y", installment_amount=10, total_installments=1)
    assert DebtUpdateRequest(**upd, due_date=None, payment_frequency="none").due_date is None
    with pytest.raises(ValidationError):
        DebtUpdateRequest(**upd, due_date=None, payment_frequency="weekly")


def test_service_requires_date_for_periodic_debts(db, test_user):
    with pytest.raises(ValueError):
        create_debt(db, USER_TID, name="A", creditor="B", due_date=None, installment_amount=1,
                    total_installments=1, paid_installments=0, payment_frequency="monthly")


def test_undated_debt_listed_and_pay_keeps_date_empty(db, test_user, user_accounts):
    debt = _undated(db)
    items = build_debts(db, USER_TID)["items"]
    assert any(d["id"] == debt.id and d["due_date"] is None for d in items)

    db.add(Movement(user_id=test_user.id, movement_type="ING", movement_date=date(2026, 6, 1),
                    amount=1000, target_account_id=user_accounts["efectivo"].id,
                    payment_method="cash", is_void=False))
    db.commit()
    paid = pay_debt(db, USER_TID, debt_id=debt.id, payment_date="2026-06-15",
                    payment_method="cash", account_name="Efectivo")
    assert paid.paid_installments == 1
    assert paid.due_date is None


def test_update_can_clear_and_set_date(db, test_user):
    debt = create_debt(db, USER_TID, name="A", creditor="B", due_date="2026-06-30",
                       installment_amount=100, total_installments=3, paid_installments=0,
                       payment_frequency="none")
    cleared = update_debt(db, USER_TID, debt.id, name="A", creditor="B", due_date="",
                          installment_amount=100, total_installments=3, payment_frequency="none")
    assert cleared.due_date is None
    dated = update_debt(db, USER_TID, debt.id, name="A", creditor="B", due_date="2026-07-15",
                        installment_amount=100, total_installments=3, payment_frequency="monthly")
    assert dated.due_date == date(2026, 7, 15)


def test_calendar_shows_undated_debt_once_outside_projection(db, test_user):
    debt = _undated(db, total=3)
    today = today_gt()
    cal = build_calendar(db, USER_TID, today.year, today.month)
    keys = [r["key"] for r in cal["items"]]
    assert not any(k.startswith(f"d:{debt.id}:") for k in keys)
    rows = [r for r in cal["undated"] if r.get("debt_id") == debt.id]
    assert len(rows) == 1
    assert rows[0]["date"] is None and rows[0]["action"] == "confirm"
    assert "quedan 3 cuotas" in rows[0]["note"]
