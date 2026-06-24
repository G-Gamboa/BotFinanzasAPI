"""Tests para finance_db_service — saldos, deudas, ahorro."""
from datetime import date

import pytest

from app.db.models import Account, Debt, DebtPayment, Movement
from app.services.finance_db_service import (
    _add_months,
    build_ahorro_breakdown,
    build_debts,
    build_saldos_map,
    get_usd_to_gtq,
)


USER_TID = 999_999_999


# ── _add_months ───────────────────────────────────────────────────────────────

class TestAddMonths:
    def test_normal_month(self):
        assert _add_months(date(2026, 3, 15), 1) == date(2026, 4, 15)

    def test_year_rollover(self):
        assert _add_months(date(2026, 11, 1), 2) == date(2027, 1, 1)

    def test_clamps_to_last_day(self):
        # 31 enero + 1 mes = 28 febrero (2025 no es bisiesto)
        assert _add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)

    def test_leap_year_feb(self):
        assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)

    def test_zero_months(self):
        assert _add_months(date(2026, 6, 15), 0) == date(2026, 6, 15)


# ── get_usd_to_gtq ────────────────────────────────────────────────────────────

class TestGetUsdToGtq:
    def test_returns_value_from_settings(self, db, test_user):
        rate = get_usd_to_gtq(db, test_user.id, fallback=7.0)
        assert rate == pytest.approx(7.7)

    def test_fallback_when_no_settings(self, db, test_user):
        from sqlalchemy import delete
        from app.db.models import UserSetting
        db.execute(delete(UserSetting).where(UserSetting.user_id == test_user.id))
        db.commit()
        assert get_usd_to_gtq(db, test_user.id, fallback=8.5) == 8.5


# ── build_saldos_map ──────────────────────────────────────────────────────────

def _ing(db, user_id, account_id, amount, payment_method="cash"):
    m = Movement(
        user_id=user_id,
        movement_type="ING",
        movement_date=date(2026, 6, 1),
        amount=amount,
        target_account_id=account_id if payment_method == "cash" else None,
        transfer_account_id=account_id if payment_method == "transfer" else None,
        payment_method=payment_method,
        is_void=False,
    )
    db.add(m)
    db.commit()
    return m


def _egr(db, user_id, account_id, amount, payment_method="cash"):
    m = Movement(
        user_id=user_id,
        movement_type="EGR",
        movement_date=date(2026, 6, 1),
        amount=amount,
        source_account_id=account_id if payment_method == "cash" else None,
        transfer_account_id=account_id if payment_method == "transfer" else None,
        payment_method=payment_method,
        is_void=False,
    )
    db.add(m)
    db.commit()
    return m


class TestBuildSaldosMap:
    def test_empty_accounts_all_zero(self, db, test_user, user_accounts):
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == 0.0
        assert saldos["Ahorro"] == 0.0

    def test_ingreso_cash_increases_account(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(1000.0)

    def test_ingreso_transfer_increases_account(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 500.0, payment_method="transfer")
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(500.0)

    def test_egreso_cash_decreases_account(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        _egr(db, test_user.id, user_accounts["efectivo"].id, 300.0)
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(700.0)

    def test_egreso_transfer_decreases_account(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        _egr(db, test_user.id, user_accounts["efectivo"].id, 200.0, payment_method="transfer")
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(800.0)

    def test_voided_movement_excluded(self, db, test_user, user_accounts):
        m = _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        m.is_void = True
        db.commit()
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(0.0)

    def test_mov_normal_transfers_between_accounts(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        mov = Movement(
            user_id=test_user.id,
            movement_type="MOV",
            movement_date=date(2026, 6, 2),
            amount=400.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            is_void=False,
        )
        db.add(mov)
        db.commit()
        saldos = build_saldos_map(db, USER_TID)
        assert saldos["Efectivo"] == pytest.approx(600.0)
        assert saldos["Ahorro"] == pytest.approx(400.0)

    def test_user_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            build_saldos_map(db, 0)


# ── build_debts ───────────────────────────────────────────────────────────────

class TestBuildDebts:
    def test_empty(self, db, test_user):
        result = build_debts(db, USER_TID)
        assert result["items"] == []
        assert result["total_pendiente"] == 0.0

    def test_active_debt_appears(self, db, test_user):
        db.add(Debt(
            user_id=test_user.id,
            name="Préstamo auto",
            creditor="Banco",
            due_date=date(2026, 12, 31),
            installment_amount=500.0,
            total_installments=12,
            paid_installments=2,
            status="active",
            payment_frequency="monthly",
        ))
        db.commit()
        result = build_debts(db, USER_TID)
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["name"] == "Préstamo auto"
        assert item["pending_installments"] == 10
        assert item["saldo_pendiente"] == pytest.approx(5000.0)

    def test_total_pendiente_sums_all(self, db, test_user):
        for i in range(3):
            db.add(Debt(
                user_id=test_user.id,
                name=f"Deuda {i}",
                creditor="Acreedor",
                due_date=date(2027, 1, 1),
                installment_amount=100.0,
                total_installments=5,
                paid_installments=0,
                status="active",
                payment_frequency="monthly",
            ))
        db.commit()
        result = build_debts(db, USER_TID)
        assert result["total_pendiente"] == pytest.approx(1500.0)


# ── build_ahorro_breakdown ────────────────────────────────────────────────────

class TestBuildAhorroBreakdown:
    def test_empty(self, db, test_user):
        result = build_ahorro_breakdown(db, USER_TID)
        assert result["total"] == 0.0
        assert result["items"] == []

    def test_guardar_ahorro_increases_breakdown(self, db, test_user, user_accounts):
        mov = Movement(
            user_id=test_user.id,
            movement_type="MOV",
            movement_date=date(2026, 6, 1),
            amount=500.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            is_void=False,
        )
        db.add(mov)
        db.commit()
        result = build_ahorro_breakdown(db, USER_TID)
        assert result["total"] == pytest.approx(500.0)
        assert result["items"][0]["cuenta"] == "Efectivo"
        assert result["items"][0]["saldo"] == pytest.approx(500.0)
