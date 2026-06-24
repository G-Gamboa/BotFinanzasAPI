"""Tests para finance_db_service — build_cc_balances, build_networth, build_neto,
rangos de fecha, build_period_summary."""
from datetime import date

import pytest

from app.db.models import Account, Debt, Movement
from app.services.finance_db_service import (
    _last_close_date,
    build_cc_balances,
    build_neto,
    build_networth,
    build_period_summary,
    day_range,
    month_range,
    week_range,
)


USER_TID = 999_999_999


# ── _last_close_date ──────────────────────────────────────────────────────────

class TestLastCloseDate:
    def test_close_day_in_past_this_month(self):
        # Hoy 24, corte el 15 → último corte fue el 15 de este mes
        assert _last_close_date(date(2026, 6, 24), 15) == date(2026, 6, 15)

    def test_close_day_is_today(self):
        assert _last_close_date(date(2026, 6, 15), 15) == date(2026, 6, 15)

    def test_close_day_in_future_this_month(self):
        # Hoy 10, corte el 25 → último corte fue el 25 del mes anterior
        assert _last_close_date(date(2026, 6, 10), 25) == date(2026, 5, 25)

    def test_close_day_31_in_june(self):
        # Junio: min(31, 30) = 30 → candidate = 30 jun
        # 30 jun > 24 jun (hoy) → va al mes anterior
        # Mayo: min(31, 31) = 31 → last close = 31 mayo
        result = _last_close_date(date(2026, 6, 24), 31)
        assert result == date(2026, 5, 31)

    def test_close_day_past_in_short_month(self):
        # Hoy 28 feb (no bisiesto), corte 28 → último corte fue el 28 de feb
        assert _last_close_date(date(2025, 2, 28), 28) == date(2025, 2, 28)


class TestLastCloseDateFixed:
    """Tests más limpios que no tienen ramas ambiguas."""
    def test_close_past_same_month(self):
        d = _last_close_date(date(2026, 6, 20), 10)
        assert d == date(2026, 6, 10)

    def test_close_future_goes_prev_month(self):
        d = _last_close_date(date(2026, 6, 5), 20)
        assert d == date(2026, 5, 20)

    def test_january_1st_with_close_5(self):
        # Hoy 1 enero, corte 5 → diciembre anterior
        d = _last_close_date(date(2026, 1, 1), 5)
        assert d == date(2025, 12, 5)


# ── date range helpers ────────────────────────────────────────────────────────

class TestDateRanges:
    def test_day_range(self):
        start, end = day_range(date(2026, 6, 15))
        assert start == end == date(2026, 6, 15)

    def test_week_range_monday(self):
        # 2026-06-15 es lunes
        start, end = week_range(date(2026, 6, 15))
        assert start == date(2026, 6, 15)
        assert end == date(2026, 6, 21)

    def test_week_range_wednesday(self):
        # 2026-06-17 es miércoles → semana empieza el lunes 15
        start, end = week_range(date(2026, 6, 17))
        assert start == date(2026, 6, 15)

    def test_month_range_june(self):
        start, end = month_range(date(2026, 6, 15))
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 30)

    def test_month_range_december(self):
        start, end = month_range(date(2026, 12, 1))
        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)


# ── build_cc_balances ─────────────────────────────────────────────────────────

@pytest.fixture
def cc_account(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Visa GTQ",
        account_type="credit_card", currency="GTQ",
        is_active=True, is_system=False, sort_order=10,
        tc_type="GTQ", billing_close_day=15, payment_due_day=25,
    )
    db.add(acc)
    db.commit()
    return acc


class TestBuildCcBalances:
    def test_no_cc_accounts_returns_empty(self, db, test_user):
        assert build_cc_balances(db, USER_TID) == []

    def test_single_gtq_charge(self, db, test_user, cc_account, user_categories):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="EGR",
            movement_date=date(2026, 6, 1),
            amount=500.0,
            category_id=user_categories["alimentacion"].id,
            payment_method="credit_card",
            credit_card_account_id=cc_account.id,
            is_void=False,
        ))
        db.commit()
        result = build_cc_balances(db, USER_TID)
        assert len(result) == 1
        item = result[0]
        assert item["name"] == "Visa GTQ"
        assert item["balance_gtq"] == pytest.approx(500.0)

    def test_voided_charge_excluded(self, db, test_user, cc_account, user_categories):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="EGR",
            movement_date=date(2026, 6, 1),
            amount=500.0,
            category_id=user_categories["alimentacion"].id,
            payment_method="credit_card",
            credit_card_account_id=cc_account.id,
            is_void=True,
        ))
        db.commit()
        result = build_cc_balances(db, USER_TID)
        assert result[0]["balance_gtq"] == pytest.approx(0.0)

    def test_result_has_required_fields(self, db, test_user, cc_account):
        result = build_cc_balances(db, USER_TID)
        item = result[0]
        for field in ("id", "name", "tc_type", "balance", "balance_gtq", "regular_balance",
                      "visacuota_balance", "balance_at_close_gtq", "pending_to_pay_gtq"):
            assert field in item, f"Campo faltante: {field}"

    def test_inactive_cc_excluded(self, db, test_user, cc_account):
        cc_account.is_active = False
        db.commit()
        assert build_cc_balances(db, USER_TID) == []


# ── build_networth ────────────────────────────────────────────────────────────

class TestBuildNetworth:
    def test_empty_returns_zeros(self, db, test_user, user_accounts):
        result = build_networth(db, USER_TID, fallback_tc=7.7)
        assert result["liquidez_gtq"] == 0.0
        assert result["total_gtq"] == 0.0

    def test_liquid_balance_included(self, db, test_user, user_accounts):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="ING",
            movement_date=date(2026, 6, 1),
            amount=1000.0,
            target_account_id=user_accounts["efectivo"].id,
            payment_method="cash",
            is_void=False,
        ))
        db.commit()
        result = build_networth(db, USER_TID, fallback_tc=7.7)
        assert result["liquidez_gtq"] == pytest.approx(1000.0)
        assert result["total_gtq"] == pytest.approx(1000.0)

    def test_has_required_fields(self, db, test_user, user_accounts):
        result = build_networth(db, USER_TID, fallback_tc=7.7)
        for f in ("liquid_map", "liquidez_gtq", "ahorro_total_gtq", "prestamos_gtq",
                  "inv_total_usd", "total_gtq", "tc"):
            assert f in result


# ── build_neto ────────────────────────────────────────────────────────────────

class TestBuildNeto:
    def test_no_pasivos(self, db, test_user, user_accounts):
        result = build_neto(db, USER_TID, fallback_tc=7.7)
        assert result["pasivos"] == 0.0
        assert result["patrimonio_neto"] == result["patrimonio_bruto"]

    def test_debt_increases_pasivos(self, db, test_user, user_accounts):
        db.add(Debt(
            user_id=test_user.id, name="Deuda",
            creditor="Banco", due_date=date(2027, 1, 1),
            installment_amount=500.0,
            total_installments=3, paid_installments=0,
            status="active", payment_frequency="monthly",
        ))
        db.commit()
        result = build_neto(db, USER_TID, fallback_tc=7.7)
        assert result["pasivos"] == pytest.approx(1500.0)
        assert result["patrimonio_neto"] == pytest.approx(-1500.0)

    def test_has_all_fields(self, db, test_user, user_accounts):
        result = build_neto(db, USER_TID, fallback_tc=7.7)
        for f in ("patrimonio_bruto", "pasivos", "patrimonio_neto",
                  "compromiso_visacuotas", "patrimonio_neto_ajustado"):
            assert f in result


# ── build_period_summary ──────────────────────────────────────────────────────

class TestBuildPeriodSummary:
    def test_empty_period(self, db, test_user):
        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert result["ingresos"] == 0.0
        assert result["egresos"] == 0.0

    def test_ingreso_counted(self, db, test_user, user_accounts, user_categories):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="ING",
            movement_date=date(2026, 6, 15),
            amount=800.0,
            target_account_id=user_accounts["efectivo"].id,
            category_id=user_categories["salario"].id,
            payment_method="cash",
            is_void=False,
        ))
        db.commit()
        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert result["ingresos"] == pytest.approx(800.0)
        assert result["egresos"] == 0.0

    def test_movement_outside_range_excluded(self, db, test_user, user_accounts, user_categories):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="ING",
            movement_date=date(2026, 5, 1),  # mayo, fuera del rango junio
            amount=500.0,
            target_account_id=user_accounts["efectivo"].id,
            category_id=user_categories["salario"].id,
            payment_method="cash",
            is_void=False,
        ))
        db.commit()
        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert result["ingresos"] == 0.0
