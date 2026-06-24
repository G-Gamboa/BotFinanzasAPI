"""Tests para installment_service — CRUD de planes de cuotas y process_pending_charges."""
from datetime import date, datetime, timezone

import pytest

from app.db.models import Account, Category, CreditCardInstallmentPlan, Movement
from app.schemas.installment_plans import InstallmentPlanCreateRequest
from app.services.installment_service import (
    _add_months,
    _count_paid,
    _find_egr_category,
    _parse_date,
    _plan_to_dict,
    create_installment_plan,
    delete_installment_plan,
    list_installment_plans,
    process_pending_charges,
    update_installment_plan,
)


USER_TID = 999_999_999


# ── Pure helpers ──────────────────────────────────────────────────────────────

class TestAddMonths:
    def test_simple(self):
        assert _add_months(date(2026, 3, 1), 1) == date(2026, 4, 1)

    def test_year_wrap(self):
        assert _add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)

    def test_clamps_feb(self):
        assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


class TestParseDate:
    def test_valid(self):
        assert _parse_date("2026-06-01") == date(2026, 6, 1)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _parse_date("01/06/2026")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cc(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Visa CC",
        account_type="credit_card", currency="GTQ",
        is_active=True, is_system=False, sort_order=10,
        tc_type="GTQ",
    )
    db.add(acc)
    db.commit()
    return acc


def _plan_req(cc_id, **kwargs):
    base = {
        "telegram_user_id": USER_TID,
        "credit_card_account_id": cc_id,
        "name": "MacBook",
        "total_amount": 12000.0,
        "total_installments": 12,
        "monthly_amount": 1000.0,
        "purchase_date": "2026-01-01",
        "first_charge_date": "2026-02-01",
        "note": None,
    }
    return InstallmentPlanCreateRequest(**{**base, **kwargs})


# ── _count_paid ───────────────────────────────────────────────────────────────

class TestCountPaid:
    def test_zero_when_no_movements(self, db, test_user, cc):
        plan = CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Test", total_amount=1000.0, total_installments=3,
            monthly_amount=333.33, purchase_date=date(2026, 1, 1),
            first_charge_date=date(2026, 2, 1), status="active", is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()
        assert _count_paid(db, plan.id) == 0

    def test_counts_only_non_void(self, db, test_user, cc):
        plan = CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Test", total_amount=1000.0, total_installments=3,
            monthly_amount=333.33, purchase_date=date(2026, 1, 1),
            first_charge_date=date(2026, 2, 1), status="active", is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.flush()

        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 2, 1), amount=333.33,
            payment_method="credit_card", credit_card_account_id=cc.id,
            installment_plan_id=plan.id, is_void=False,
        ))
        db.add(Movement(
            user_id=test_user.id, movement_type="EGR",
            movement_date=date(2026, 3, 1), amount=333.33,
            payment_method="credit_card", credit_card_account_id=cc.id,
            installment_plan_id=plan.id, is_void=True,  # anulado → no cuenta
        ))
        db.commit()
        assert _count_paid(db, plan.id) == 1


# ── _find_egr_category ────────────────────────────────────────────────────────

class TestFindEgrCategory:
    def test_returns_preferred_name(self, db, test_user, user_categories):
        # "Alimentación" no está en preferred_names, así que devuelve la primera disponible
        result = _find_egr_category(db, test_user.id)
        assert result is not None
        assert result.kind == "EGR"

    def test_none_when_no_egr_categories(self, db, test_user):
        result = _find_egr_category(db, test_user.id)
        assert result is None  # sin categorías EGR activas


# ── list_installment_plans ────────────────────────────────────────────────────

class TestListInstallmentPlans:
    def test_empty_list(self, db, test_user):
        assert list_installment_plans(db, USER_TID) == []

    def test_returns_active_plans(self, db, test_user, cc):
        db.add(CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Laptop", total_amount=5000.0, total_installments=5,
            monthly_amount=1000.0, purchase_date=date(2026, 1, 1),
            first_charge_date=date(2026, 2, 1), status="active", is_active=True,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
        result = list_installment_plans(db, USER_TID)
        assert len(result) == 1
        assert result[0]["name"] == "Laptop"

    def test_inactive_plan_excluded(self, db, test_user, cc):
        db.add(CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Cancelado", total_amount=1000.0, total_installments=3,
            monthly_amount=333.0, purchase_date=date(2026, 1, 1),
            first_charge_date=date(2026, 2, 1), status="cancelled", is_active=False,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
        assert list_installment_plans(db, USER_TID) == []


# ── create_installment_plan ───────────────────────────────────────────────────

class TestCreateInstallmentPlan:
    def test_creates_ok(self, db, test_user, cc):
        plan = create_installment_plan(db, _plan_req(cc.id))
        assert plan.id is not None
        assert plan.name == "MacBook"
        assert plan.status == "active"
        assert plan.is_active is True

    def test_cc_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Tarjeta de crédito no encontrada"):
            create_installment_plan(db, _plan_req(99999))

    def test_first_charge_before_purchase_raises(self, db, test_user, cc):
        with pytest.raises(ValueError, match="first_charge_date"):
            create_installment_plan(db, _plan_req(
                cc.id,
                purchase_date="2026-06-01",
                first_charge_date="2026-05-01",  # antes de purchase
            ))


# ── update_installment_plan ───────────────────────────────────────────────────

class TestUpdateInstallmentPlan:
    def test_updates_name_and_note(self, db, test_user, cc):
        plan = create_installment_plan(db, _plan_req(cc.id))
        updated = update_installment_plan(db, plan.id, USER_TID, "iPhone", "nota nueva")
        assert updated.name == "iPhone"
        assert updated.note == "nota nueva"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Plan de cuotas no encontrado"):
            update_installment_plan(db, 99999, USER_TID, "x", None)


# ── delete_installment_plan ───────────────────────────────────────────────────

class TestDeleteInstallmentPlan:
    def test_marks_cancelled(self, db, test_user, cc):
        plan = create_installment_plan(db, _plan_req(cc.id))
        deleted = delete_installment_plan(db, plan.id, USER_TID)
        assert deleted.is_active is False
        assert deleted.status == "cancelled"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Plan de cuotas no encontrado"):
            delete_installment_plan(db, 99999, USER_TID)


# ── process_pending_charges ───────────────────────────────────────────────────

class TestProcessPendingCharges:
    def test_no_plans_returns_empty(self, db, test_user):
        assert process_pending_charges(db, USER_TID) == []

    def test_generates_overdue_charges(self, db, test_user, cc, user_categories):
        # Plan con first_charge_date en el pasado → debe generar cuotas
        past_date = date(2026, 1, 1)
        plan = CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Tablet", total_amount=3000.0, total_installments=3,
            monthly_amount=1000.0, purchase_date=past_date,
            first_charge_date=past_date,  # hace 6 meses → 3 cuotas vencidas
            status="active", is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()

        created = process_pending_charges(db, USER_TID)
        assert len(created) == 3  # las 3 cuotas deben generarse

    def test_no_duplicate_charges(self, db, test_user, cc, user_categories):
        past_date = date(2026, 1, 1)
        plan = CreditCardInstallmentPlan(
            user_id=test_user.id, credit_card_account_id=cc.id,
            name="Tablet2", total_amount=3000.0, total_installments=3,
            monthly_amount=1000.0, purchase_date=past_date,
            first_charge_date=past_date,
            status="active", is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()

        process_pending_charges(db, USER_TID)
        # Segunda llamada no debe generar duplicados
        second = process_pending_charges(db, USER_TID)
        assert second == []
