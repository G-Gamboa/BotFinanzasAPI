"""Tests para availability_service.build_disponibles (lines 19-64)."""
from datetime import date

import pytest

from app.db.models import Loan, LoanPerson, Movement
from app.services.availability_service import build_disponibles


USER_TID = 999_999_999


def _ing(db, user_id, account_id, amount=1000.0):
    m = Movement(
        user_id=user_id, movement_type="ING",
        movement_date=date(2026, 6, 1), amount=amount,
        target_account_id=account_id, payment_method="cash", is_void=False,
    )
    db.add(m)
    db.commit()


class TestBuildDisponibles:
    def test_empty_returns_structure(self, db, test_user, user_accounts):
        result = build_disponibles(db, USER_TID)
        assert "saldos_liquidos" in result
        assert "ahorro_por_cuenta" in result
        assert "prestamos_por_persona" in result

    def test_empty_lists_when_no_transactions(self, db, test_user, user_accounts):
        result = build_disponibles(db, USER_TID)
        assert result["saldos_liquidos"] == []
        assert result["ahorro_por_cuenta"] == []
        assert result["prestamos_por_persona"] == []

    def test_liquid_balance_included(self, db, test_user, user_accounts):
        _ing(db, test_user.id, user_accounts["efectivo"].id, 500.0)
        result = build_disponibles(db, USER_TID)
        names = [s["cuenta"] for s in result["saldos_liquidos"]]
        assert "Efectivo" in names
        efectivo = next(s for s in result["saldos_liquidos"] if s["cuenta"] == "Efectivo")
        assert efectivo["saldo"] == pytest.approx(500.0)

    def test_ahorro_breakdown_included(self, db, test_user, user_accounts):
        # GUARDAR: Efectivo → Ahorro
        _ing(db, test_user.id, user_accounts["efectivo"].id, 2000.0)
        db.add(Movement(
            user_id=test_user.id, movement_type="MOV",
            movement_date=date(2026, 6, 5), amount=800.0,
            source_account_id=user_accounts["efectivo"].id,
            target_account_id=user_accounts["ahorro"].id,
            is_void=False,
        ))
        db.commit()

        result = build_disponibles(db, USER_TID)
        assert len(result["ahorro_por_cuenta"]) == 1
        assert result["ahorro_por_cuenta"][0]["saldo"] == pytest.approx(800.0)

    def test_prestamos_balance_included(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Julio", is_active=True)
        db.add(person)
        db.commit()

        _ing(db, test_user.id, user_accounts["efectivo"].id, 3000.0)

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=1200.0,
            loan_date=date(2026, 6, 10),
            status="active",
            source_account_id=user_accounts["efectivo"].id,
        )
        db.add(loan)
        db.commit()

        result = build_disponibles(db, USER_TID)
        personas = {p["persona"]: p["saldo"] for p in result["prestamos_por_persona"]}
        assert "Julio" in personas
        assert personas["Julio"] == pytest.approx(1200.0)

    def test_zero_saldo_excluded_from_liquid(self, db, test_user, user_accounts):
        # Efectivo vacío → no aparece en saldos_liquidos
        result = build_disponibles(db, USER_TID)
        for item in result["saldos_liquidos"]:
            assert abs(item["saldo"]) > 1e-9
