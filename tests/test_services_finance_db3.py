"""Tests para finance_db_service — gaps restantes:
build_ahorro_breakdown RETIRAR path, build_period_summary EGR con categoría,
build_savings_goals RETIRAR, build_neto con plan futuro, build_cc_balances
TC payments after close, visacuota remaining, sin close_date.
"""
from datetime import date, datetime, timezone

import pytest

from app.db.models import (
    Account, CreditCardInstallmentPlan, CreditCardPayment, Movement, SavingsGoal,
)
from app.services.finance_db_service import (
    build_ahorro_breakdown,
    build_cc_balances,
    build_neto,
    build_period_summary,
    build_savings_goals,
)


USER_TID = 999_999_999


def _ing(db, user_id, account_id, amount=1000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


# ── build_ahorro_breakdown RETIRAR path (lines 165-167) ──────────────────────

class TestBuildAhorroBDesglose:
    def test_retirar_subtracts_from_ahorro_breakdown(self, db, test_user, user_accounts):
        """source_name == 'Ahorro' → resta del breakdown (línea 166)."""
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        # GUARDAR: Efectivo → Ahorro
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 2), amount=1000.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            is_void=False,
        ))
        db.commit()

        # RETIRAR: Ahorro → Efectivo (source=Ahorro, target=Efectivo)
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 5), amount=300.0,
            source_account_id=user_accounts["ahorro"].id,
            target_account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_ahorro_breakdown(db, USER_TID)
        # Neto = 1000 - 300 = 700
        assert result["total"] == pytest.approx(700.0)

    def test_retirar_with_destination_amount(self, db, test_user, user_accounts):
        """RETIRAR con destination_amount → usa ese valor (no m.amount)."""
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 2), amount=1000.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            is_void=False,
        ))
        db.commit()

        # RETIRAR con destination_amount diferente a amount
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 5), amount=400.0,
            destination_amount=380.0,  # se usa este
            source_account_id=user_accounts["ahorro"].id,
            target_account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_ahorro_breakdown(db, USER_TID)
        assert result["total"] == pytest.approx(620.0)  # 1000 - 380


# ── build_period_summary EGR con categoría (lines 692-698) ───────────────────

class TestBuildPeriodSummaryEgr:
    def test_egr_counted_by_category(self, db, test_user, user_accounts, user_categories):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 3000.0)

        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 10), amount=450.0,
            source_account_id=user_accounts["efectivo"].id,
            category_id=user_categories["alimentacion"].id,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )

        assert result["egresos"] == pytest.approx(450.0)
        assert "Alimentación" in result["gastos_por_categoria"]
        assert result["gastos_por_categoria"]["Alimentación"] == pytest.approx(450.0)

    def test_egr_without_category_uses_sin_categoria(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 3000.0)

        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 10), amount=200.0,
            payment_method="cash", is_void=False,
        ))
        db.commit()

        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert "Sin categoría" in result["gastos_por_categoria"]

    def test_top_gastos_sorted_desc(self, db, test_user, user_accounts, user_categories):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        for amount in [100.0, 500.0, 300.0]:
            db.add(Movement(
                user_id=test_user.id, movement_type="EGR",
                movement_date=date(2026, 6, 10), amount=amount,
                category_id=user_categories["alimentacion"].id,
                payment_method="cash", is_void=False,
            ))
        db.commit()

        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert len(result["top_gastos"]) >= 1
        montos = [g["monto"] for g in result["top_gastos"]]
        assert montos == sorted(montos, reverse=True)


# ── build_savings_goals — RETIRAR (line 791) y else branch (792-794) ──────────

class TestBuildSavingsGoalsRetirar:
    def test_retirar_decreases_goal_balance(self, db, test_user, user_accounts):
        """target es cuenta líquida (no savings) → line 791: goal_totals -= amount."""
        goal = SavingsGoal(
            user_id=test_user.id,
            name="Fondo emergencia",
            target_amount=10000.0,
            is_active=True,
        )
        db.add(goal)
        db.commit()

        # GUARDAR: source=Efectivo, target=Ahorro (savings) → suma
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 1), amount=2000.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            savings_goal_id=goal.id,
            is_void=False,
        ))
        db.commit()

        # RETIRAR: source=Ahorro, target=Efectivo (liquid) → resta
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 5), amount=500.0,
            source_account_id=user_accounts["ahorro"].id,
            target_account_id=user_accounts["efectivo"].id,
            savings_goal_id=goal.id,
            is_void=False,
        ))
        db.commit()

        result = build_savings_goals(db, USER_TID)
        assert result[0]["current_amount"] == pytest.approx(1500.0)

    def test_movement_without_both_accounts_adds_amount(self, db, test_user, user_accounts):
        """source_account_id o target_account_id es None → else branch (line 793-794)."""
        goal = SavingsGoal(
            user_id=test_user.id,
            name="Meta simple",
            target_amount=5000.0,
            is_active=True,
        )
        db.add(goal)
        db.commit()

        # Movimiento con solo target_account_id (source=None) → else branch
        db.add(Movement(
            user_id=test_user.id, movement_type="ING",
            movement_date=date(2026, 6, 1), amount=300.0,
            source_account_id=None,
            target_account_id=user_accounts["efectivo"].id,
            savings_goal_id=goal.id,
            is_void=False,
        ))
        db.commit()

        result = build_savings_goals(db, USER_TID)
        assert result[0]["current_amount"] == pytest.approx(300.0)


# ── build_neto — compromiso_visacuotas futuro (lines 609, 624-628) ────────────

class TestBuildNetoFutureInstallments:
    def test_future_installments_as_compromiso(self, db, test_user, user_accounts):
        cc = Account(
            user_id=test_user.id, name="Visa CI",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ", billing_close_day=15, payment_due_day=25,
        )
        db.add(cc)
        db.commit()

        # Plan con 6 cuotas futuras (first_charge en el pasado, total > paid)
        plan = CreditCardInstallmentPlan(
            user_id=test_user.id,
            credit_card_account_id=cc.id,
            name="Laptop futuro",
            total_amount=6000.0,
            total_installments=6,
            monthly_amount=1000.0,
            purchase_date=date(2026, 1, 1),
            first_charge_date=date(2027, 1, 1),  # todo en el futuro
            status="active",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()

        result = build_neto(db, USER_TID, fallback_tc=7.7)
        # 6 cuotas × 1000 = 6000 de compromiso futuro
        assert result["compromiso_visacuotas"] == pytest.approx(6000.0)
        assert result["patrimonio_neto_ajustado"] == pytest.approx(
            result["patrimonio_neto"] - 6000.0
        )


# ── build_cc_balances — sin close_date (line 461-462) ────────────────────────

class TestBuildCcBalancesNoBillingClose:
    def test_no_billing_close_gives_none_pending(self, db, test_user):
        # TC sin billing_close_day → close_date será None → pending_to_pay_gtq=None
        cc = Account(
            user_id=test_user.id, name="TC Sin Corte",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ",
            billing_close_day=None,
            payment_due_day=None,
        )
        db.add(cc)
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "TC Sin Corte")
        assert item["balance_at_close_gtq"] is None
        assert item["pending_to_pay_gtq"] is None


# ── build_cc_balances — TC payment after close date (lines 365-370) ───────────

class TestBuildCcBalancesPaymentAfterClose:
    def test_payment_after_close_reduces_pending(self, db, test_user, user_accounts):
        cc = Account(
            user_id=test_user.id, name="Visa AfterClose",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ", billing_close_day=15, payment_due_day=25,
        )
        db.add(cc)
        db.commit()

        # Cargo dentro del corte (antes del 15 de junio)
        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 10), amount=500.0,
            credit_card_account_id=cc.id,
            payment_method="credit_card", is_void=False,
        ))
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 5000.0)

        # Pago después del corte (post-June 15)
        db.add(CreditCardPayment(
            credit_card_account_id=cc.id,
            user_id=test_user.id,
            amount=200.0,
            payment_date=date(2026, 6, 20),  # después del corte
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "Visa AfterClose")
        # pending = balance_at_close - payments_since_close = 500 - 200 = 300
        assert item["pending_to_pay_gtq"] == pytest.approx(300.0)
