"""Tests para debt_service."""
from datetime import date, timedelta

import pytest

from app.services.debt_service import (
    advance_due_date,
    create_debt,
    parse_iso_date,
    update_debt,
)


USER_TID = 999_999_999


# ── parse_iso_date ────────────────────────────────────────────────────────────

class TestParseIsoDate:
    def test_valid_date(self):
        d = parse_iso_date("2026-06-15")
        assert d == date(2026, 6, 15)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_iso_date("15/06/2026")

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            parse_iso_date("2026-02-30")


# ── advance_due_date ──────────────────────────────────────────────────────────

class TestAdvanceDueDate:
    BASE = date(2026, 6, 15)

    def test_weekly(self):
        assert advance_due_date(self.BASE, "weekly") == date(2026, 6, 22)

    def test_biweekly(self):
        assert advance_due_date(self.BASE, "biweekly") == date(2026, 6, 29)

    def test_monthly(self):
        assert advance_due_date(self.BASE, "monthly") == date(2026, 7, 15)

    def test_monthly_end_of_month(self):
        # 31 de enero → 28 de febrero (no hay día 31 en feb)
        assert advance_due_date(date(2026, 1, 31), "monthly") == date(2026, 2, 28)

    def test_none_frequency_no_change(self):
        assert advance_due_date(self.BASE, "none") == self.BASE


# ── create_debt ───────────────────────────────────────────────────────────────

class TestCreateDebt:
    def test_creates_active_debt(self, db, test_user):
        debt = create_debt(
            db, USER_TID,
            name="Préstamo banco",
            creditor="Banco Industrial",
            due_date="2026-12-31",
            installment_amount=500.0,
            total_installments=12,
            paid_installments=0,
        )
        assert debt.id is not None
        assert debt.status == "active"
        assert debt.name == "Préstamo banco"
        assert debt.paid_installments == 0

    def test_already_paid_debt_has_paid_status(self, db, test_user):
        debt = create_debt(
            db, USER_TID,
            name="Deuda pagada",
            creditor="Amigo",
            due_date="2026-01-01",
            installment_amount=100.0,
            total_installments=3,
            paid_installments=3,
        )
        assert debt.status == "paid"

    def test_user_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            create_debt(
                db, 0,
                name="x", creditor="x",
                due_date="2026-01-01",
                installment_amount=100.0,
                total_installments=1,
                paid_installments=0,
            )

    def test_invalid_date_raises(self, db, test_user):
        with pytest.raises(ValueError):
            create_debt(
                db, USER_TID,
                name="x", creditor="x",
                due_date="not-a-date",
                installment_amount=100.0,
                total_installments=1,
                paid_installments=0,
            )


# ── update_debt ───────────────────────────────────────────────────────────────

class TestUpdateDebt:
    def _make_debt(self, db, test_user):
        return create_debt(
            db, USER_TID,
            name="Original",
            creditor="Acreedor",
            due_date="2026-12-31",
            installment_amount=200.0,
            total_installments=6,
            paid_installments=1,
        )

    def test_updates_fields(self, db, test_user):
        debt = self._make_debt(db, test_user)
        updated = update_debt(
            db, USER_TID,
            debt_id=debt.id,
            name="Nuevo nombre",
            creditor="Nuevo acreedor",
            due_date="2027-01-31",
            installment_amount=300.0,
            total_installments=6,
        )
        assert updated.name == "Nuevo nombre"
        assert updated.installment_amount == 300.0

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Deuda no encontrada"):
            update_debt(
                db, USER_TID,
                debt_id=99999,
                name="x", creditor="x",
                due_date="2026-01-01",
                installment_amount=100.0,
                total_installments=1,
            )

    def test_status_recalculated(self, db, test_user):
        debt = self._make_debt(db, test_user)  # paid=1, total=6 → active
        # Actualizar para que pagados >= total
        updated = update_debt(
            db, USER_TID,
            debt_id=debt.id,
            name=debt.name,
            creditor=debt.creditor,
            due_date="2026-12-31",
            installment_amount=200.0,
            total_installments=1,  # ahora paid(1) >= total(1) → paid
        )
        assert updated.status == "paid"
