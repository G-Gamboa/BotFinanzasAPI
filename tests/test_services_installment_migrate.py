"""Tests para installment_service.migrate_debt_to_tc (lines 348-450)."""
from datetime import date

import pytest

from app.db.models import Account, Debt, Movement
from app.schemas.installment_plans import MigrateDebtRequest
from app.services.installment_service import migrate_debt_to_tc
from app.services.debt_service import create_debt


USER_TID = 999_999_999


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_debt(db, test_user, total=6, paid=2, amount=500.0, status="active"):
    debt = create_debt(
        db, USER_TID,
        name="Préstamo carro",
        creditor="Banco Agrícola",
        due_date="2026-12-15",
        installment_amount=amount,
        total_installments=total,
        paid_installments=paid,
    )
    if status != "active":
        debt.status = status
        db.commit()
    return debt


def _req(cc_id, debt_id, migration_type="normal", first_charge_date=None):
    return MigrateDebtRequest(
        telegram_user_id=USER_TID,
        debt_id=debt_id,
        credit_card_account_id=cc_id,
        migration_type=migration_type,
        first_charge_date=first_charge_date,
    )


@pytest.fixture
def cc(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Visa BI",
        account_type="credit_card", currency="GTQ",
        is_active=True, is_system=False, sort_order=10,
        tc_type="GTQ", billing_close_day=20, payment_due_day=28,
    )
    db.add(acc)
    db.commit()
    return acc


# ── migrate_debt_to_tc – normal ───────────────────────────────────────────────

class TestMigrateNormal:
    def test_success_creates_egr_movement(self, db, test_user, cc, user_categories):
        debt = _make_debt(db, test_user, total=6, paid=2)  # 4 cuotas pendientes
        result = migrate_debt_to_tc(db, _req(cc.id, debt.id, "normal"))

        assert result["ok"] is True
        assert result["pending_installments"] == 4
        assert result["remaining_amount"] == pytest.approx(4 * 500.0)

    def test_normal_closes_debt(self, db, test_user, cc, user_categories):
        debt = _make_debt(db, test_user, total=3, paid=1)
        migrate_debt_to_tc(db, _req(cc.id, debt.id, "normal"))

        db.refresh(debt)
        assert debt.status == "paid"
        assert debt.paid_installments == debt.total_installments

    def test_normal_creates_movement_in_db(self, db, test_user, cc, user_categories):
        debt = _make_debt(db, test_user, total=3, paid=0)
        migrate_debt_to_tc(db, _req(cc.id, debt.id, "normal"))

        from sqlalchemy import select
        mov = db.scalar(
            select(Movement).where(
                Movement.credit_card_account_id == cc.id,
                Movement.movement_type == "EGR",
            )
        )
        assert mov is not None
        assert float(mov.amount) == pytest.approx(3 * 500.0)


# ── migrate_debt_to_tc – visacuota ────────────────────────────────────────────

class TestMigrateVisacuota:
    def test_success_creates_installment_plan(self, db, test_user, cc):
        debt = _make_debt(db, test_user, total=6, paid=2)
        result = migrate_debt_to_tc(db, _req(
            cc.id, debt.id,
            migration_type="visacuota",
            first_charge_date="2026-07-20",
        ))

        assert result["ok"] is True
        assert result["pending_installments"] == 4

    def test_visacuota_closes_debt(self, db, test_user, cc):
        debt = _make_debt(db, test_user, total=4, paid=1)
        migrate_debt_to_tc(db, _req(
            cc.id, debt.id,
            migration_type="visacuota",
            first_charge_date="2026-07-20",
        ))

        db.refresh(debt)
        assert debt.status == "paid"

    def test_visacuota_without_first_charge_date_raises(self, db, test_user, cc):
        debt = _make_debt(db, test_user)
        with pytest.raises(ValueError, match="first_charge_date"):
            migrate_debt_to_tc(db, _req(cc.id, debt.id, "visacuota"))


# ── error paths ───────────────────────────────────────────────────────────────

class TestMigrateErrors:
    def test_debt_not_found_raises(self, db, test_user, cc):
        with pytest.raises(ValueError, match="Deuda no encontrada"):
            migrate_debt_to_tc(db, _req(cc.id, 99999))

    def test_inactive_debt_raises(self, db, test_user, cc):
        debt = _make_debt(db, test_user, total=3, paid=3)  # status=paid automático
        with pytest.raises(ValueError, match="no está activa"):
            migrate_debt_to_tc(db, _req(cc.id, debt.id))

    def test_cc_not_found_raises(self, db, test_user):
        debt = _make_debt(db, test_user)
        with pytest.raises(ValueError, match="Tarjeta de crédito no encontrada"):
            migrate_debt_to_tc(db, _req(99999, debt.id))

    def test_no_pending_installments_raises(self, db, test_user, cc):
        # total=3, paid=3 → status=paid pero queremos probar la ruta de "0 cuotas pendientes"
        # con status=active forzado
        from app.db.models import Debt as DebtModel
        debt = _make_debt(db, test_user, total=3, paid=2)
        # Forzar que quede con 1 cuota pendiente pero pagada = 3 (sin alterar status)
        debt.paid_installments = 3
        debt.status = "active"  # forza active para llegar a la validación
        db.commit()
        with pytest.raises(ValueError, match="no tiene cuotas pendientes"):
            migrate_debt_to_tc(db, _req(cc.id, debt.id))

    def test_invalid_migration_type_raises(self, db, test_user, cc):
        debt = _make_debt(db, test_user)
        with pytest.raises(ValueError, match="migration_type inválido"):
            migrate_debt_to_tc(db, _req(cc.id, debt.id, migration_type="otro"))
