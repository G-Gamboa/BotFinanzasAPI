"""Tests para loans_view_service."""
from datetime import date

import pytest

from app.db.models import Loan, LoanPayment, LoanPerson
from app.services.loans_view_service import (
    build_loans_view,
    get_loan_concepts_balance,
    normalize_loan_concept,
)


USER_TID = 999_999_999


# ── normalize_loan_concept ────────────────────────────────────────────────────

class TestNormalizeLoanConcept:
    def test_none_returns_general(self):
        assert normalize_loan_concept(None) == "General"

    def test_empty_string_returns_general(self):
        assert normalize_loan_concept("") == "General"

    def test_whitespace_only_returns_general(self):
        assert normalize_loan_concept("   ") == "General"

    def test_normal_note(self):
        assert normalize_loan_concept("Préstamo auto") == "Préstamo auto"

    def test_strips_extra_spaces(self):
        assert normalize_loan_concept("  hola  mundo  ") == "hola mundo"


# ── build_loans_view ──────────────────────────────────────────────────────────

class TestBuildLoansView:
    def test_empty_returns_empty_items(self, db, test_user):
        result = build_loans_view(db, USER_TID)
        assert result["items"] == []
        assert result["total_people"] == 0

    def test_user_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            build_loans_view(db, 0)

    def test_single_loan(self, db, test_user):
        person = LoanPerson(user_id=test_user.id, name="Ana", is_active=True)
        db.add(person)
        db.flush()

        db.add(Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=1000.0,
            loan_date=date(2026, 1, 1),
            status="active",
            note="Préstamo general",
        ))
        db.commit()

        result = build_loans_view(db, USER_TID)
        assert len(result["items"]) == 1
        assert result["items"][0]["person"] == "Ana"
        assert result["items"][0]["total_balance"] == 1000.0

    def test_payment_reduces_balance(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Carlos", is_active=True)
        db.add(person)
        db.flush()

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=500.0,
            loan_date=date(2026, 1, 1),
            status="active",
            note=None,
        )
        db.add(loan)
        db.flush()

        db.add(LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=200.0,
            payment_date=date(2026, 2, 1),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_loans_view(db, USER_TID)
        assert result["items"][0]["total_balance"] == 300.0

    def test_fully_paid_loan_excluded(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="Luis", is_active=True)
        db.add(person)
        db.flush()

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=300.0,
            loan_date=date(2026, 1, 1),
            status="active",
            note=None,
        )
        db.add(loan)
        db.flush()

        db.add(LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=300.0,
            payment_date=date(2026, 2, 1),
            account_id=user_accounts["efectivo"].id,
            is_void=False,
        ))
        db.commit()

        result = build_loans_view(db, USER_TID)
        assert result["total_people"] == 0

    def test_voided_payment_ignored(self, db, test_user, user_accounts):
        person = LoanPerson(user_id=test_user.id, name="María", is_active=True)
        db.add(person)
        db.flush()

        loan = Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=400.0,
            loan_date=date(2026, 1, 1),
            status="active",
        )
        db.add(loan)
        db.flush()

        db.add(LoanPayment(
            loan_id=loan.id,
            user_id=test_user.id,
            amount=400.0,
            payment_date=date(2026, 2, 1),
            account_id=user_accounts["efectivo"].id,
            is_void=True,  # anulado → no cuenta
        ))
        db.commit()

        result = build_loans_view(db, USER_TID)
        # Pago anulado → saldo sigue siendo 400
        assert result["items"][0]["total_balance"] == 400.0


# ── get_loan_concepts_balance ─────────────────────────────────────────────────

class TestGetLoanConceptsBalance:
    def test_no_loans_returns_empty(self, db, test_user):
        result = get_loan_concepts_balance(db, USER_TID, "Nadie")
        assert result == {}

    def test_returns_balance_by_concept(self, db, test_user):
        person = LoanPerson(user_id=test_user.id, name="Roberto", is_active=True)
        db.add(person)
        db.flush()

        db.add(Loan(
            user_id=test_user.id,
            loan_person_id=person.id,
            loan_type="lent",
            principal_amount=750.0,
            loan_date=date(2026, 1, 1),
            status="active",
            note="Computadora",
        ))
        db.commit()

        result = get_loan_concepts_balance(db, USER_TID, "Roberto")
        assert result["Computadora"] == 750.0
