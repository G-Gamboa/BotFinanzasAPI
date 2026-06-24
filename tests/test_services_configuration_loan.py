"""Tests para configuration_service — update_loan_person y set_loan_person_active."""
import pytest

from app.services.configuration_service import (
    create_loan_person,
    set_loan_person_active,
    update_loan_person,
)


USER_TID = 999_999_999


class TestUpdateLoanPerson:
    def test_updates_name(self, db, test_user):
        person = create_loan_person(db, USER_TID, "Roberto")
        updated = update_loan_person(db, person.id, USER_TID, "Roberto Nuevo")
        assert updated.name == "Roberto Nuevo"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Persona no encontrada"):
            update_loan_person(db, 99999, USER_TID, "x")

    def test_empty_name_raises(self, db, test_user):
        person = create_loan_person(db, USER_TID, "Ana")
        with pytest.raises(ValueError, match="obligatorio"):
            update_loan_person(db, person.id, USER_TID, "   ")

    def test_duplicate_name_raises(self, db, test_user):
        create_loan_person(db, USER_TID, "Mario")
        person2 = create_loan_person(db, USER_TID, "Luigi")
        with pytest.raises(ValueError, match="Ya existe otra persona"):
            update_loan_person(db, person2.id, USER_TID, "Mario")

    def test_same_name_does_not_raise(self, db, test_user):
        person = create_loan_person(db, USER_TID, "Pedro")
        updated = update_loan_person(db, person.id, USER_TID, "Pedro")
        assert updated.name == "Pedro"


class TestSetLoanPersonActive:
    def test_deactivate(self, db, test_user):
        person = create_loan_person(db, USER_TID, "Rosa")
        result = set_loan_person_active(db, person.id, USER_TID, False)
        assert result.is_active is False

    def test_reactivate(self, db, test_user):
        person = create_loan_person(db, USER_TID, "Tomas")
        set_loan_person_active(db, person.id, USER_TID, False)
        result = set_loan_person_active(db, person.id, USER_TID, True)
        assert result.is_active is True

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Persona no encontrada"):
            set_loan_person_active(db, 99999, USER_TID, False)
