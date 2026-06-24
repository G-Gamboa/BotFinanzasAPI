"""Tests para transaction_service — MOV subtypes (AHORRO, INVERSION, PRESTAMO, NORMAL)."""
from datetime import date

import pytest
from pydantic import ValidationError

from app.db.models import Account, Loan, LoanPerson, Movement
from app.schemas.transactions import MovementCreateRequest
from app.services.transaction_service import create_movimiento


USER_TID = 999_999_999


# ── Helpers ───────────────────────────────────────────────────────────────────

def _req(**kwargs) -> MovementCreateRequest:
    base = {
        "telegram_user_id": USER_TID,
        "movement_type": "MOV",
        "movement_date": "2026-06-10",
        "amount": 200.0,
        "mov_subtype": "NORMAL",
        "mov_direction": "NORMAL",
    }
    return MovementCreateRequest(**{**base, **kwargs})


def _fund(db, user_id, account_id, amount=1000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


@pytest.fixture
def banco(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Banco",
        account_type="bank", currency="GTQ",
        is_active=True, is_system=False, sort_order=3,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def inv_account(db, test_user):
    acc = Account(
        user_id=test_user.id, name="Binance",
        account_type="investment", currency="GTQ",
        is_active=True, is_system=False, sort_order=4,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def loan_person(db, test_user):
    p = LoanPerson(user_id=test_user.id, name="Pedro", is_active=True)
    db.add(p)
    db.commit()
    return p


# ── MOV NORMAL ────────────────────────────────────────────────────────────────

class TestMovNormal:
    def test_transfers_between_liquid_accounts(self, db, test_user, user_accounts, banco):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        mov = create_movimiento(db, _req(
            mov_subtype="NORMAL", mov_direction="NORMAL",
            source_account_name="Efectivo",
            target_account_name="Banco",
        ))
        db.commit()
        assert mov.source_account_id == user_accounts["efectivo"].id
        assert mov.target_account_id == banco.id

    def test_same_account_raises(self, db, test_user, user_accounts, banco):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        with pytest.raises(ValueError, match="no pueden ser iguales"):
            create_movimiento(db, _req(
                mov_subtype="NORMAL", mov_direction="NORMAL",
                source_account_name="Efectivo",
                target_account_name="Efectivo",
            ))

    def test_insufficient_balance_raises(self, db, test_user, user_accounts, banco):
        # Efectivo vacío
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            create_movimiento(db, _req(
                mov_subtype="NORMAL", mov_direction="NORMAL",
                amount=500.0,
                source_account_name="Efectivo",
                target_account_name="Banco",
            ))


# ── MOV AHORRO ────────────────────────────────────────────────────────────────

class TestMovAhorro:
    def test_guardar_ok(self, db, test_user, user_accounts):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        mov = create_movimiento(db, _req(
            mov_subtype="AHORRO", mov_direction="GUARDAR",
            amount=300.0, source_account_name="Efectivo",
        ))
        db.commit()
        assert mov.source_account_id == user_accounts["efectivo"].id
        assert mov.target_account_id == user_accounts["ahorro"].id

    def test_guardar_insufficient_balance_raises(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            create_movimiento(db, _req(
                mov_subtype="AHORRO", mov_direction="GUARDAR",
                amount=500.0, source_account_name="Efectivo",
            ))

    def test_retirar_ok(self, db, test_user, user_accounts):
        # Primero guardar para tener saldo en ahorro
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        create_movimiento(db, _req(
            mov_subtype="AHORRO", mov_direction="GUARDAR",
            amount=500.0, source_account_name="Efectivo",
        ))
        db.commit()

        mov = create_movimiento(db, _req(
            mov_subtype="AHORRO", mov_direction="RETIRAR",
            amount=200.0, target_account_name="Efectivo",
        ))
        db.commit()
        assert mov.source_account_id == user_accounts["ahorro"].id
        assert mov.target_account_id == user_accounts["efectivo"].id

    def test_retirar_sin_saldo_raises(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="No puedes retirar"):
            create_movimiento(db, _req(
                mov_subtype="AHORRO", mov_direction="RETIRAR",
                amount=100.0, target_account_name="Efectivo",
            ))

    def test_invalid_direction_raises(self, db, test_user, user_accounts):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        with pytest.raises(ValueError, match="mov_direction inválido para AHORRO"):
            create_movimiento(db, _req(
                mov_subtype="AHORRO", mov_direction="INVERTIR",
                amount=100.0, source_account_name="Efectivo",
            ))


# ── MOV INVERSION ─────────────────────────────────────────────────────────────

class TestMovInversion:
    def test_invertir_ok(self, db, test_user, user_accounts, inv_account):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        mov = create_movimiento(db, _req(
            mov_subtype="INVERSION", mov_direction="INVERTIR",
            amount=400.0,
            source_account_name="Efectivo",
            target_account_name="Binance",
        ))
        db.commit()
        assert mov.source_account_id == user_accounts["efectivo"].id
        assert mov.target_account_id == inv_account.id

    def test_retirar_inv_ok(self, db, test_user, user_accounts, inv_account):
        mov = create_movimiento(db, _req(
            mov_subtype="INVERSION", mov_direction="RETIRAR_INV",
            amount=300.0,
            source_account_name="Binance",
            target_account_name="Efectivo",
        ))
        db.commit()
        assert mov.source_account_id == inv_account.id

    def test_invertir_insufficient_balance_raises(self, db, test_user, user_accounts, inv_account):
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            create_movimiento(db, _req(
                mov_subtype="INVERSION", mov_direction="INVERTIR",
                amount=500.0,
                source_account_name="Efectivo",
                target_account_name="Binance",
            ))

    def test_mover_inv_same_account_raises(self, db, test_user, user_accounts, inv_account):
        with pytest.raises(ValueError, match="no pueden ser iguales"):
            create_movimiento(db, _req(
                mov_subtype="INVERSION", mov_direction="MOVER_INV",
                amount=100.0,
                source_account_name="Binance",
                target_account_name="Binance",
            ))

    def test_invalid_direction_raises(self, db, test_user, user_accounts, inv_account):
        with pytest.raises(ValueError, match="mov_direction inválido para INVERSION"):
            create_movimiento(db, _req(
                mov_subtype="INVERSION", mov_direction="GUARDAR",
                amount=100.0,
                source_account_name="Efectivo",
                target_account_name="Binance",
            ))


# ── MOV PRESTAMO ──────────────────────────────────────────────────────────────

class TestMovPrestamo:
    def test_dar_prestamo_creates_loan(self, db, test_user, user_accounts, loan_person):
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        result = create_movimiento(db, _req(
            mov_subtype="PRESTAMO", mov_direction="DAR",
            amount=500.0,
            source_account_name="Efectivo",
            loan_person_name="Pedro",
        ))
        db.commit()
        assert result.__class__.__name__ == "Loan"
        assert float(result.principal_amount) == 500.0

    def test_dar_without_permission_raises(self, db, test_user, user_accounts, loan_person):
        test_user.can_use_loans = False
        db.commit()
        with pytest.raises(ValueError, match="no tiene permiso"):
            create_movimiento(db, _req(
                mov_subtype="PRESTAMO", mov_direction="DAR",
                amount=100.0,
                source_account_name="Efectivo",
                loan_person_name="Pedro",
            ))

    def test_dar_unknown_person_raises(self, db, test_user, user_accounts, loan_person):
        with pytest.raises(ValueError, match="loan_person_name no existe"):
            create_movimiento(db, _req(
                mov_subtype="PRESTAMO", mov_direction="DAR",
                amount=100.0,
                source_account_name="Efectivo",
                loan_person_name="Nadie",
            ))

    def test_cobrar_ok(self, db, test_user, user_accounts, loan_person):
        # Crear préstamo primero
        _fund(db, test_user.id, user_accounts["efectivo"].id, 1000.0)
        create_movimiento(db, _req(
            mov_subtype="PRESTAMO", mov_direction="DAR",
            amount=500.0,
            source_account_name="Efectivo",
            loan_person_name="Pedro",
            note="Préstamo carro",
        ))
        db.commit()

        result = create_movimiento(db, _req(
            mov_subtype="PRESTAMO", mov_direction="COBRAR",
            amount=200.0,
            target_account_name="Efectivo",
            loan_person_name="Pedro",
            note="Préstamo carro",
        ))
        db.commit()
        assert result.__class__.__name__ == "LoanPayment"
        assert float(result.amount) == 200.0

    def test_invalid_direction_raises(self, db, test_user, user_accounts, loan_person):
        with pytest.raises(ValueError, match="mov_direction inválido para PRESTAMO"):
            create_movimiento(db, _req(
                mov_subtype="PRESTAMO", mov_direction="GUARDAR",
                amount=100.0, loan_person_name="Pedro",
            ))

    def test_invalid_subtype_raises(self, db, test_user, user_accounts):
        with pytest.raises(ValidationError):
            _req(mov_subtype="XXXXX", mov_direction="NORMAL")
