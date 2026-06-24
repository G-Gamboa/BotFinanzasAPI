"""Tests para finance_db_service — paths complejos:
build_saldos_map (loans/debt_payments/cc_payments), build_savings_goals,
build_period_summary con DebtPayment, build_cc_balances USD/MIXTO, build_dashboard.
"""
from datetime import date, datetime, timezone

import pytest

from app.db.models import (
    Account, CreditCardInstallmentPlan, CreditCardPayment, Debt, DebtPayment,
    Loan, LoanPayment, LoanPerson, Movement, SavingsGoal,
)
from app.services.finance_db_service import (
    build_cc_balances,
    build_dashboard,
    build_networth,
    build_period_summary,
    build_savings_goals,
    build_saldos_map,
)
from app.services.debt_service import create_debt, pay_debt


USER_TID = 999_999_999


# ── helpers ───────────────────────────────────────────────────────────────────

def _ing(db, user_id, account_id, amount=1000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


# ── build_saldos_map — Loan paths (lines 93-136) ─────────────────────────────

class TestBuildSaldosMapLoans:
    def test_loan_decreases_liquid_increases_prestamos(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Luis", is_active=True)
        db.add(person)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=500.0,
            loan_date=date(2026, 6, 10),
            status="active",
            source_account_id=user_accounts["efectivo"].id,
        )
        db.add(loan)
        db.commit()

        saldos = build_saldos_map(db, USER_TID)
        assert saldos.get("Efectivo", 0) == pytest.approx(1500.0)
        assert saldos.get("Prestamos", 0) == pytest.approx(500.0)

    def test_loan_payment_reduces_prestamos(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Carlos", is_active=True)
        db.add(person)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=800.0,
            loan_date=date(2026, 6, 10),
            status="active",
            source_account_id=user_accounts["efectivo"].id,
        )
        db.add(loan)
        db.flush()

        payment = LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=300.0,
            payment_date=date(2026, 6, 15),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        )
        db.add(payment)
        db.commit()

        saldos = build_saldos_map(db, USER_TID)
        assert saldos.get("Prestamos", 0) == pytest.approx(500.0)

    def test_debt_payment_decreases_liquid(self, db, test_user, user_accounts):
        debt = create_debt(
            db, USER_TID,
            name="Crédito",
            creditor="Banco",
            due_date="2026-12-31",
            installment_amount=400.0,
            total_installments=3,
            paid_installments=0,
        )
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        pay_debt(db, USER_TID, debt.id, "2026-06-10", "cash", "Efectivo")

        saldos = build_saldos_map(db, USER_TID)
        assert saldos.get("Efectivo", 0) == pytest.approx(1600.0)

    def test_cc_payment_decreases_liquid(self, db, test_user, user_accounts):
        cc = Account(
            user_id=test_user.id, name="Visa GTQ",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ", billing_close_day=15, payment_due_day=25,
        )
        db.add(cc)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        cp = CreditCardPayment(
            credit_card_account_id=cc.id,
            user_id=test_user.id,
            amount=600.0,
            payment_date=date(2026, 6, 10),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        )
        db.add(cp)
        db.commit()

        saldos = build_saldos_map(db, USER_TID)
        assert saldos.get("Efectivo", 0) == pytest.approx(1400.0)

    def test_mov_with_loan_person_skipped(self, db, test_user, user_accounts):
        """MOV rows with loan_person_id should be skipped in saldos calc (line 83-84)."""
        person = LoanPerson(user_id=test_user.id, name="Ana", is_active=True)
        db.add(person)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 1000.0)

        # MOV con loan_person_id → debe ser ignorado
        mov = Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 5), amount=200.0,
            loan_person_id=person.id,
            is_void=False,
        )
        db.add(mov)
        db.commit()

        saldos = build_saldos_map(db, USER_TID)
        # Efectivo sigue en 1000 porque el MOV con loan_person se ignora
        assert saldos.get("Efectivo", 0) == pytest.approx(1000.0)


# ── build_savings_goals (lines 766-806) ───────────────────────────────────────

class TestBuildSavingsGoals:
    def test_empty_returns_empty_list(self, db, test_user):
        assert build_savings_goals(db, USER_TID) == []

    def test_returns_goal_with_zero_balance(self, db, test_user):
        goal = SavingsGoal(
            user_id=test_user.id,
            name="Vacaciones",
            target_amount=5000.0,
            is_active=True,
        )
        db.add(goal)
        db.commit()

        result = build_savings_goals(db, USER_TID)
        assert len(result) == 1
        assert result[0]["name"] == "Vacaciones"
        assert result[0]["current_amount"] == 0.0

    def test_guardar_increases_goal_balance(self, db, test_user, user_accounts):
        goal = SavingsGoal(
            user_id=test_user.id,
            name="Carro",
            target_amount=50000.0,
            account_name="Efectivo",
            is_active=True,
        )
        db.add(goal)
        db.commit()

        # GUARDAR: target = Ahorro, source = Efectivo, savings_goal_id = goal.id
        mov = Movement(
            user_id=test_user.id,
            movement_type="MOV",
            movement_date=date(2026, 6, 1),
            amount=1000.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            savings_goal_id=goal.id,
            is_void=False,
        )
        db.add(mov)
        db.commit()

        result = build_savings_goals(db, USER_TID)
        assert result[0]["current_amount"] == pytest.approx(1000.0)

    def test_inactive_goal_excluded(self, db, test_user):
        goal = SavingsGoal(
            user_id=test_user.id,
            name="Inactiva",
            target_amount=1000.0,
            is_active=False,
        )
        db.add(goal)
        db.commit()

        assert build_savings_goals(db, USER_TID) == []


# ── build_period_summary con DebtPayment (lines 706-738) ─────────────────────

class TestBuildPeriodSummaryDebtPayment:
    def test_debt_payment_counted_as_egreso(self, db, test_user, user_accounts):
        debt = create_debt(
            db, USER_TID,
            name="Teléfono",
            creditor="Operadora",
            due_date="2026-06-20",
            installment_amount=350.0,
            total_installments=3,
            paid_installments=0,
        )
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        pay_debt(db, USER_TID, debt.id, "2026-06-15", "cash", "Efectivo")

        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )

        assert result["egresos"] == pytest.approx(350.0)
        assert any("Teléfono" in k for k in result["gastos_por_categoria"])

    def test_debt_payment_outside_range_excluded(self, db, test_user, user_accounts):
        debt = create_debt(
            db, USER_TID,
            name="Cable",
            creditor="X",
            due_date="2026-05-15",
            installment_amount=200.0,
            total_installments=3,
            paid_installments=0,
        )
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        pay_debt(db, USER_TID, debt.id, "2026-05-10", "cash", "Efectivo")

        result = build_period_summary(
            db, USER_TID, "mes",
            date(2026, 6, 1), date(2026, 6, 30),
        )
        assert result["egresos"] == 0.0


# ── build_cc_balances – USD y MIXTO TC (lines 291-326, 414-455) ───────────────

@pytest.fixture
def cc_usd(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Visa USD",
        account_type="credit_card", currency="USD",
        is_active=True, is_system=False, sort_order=11,
        tc_type="USD", billing_close_day=15, payment_due_day=25,
        tc_exchange_rate=7.8,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def cc_mixto(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Visa Mixta",
        account_type="credit_card", currency="GTQ",
        is_active=True, is_system=False, sort_order=12,
        tc_type="MIXTO", billing_close_day=15, payment_due_day=25,
        tc_exchange_rate=7.8,
    )
    db.add(acc)
    db.commit()
    return acc


class TestBuildCcBalancesUSD:
    def test_usd_charge_in_dollars(self, db, test_user, cc_usd, user_categories):
        db.add(Movement(
            user_id=test_user.id,
            movement_type="EGR",
            movement_date=date(2026, 6, 1),
            amount=100.0,  # $100 USD
            credit_card_account_id=cc_usd.id,
            payment_method="credit_card",
            is_void=False,
        ))
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "Visa USD")
        assert item["tc_type"] == "USD"
        assert item["balance"] == pytest.approx(100.0)
        assert item["balance_gtq"] == pytest.approx(100.0 * 7.8)

    def test_usd_payment_reduces_balance(self, db, test_user, cc_usd, user_accounts, user_categories):
        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 1), amount=200.0,
            credit_card_account_id=cc_usd.id,
            payment_method="credit_card", is_void=False,
        ))
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 5000.0)
        db.add(CreditCardPayment(
            credit_card_account_id=cc_usd.id,
            user_id=test_user.id,
            amount=700.0,    # Q gastados
            amount_usd=100.0,  # $100 pagados → reducen saldo $
            payment_date=date(2026, 6, 10),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "Visa USD")
        # 200 - 100 = $100 restantes
        assert item["balance"] == pytest.approx(100.0)


class TestBuildCcBalancesMixto:
    def test_mixto_gtq_charge(self, db, test_user, cc_mixto, user_categories):
        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 1), amount=300.0,
            credit_card_account_id=cc_mixto.id,
            payment_method="credit_card", is_void=False,
            # amount_foreign=None → cargo en Q
        ))
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "Visa Mixta")
        assert item["tc_type"] == "MIXTO"
        assert item["balance_gtq"] == pytest.approx(300.0)

    def test_mixto_usd_charge_uses_amount_foreign(self, db, test_user, cc_mixto, user_categories):
        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 6, 1),
            amount=390.0,       # equivalente Q (para la TC)
            amount_foreign=50.0,  # $50 reales → acumulan en saldo USD
            credit_card_account_id=cc_mixto.id,
            payment_method="credit_card", is_void=False,
        ))
        db.commit()

        result = build_cc_balances(db, USER_TID)
        item = next(r for r in result if r["name"] == "Visa Mixta")
        # Solo el saldo USD contribuye: 50 * 7.8 = 390 GTQ
        assert item["balance_gtq"] == pytest.approx(50.0 * 7.8)


# ── build_networth con inversiones y préstamos (lines 510-537) ────────────────

class TestBuildNetworthInvestments:
    def test_investment_in_networth(self, db, test_user, user_accounts):
        inv = Account(
            user_id=test_user.id, name="Coinbase",
            account_type="investment", currency="USD",
            is_active=True, is_system=False, sort_order=6,
        )
        db.add(inv)
        db.commit()

        _ing(db, test_user.id, inv.id, 200.0)  # $200 inversión

        result = build_networth(db, USER_TID, fallback_tc=7.7)
        assert result["inv_total_usd"] == pytest.approx(200.0)

    def test_loan_in_networth(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Raul", is_active=True)
        db.add(person)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 3000.0)

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=1000.0,
            loan_date=date(2026, 6, 5),
            status="active",
            source_account_id=user_accounts["efectivo"].id,
        )
        db.add(loan)

        lpay = LoanPayment(
            loan_id=None,  # se asigna tras flush
            user_id=test_user.id,
            amount=400.0,
            payment_date=date(2026, 6, 12),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        )
        db.add(loan)
        db.flush()
        lpay.loan_id = loan.id
        db.add(lpay)
        db.commit()

        result = build_networth(db, USER_TID, fallback_tc=7.7)
        # Prestamos = 1000 - 400 = 600
        assert result["prestamos_gtq"] == pytest.approx(600.0)


# ── build_dashboard (lines 810-828) ──────────────────────────────────────────

class TestBuildDashboard:
    def test_returns_all_keys(self, db, test_user, user_accounts):
        result = build_dashboard(db, USER_TID, fallback_tc=7.7)
        for key in ("networth", "neto", "resumen_dia", "resumen_semana",
                    "resumen_mes", "prestamos_resumen", "savings_goals"):
            assert key in result

    def test_resumen_dia_is_valid_period(self, db, test_user, user_accounts):
        result = build_dashboard(db, USER_TID, fallback_tc=7.7)
        dia = result["resumen_dia"]
        assert dia["periodo"] == "dia"
        assert "ingresos" in dia
        assert "egresos" in dia

    def test_savings_goals_in_dashboard(self, db, test_user, user_accounts):
        goal = SavingsGoal(
            user_id=test_user.id, name="Dashboard Goal",
            target_amount=1000.0, is_active=True,
        )
        db.add(goal)
        db.commit()

        result = build_dashboard(db, USER_TID, fallback_tc=7.7)
        names = [g["name"] for g in result["savings_goals"]]
        assert "Dashboard Goal" in names
