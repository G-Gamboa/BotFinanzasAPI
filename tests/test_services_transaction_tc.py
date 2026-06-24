"""Tests para transaction_service — TC payments, update_movement edge cases,
void_movement wrong user, build_ahorro RETIRAR path, build_loan second payment."""
from datetime import date, datetime, timezone

import pytest

from app.db.models import Account, CreditCardPayment, Movement, User, LoanPerson, SavingsGoal
from app.schemas.transactions import CreditCardPaymentRequest, MovementCreateRequest
from app.services.transaction_service import (
    create_egreso,
    create_ingreso,
    create_movimiento,
    create_tc_payment,
    void_movement,
    void_tc_payment,
    update_movement,
)


USER_TID = 999_999_999


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ing_req(**kwargs):
    base = {
        "telegram_user_id": USER_TID,
        "movement_type": "ING",
        "movement_date": "2026-06-10",
        "amount": 1000.0,
        "category_name": "Salario",
        "payment_method": "cash",
        "account_name": "Efectivo",
    }
    return MovementCreateRequest(**{**base, **kwargs})


def _tc_req(**kwargs):
    base = {
        "telegram_user_id": USER_TID,
        "credit_card_account_id": None,  # overridden per test
        "amount": 500.0,
        "payment_date": "2026-06-10",
        "account_name": "Efectivo",
    }
    return CreditCardPaymentRequest(**{**base, **kwargs})


def _fund(db, user_id, account_id, amount=2000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


@pytest.fixture
def inv_account2(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Crypto",
        account_type="investment", currency="USD",
        is_active=True, is_system=False, sort_order=5,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def inv_account(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Binance",
        account_type="investment", currency="USD",
        is_active=True, is_system=False, sort_order=4,
    )
    db.add(acc)
    db.commit()
    return acc


# ── create_tc_payment ─────────────────────────────────────────────────────────

class TestCreateTcPayment:
    def test_success(self, db, test_user, user_accounts, cc_account, user_categories):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        req = _tc_req(credit_card_account_id=cc_account.id)
        payment = create_tc_payment(db, req)
        assert payment.id is not None
        assert float(payment.amount) == pytest.approx(500.0)
        assert payment.credit_card_account_id == cc_account.id
        assert payment.is_void is False

    def test_cc_not_found_raises(self, db, test_user, user_accounts, user_categories):
        req = _tc_req(credit_card_account_id=99999)
        with pytest.raises(ValueError, match="Tarjeta de crédito no encontrada"):
            create_tc_payment(db, req)

    def test_liquid_account_not_found_raises(self, db, test_user, user_accounts, cc_account):
        req = _tc_req(credit_card_account_id=cc_account.id, account_name="NoExiste")
        with pytest.raises(ValueError, match="account_name no existe"):
            create_tc_payment(db, req)

    def test_insufficient_balance_raises(self, db, test_user, user_accounts, cc_account):
        # Efectivo vacío
        req = _tc_req(credit_card_account_id=cc_account.id, amount=1000.0)
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            create_tc_payment(db, req)

    def test_amount_usd_stored(self, db, test_user, user_accounts, cc_account):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 5000.0)
        req = _tc_req(credit_card_account_id=cc_account.id, amount=770.0, amount_usd=100.0)
        payment = create_tc_payment(db, req)
        assert float(payment.amount_usd) == pytest.approx(100.0)


# ── void_tc_payment ───────────────────────────────────────────────────────────

class TestVoidTcPayment:
    def _make_payment(self, db, test_user, cc_account, user_accounts):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        req = _tc_req(credit_card_account_id=cc_account.id, amount=300.0)
        return create_tc_payment(db, req)

    def test_success(self, db, test_user, user_accounts, cc_account):
        payment = self._make_payment(db, test_user, cc_account, user_accounts)
        voided = void_tc_payment(db, USER_TID, payment.id)
        assert voided.is_void is True
        assert voided.voided_at is not None

    def test_with_reason(self, db, test_user, user_accounts, cc_account):
        payment = self._make_payment(db, test_user, cc_account, user_accounts)
        voided = void_tc_payment(db, USER_TID, payment.id, reason="Error de captura")
        assert voided.void_reason == "Error de captura"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Abono no encontrado"):
            void_tc_payment(db, USER_TID, 99999)

    def test_already_voided_raises(self, db, test_user, user_accounts, cc_account):
        payment = self._make_payment(db, test_user, cc_account, user_accounts)
        void_tc_payment(db, USER_TID, payment.id)
        with pytest.raises(ValueError, match="ya está anulado"):
            void_tc_payment(db, USER_TID, payment.id)

    def test_wrong_user_raises(self, db, test_user, user_accounts, cc_account):
        payment = self._make_payment(db, test_user, cc_account, user_accounts)
        # Segundo usuario
        other_user = User(
            telegram_user_id=888_888_888,
            first_name="Other", last_name="User",
            is_active=True, can_use_loans=False, theme_key="neutral",
        )
        db.add(other_user)
        db.commit()
        with pytest.raises(ValueError, match="No tienes permiso"):
            void_tc_payment(db, 888_888_888, payment.id)


# ── void_movement wrong user ──────────────────────────────────────────────────

class TestVoidMovementWrongUser:
    def test_wrong_user_raises(self, db, test_user, user_accounts, user_categories):
        # Crear movimiento de test_user
        mov = create_ingreso(db, _ing_req())
        db.commit()

        other = User(
            telegram_user_id=777_777_777,
            first_name="Other", last_name="User",
            is_active=True, can_use_loans=False, theme_key="neutral",
        )
        db.add(other)
        db.commit()

        with pytest.raises(ValueError, match="No tienes permiso"):
            void_movement(db, 777_777_777, mov.id)


# ── update_movement edge cases ────────────────────────────────────────────────

class TestUpdateMovementEdgeCases:
    def _make_ing(self, db, test_user, user_accounts, user_categories):
        mov = create_ingreso(db, _ing_req())
        db.commit()
        return mov

    def test_category_not_found_raises(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        with pytest.raises(ValueError, match="Categoría ING no existe"):
            update_movement(db, USER_TID, mov.id, category_name="NoExiste")

    def test_invalid_payment_method_raises(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        with pytest.raises(ValueError, match="payment_method inválido"):
            update_movement(db, USER_TID, mov.id, payment_method="venmo")

    def test_cc_account_not_found_on_update(self, db, test_user, user_accounts, user_categories):
        # Primero cambiar payment_method a credit_card en el movimiento
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        mov.payment_method = "credit_card"
        db.commit()
        with pytest.raises(ValueError, match="Tarjeta de crédito no encontrada"):
            update_movement(db, USER_TID, mov.id, credit_card_account_id=99999)

    def test_update_note_ok(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        updated = update_movement(db, USER_TID, mov.id, note="nueva nota")
        assert updated.note == "nueva nota"

    def test_update_amount_ok(self, db, test_user, user_accounts, user_categories):
        mov = self._make_ing(db, test_user, user_accounts, user_categories)
        updated = update_movement(db, USER_TID, mov.id, amount=999.0)
        assert float(updated.amount) == pytest.approx(999.0)


# ── require_investment_account error ─────────────────────────────────────────

class TestRequireInvestmentAccount:
    def test_retirar_inv_with_cash_source_raises(self, db, test_user, user_accounts):
        """RETIRAR_INV con cuenta cash como source → debe ser inversión."""
        with pytest.raises(ValueError, match="debe ser una cuenta de inversión"):
            create_movimiento(db, MovementCreateRequest(
                telegram_user_id=USER_TID,
                movement_type="MOV",
                movement_date="2026-06-10",
                amount=100.0,
                mov_subtype="INVERSION",
                mov_direction="RETIRAR_INV",
                source_account_name="Efectivo",   # cash, no es inversión
                target_account_name="Efectivo",
            ))

    def test_invertir_with_non_investment_target_raises(self, db, test_user, user_accounts):
        """INVERTIR con cuenta cash como target → debe ser inversión."""
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        with pytest.raises(ValueError, match="debe ser una cuenta de inversión"):
            create_movimiento(db, MovementCreateRequest(
                telegram_user_id=USER_TID,
                movement_type="MOV",
                movement_date="2026-06-10",
                amount=100.0,
                mov_subtype="INVERSION",
                mov_direction="INVERTIR",
                source_account_name="Efectivo",
                target_account_name="Efectivo",  # cash, no es inversión
            ))


# ── MOVER_INV success (lines 519-535) ────────────────────────────────────────

class TestMovInversionMoverOk:
    def test_mover_inv_different_accounts(self, db, test_user, user_accounts, inv_account, inv_account2):
        mov = create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID,
            movement_type="MOV",
            movement_date="2026-06-10",
            amount=150.0,
            mov_subtype="INVERSION",
            mov_direction="MOVER_INV",
            source_account_name="Binance",
            target_account_name="Crypto",
        ))
        db.commit()
        assert mov.source_account_id == inv_account.id
        assert mov.target_account_id == inv_account2.id


# ── build_ahorro_breakdown_internal RETIRAR path (lines 125-127) ─────────────

class TestBuildAhorro:
    def test_second_retirar_sees_existing_retirar_movement(self, db, test_user, user_accounts):
        """Ejercita el elif `source_name == 'Ahorro'` en build_ahorro_breakdown."""
        _fund(db, test_user.id, user_accounts["efectivo"].id, 2000.0)

        # Primera operación: GUARDAR 1000
        create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-01", amount=1000.0,
            mov_subtype="AHORRO", mov_direction="GUARDAR",
            source_account_name="Efectivo",
        ))
        db.commit()

        # Segunda operación: RETIRAR 200 (crea un movimiento Ahorro→Efectivo en DB)
        create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-02", amount=200.0,
            mov_subtype="AHORRO", mov_direction="RETIRAR",
            target_account_name="Efectivo",
        ))
        db.commit()

        # Tercera operación: RETIRAR 100 más
        # Cuando se ejecuta, build_ahorro_breakdown_internal ve ambos movimientos:
        #   - GUARDAR (target=Ahorro) → línea 124 (ya cubierta)
        #   - RETIRAR (source=Ahorro) → líneas 125-127 (la rama elif, ahora cubierta)
        mov = create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-03", amount=100.0,
            mov_subtype="AHORRO", mov_direction="RETIRAR",
            target_account_name="Efectivo",
        ))
        db.commit()
        assert mov is not None


# ── build_loan_balance_internal payment deduction (lines 155-160) ─────────────

class TestBuildLoanBalance:
    def test_cobrar_second_payment_deducts_first(self, db, test_user, user_accounts):
        """Ejercita el desglose de pagos en build_loan_balance_internal (lines 155-160)."""
        person = LoanPerson(user_id=test_user.id, name="Maria", is_active=True)
        db.add(person)
        db.commit()

        _fund(db, test_user.id, user_accounts["efectivo"].id, 3000.0)

        # DAR préstamo
        create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-01", amount=1000.0,
            mov_subtype="PRESTAMO", mov_direction="DAR",
            source_account_name="Efectivo",
            loan_person_name="Maria",
            note="Préstamo estudio",
        ))
        db.commit()

        # COBRAR primera parte
        create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-15", amount=300.0,
            mov_subtype="PRESTAMO", mov_direction="COBRAR",
            target_account_name="Efectivo",
            loan_person_name="Maria",
            note="Préstamo estudio",
        ))
        db.commit()

        # COBRAR segunda parte — en este punto build_loan_balance_internal ve
        # el LoanPayment ya existente → líneas 155-160 (deducción del balance)
        result = create_movimiento(db, MovementCreateRequest(
            telegram_user_id=USER_TID, movement_type="MOV",
            movement_date="2026-06-20", amount=200.0,
            mov_subtype="PRESTAMO", mov_direction="COBRAR",
            target_account_name="Efectivo",
            loan_person_name="Maria",
            note="Préstamo estudio",
        ))
        db.commit()
        assert result is not None
        assert float(result.amount) == pytest.approx(200.0)
