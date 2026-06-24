"""Tests para transaction_service — create/void/update de movimientos."""
from datetime import date

import pytest

from app.db.models import Movement
from app.schemas.transactions import MovementCreateRequest
from app.services.transaction_service import (
    create_egreso,
    create_ingreso,
    update_movement,
    void_movement,
    get_account_or_raise,
    get_accounts_by_name,
    get_categories_by_name,
    parse_iso_date,
    require_liquid_account,
)


USER_TID = 999_999_999


# ── Helpers de schema ─────────────────────────────────────────────────────────

def _req(**kwargs) -> MovementCreateRequest:
    base = {
        "telegram_user_id": USER_TID,
        "movement_type": "ING",
        "movement_date": "2026-06-10",
        "amount": 500.0,
        "category_name": "Salario",
        "payment_method": "cash",
        "account_name": "Efectivo",
    }
    return MovementCreateRequest(**{**base, **kwargs})


# ── parse_iso_date ────────────────────────────────────────────────────────────

class TestParseIsoDate:
    def test_valid(self):
        assert parse_iso_date("2026-06-01") == date(2026, 6, 1)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_iso_date("bad-date")


# ── require_liquid_account ────────────────────────────────────────────────────

class TestRequireLiquidAccount:
    def test_non_liquid_raises(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="líquida"):
            require_liquid_account(user_accounts["ahorro"], "cuenta")  # savings, not liquid

    def test_liquid_passes(self, db, test_user, user_accounts):
        require_liquid_account(user_accounts["efectivo"], "cuenta")  # cash → OK


# ── create_ingreso ────────────────────────────────────────────────────────────

class TestCreateIngreso:
    def test_cash_ingreso_ok(self, db, test_user, user_accounts, user_categories):
        req = _req()
        mov = create_ingreso(db, req)
        db.commit()
        assert mov.id is not None
        assert mov.movement_type == "ING"
        assert mov.target_account_id == user_accounts["efectivo"].id

    def test_transfer_ingreso_ok(self, db, test_user, user_accounts, user_categories):
        req = _req(payment_method="transfer")
        mov = create_ingreso(db, req)
        db.commit()
        assert mov.transfer_account_id == user_accounts["efectivo"].id
        assert mov.target_account_id is None

    def test_invalid_category_raises(self, db, test_user, user_accounts, user_categories):
        with pytest.raises(ValueError, match="Categoría ING no existe"):
            create_ingreso(db, _req(category_name="NoExiste"))

    def test_invalid_payment_method_raises(self, db, test_user, user_accounts, user_categories):
        # credit_card no es válido para ING; pasamos credit_card_account_id para satisfacer el schema
        with pytest.raises(ValueError, match="payment_method"):
            create_ingreso(db, _req(payment_method="credit_card", credit_card_account_id=1))

    def test_invalid_account_raises(self, db, test_user, user_accounts, user_categories):
        with pytest.raises(ValueError, match="account_name no existe"):
            create_ingreso(db, _req(account_name="CuentaFalsa"))

    def test_non_liquid_account_raises(self, db, test_user, user_accounts, user_categories):
        with pytest.raises(ValueError, match="líquida"):
            create_ingreso(db, _req(account_name="Ahorro"))


# ── create_egreso ─────────────────────────────────────────────────────────────

def _fund_efectivo(db, test_user, user_accounts, amount=1000.0):
    """Insertar ING directamente para tener saldo en Efectivo."""
    m = Movement(
        user_id=test_user.id,
        movement_type="ING",
        movement_date=date(2026, 6, 1),
        amount=amount,
        target_account_id=user_accounts["efectivo"].id,
        payment_method="cash",
        is_void=False,
    )
    db.add(m)
    db.commit()


class TestCreateEgreso:
    def test_cash_egreso_ok(self, db, test_user, user_accounts, user_categories):
        _fund_efectivo(db, test_user, user_accounts)
        req = _req(movement_type="EGR", category_name="Alimentación", amount=200.0)
        mov = create_egreso(db, req)
        db.commit()
        assert mov.movement_type == "EGR"
        assert mov.source_account_id == user_accounts["efectivo"].id

    def test_insufficient_balance_raises(self, db, test_user, user_accounts, user_categories):
        # Efectivo vacío
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            create_egreso(db, _req(movement_type="EGR", category_name="Alimentación", amount=100.0))

    def test_invalid_category_raises(self, db, test_user, user_accounts, user_categories):
        _fund_efectivo(db, test_user, user_accounts)
        with pytest.raises(ValueError, match="Categoría EGR no existe"):
            create_egreso(db, _req(movement_type="EGR", category_name="NoExiste", amount=50.0))

    def test_credit_card_egreso_ok(self, db, test_user, user_accounts, user_categories):
        from app.db.models import Account
        cc = Account(
            user_id=test_user.id, name="Visa",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=5,
        )
        db.add(cc)
        db.commit()

        req = _req(
            movement_type="EGR",
            category_name="Alimentación",
            amount=300.0,
            payment_method="credit_card",
            credit_card_account_id=cc.id,
            account_name=None,
        )
        mov = create_egreso(db, req)
        db.commit()
        assert mov.credit_card_account_id == cc.id
        assert mov.payment_method == "credit_card"

    def test_credit_card_not_found_raises(self, db, test_user, user_accounts, user_categories):
        req = _req(
            movement_type="EGR",
            category_name="Alimentación",
            amount=100.0,
            payment_method="credit_card",
            credit_card_account_id=99999,
            account_name=None,
        )
        with pytest.raises(ValueError, match="Tarjeta de crédito no encontrada"):
            create_egreso(db, req)


# ── void_movement ─────────────────────────────────────────────────────────────

class TestVoidMovement:
    def _make_ing(self, db, test_user, user_accounts, user_categories):
        req = _req()
        mov = create_ingreso(db, req)
        db.commit()
        return mov

    def test_void_ok(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        result = void_movement(db, USER_TID, mov.id, reason="Error")
        assert result.is_void is True
        assert result.void_reason == "Error"

    def test_already_voided_raises(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        void_movement(db, USER_TID, mov.id, reason="Primera vez")
        with pytest.raises(ValueError, match="ya está anulado"):
            void_movement(db, USER_TID, mov.id, reason="Segunda vez")

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Movimiento no encontrado"):
            void_movement(db, USER_TID, 99999)


# ── update_movement ───────────────────────────────────────────────────────────

class TestUpdateMovement:
    def _make_ing(self, db, test_user, user_accounts, user_categories):
        req = _req()
        mov = create_ingreso(db, req)
        db.commit()
        return mov

    def test_update_note(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        updated = update_movement(db, USER_TID, mov.id, note="Nueva nota")
        assert updated.note == "Nueva nota"

    def test_update_amount(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        updated = update_movement(db, USER_TID, mov.id, amount=999.0)
        assert float(updated.amount) == 999.0

    def test_update_date(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        updated = update_movement(db, USER_TID, mov.id, movement_date="2026-05-01")
        assert updated.movement_date == date(2026, 5, 1)

    def test_voided_movement_cannot_be_updated(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        void_movement(db, USER_TID, mov.id)
        with pytest.raises(ValueError, match="anulado"):
            update_movement(db, USER_TID, mov.id, note="Intento fallido")

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Movimiento no encontrado"):
            update_movement(db, USER_TID, 99999)

    def test_update_category(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        # Salario → Salario (misma categoría, debería funcionar igual)
        updated = update_movement(db, USER_TID, mov.id, category_name="Salario")
        assert updated.category_id == user_categories["salario"].id
