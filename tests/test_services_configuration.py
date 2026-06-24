"""Tests para configuration_service — cuentas, categorías, loan_people."""
from datetime import datetime, timezone

import pytest

from app.services.configuration_service import (
    create_account,
    create_category,
    create_loan_person,
    list_accounts,
    list_categories,
    list_loan_people,
    set_account_active,
    set_category_active,
    update_account,
    update_category,
)


USER_TID = 999_999_999


# ── list_accounts ─────────────────────────────────────────────────────────────

class TestListAccounts:
    def test_returns_existing_accounts(self, db, test_user, user_accounts):
        result = list_accounts(db, USER_TID)
        names = [a["name"] for a in result["items"]]
        assert "Efectivo" in names
        assert "Ahorro" in names

    def test_item_has_required_fields(self, db, test_user, user_accounts):
        item = list_accounts(db, USER_TID)["items"][0]
        for f in ("id", "name", "account_type", "currency", "is_active", "is_system", "sort_order"):
            assert f in item


# ── create_account ────────────────────────────────────────────────────────────

class TestCreateAccount:
    def test_creates_cash_account(self, db, test_user):
        acc = create_account(db, USER_TID, "Billetera", "cash", "GTQ", sort_order=5)
        assert acc.id is not None
        assert acc.name == "Billetera"
        assert acc.is_active is True

    def test_duplicate_name_raises(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="Ya existe una cuenta"):
            create_account(db, USER_TID, "Efectivo", "cash", "GTQ", sort_order=99)

    def test_invalid_type_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Tipo de cuenta inválido"):
            create_account(db, USER_TID, "XYZ", "invisible", "GTQ", sort_order=1)

    def test_invalid_currency_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Moneda inválida"):
            create_account(db, USER_TID, "Euro", "cash", "EUR", sort_order=1)

    def test_empty_name_raises(self, db, test_user):
        with pytest.raises(ValueError, match="obligatorio"):
            create_account(db, USER_TID, "   ", "cash", "GTQ", sort_order=1)

    def test_credit_card_stores_cc_fields(self, db, test_user):
        acc = create_account(
            db, USER_TID, "Visa", "credit_card", "GTQ", sort_order=10,
            billing_close_day=15, payment_due_day=25, tc_type="GTQ",
        )
        assert acc.billing_close_day == 15
        assert acc.payment_due_day == 25
        assert acc.tc_type == "GTQ"

    def test_non_cc_fields_nulled_for_cash(self, db, test_user):
        acc = create_account(
            db, USER_TID, "Efectivo2", "cash", "GTQ", sort_order=2,
            billing_close_day=15,  # debe ignorarse
        )
        assert acc.billing_close_day is None


# ── update_account ────────────────────────────────────────────────────────────

class TestUpdateAccount:
    def test_updates_name(self, db, test_user, user_accounts):
        acc_id = user_accounts["efectivo"].id
        # Renombrar cuenta no-sistema
        user_accounts["efectivo"].is_system = False
        db.commit()
        updated = update_account(db, acc_id, USER_TID, "Efectivo Renombrado", "cash", "GTQ", sort_order=1)
        assert updated.name == "Efectivo Renombrado"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Cuenta no encontrada"):
            update_account(db, 99999, USER_TID, "x", "cash", "GTQ", sort_order=1)

    def test_system_account_cannot_be_renamed(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="No puedes renombrar"):
            update_account(
                db, user_accounts["efectivo"].id, USER_TID,
                "Otro nombre", "cash", "GTQ", sort_order=1,
            )

    def test_duplicate_name_raises(self, db, test_user, user_accounts):
        user_accounts["efectivo"].is_system = False
        user_accounts["ahorro"].is_system = False
        db.commit()
        with pytest.raises(ValueError, match="Ya existe otra cuenta"):
            update_account(
                db, user_accounts["efectivo"].id, USER_TID,
                "Ahorro", "cash", "GTQ", sort_order=1,
            )


# ── set_account_active ────────────────────────────────────────────────────────

class TestSetAccountActive:
    def test_deactivate_non_system(self, db, test_user, user_accounts):
        user_accounts["efectivo"].is_system = False
        db.commit()
        result = set_account_active(db, user_accounts["efectivo"].id, USER_TID, False)
        assert result.is_active is False

    def test_system_account_cannot_be_deactivated(self, db, test_user, user_accounts):
        with pytest.raises(ValueError, match="No puedes desactivar"):
            set_account_active(db, user_accounts["efectivo"].id, USER_TID, False)

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Cuenta no encontrada"):
            set_account_active(db, 99999, USER_TID, False)


# ── list_categories ───────────────────────────────────────────────────────────

class TestListCategories:
    def test_returns_all_categories(self, db, test_user, user_categories):
        result = list_categories(db, USER_TID)
        names = [c["name"] for c in result["items"]]
        assert "Salario" in names
        assert "Alimentación" in names

    def test_otros_sorted_last_within_kind(self, db, test_user, user_categories):
        from app.db.models import Category
        now = datetime.now(timezone.utc)
        db.add(Category(
            user_id=test_user.id, name="Otros", kind="EGR",
            is_active=True, is_system=False, sort_order=99,
            created_at=now, updated_at=now,
        ))
        db.commit()
        result = list_categories(db, USER_TID)
        egr_items = [c for c in result["items"] if c["kind"] == "EGR"]
        assert egr_items[-1]["name"] == "Otros"


# ── create_category ───────────────────────────────────────────────────────────

class TestCreateCategory:
    def test_creates_ok(self, db, test_user):
        cat = create_category(db, USER_TID, "Transporte", "EGR", sort_order=5)
        assert cat.id is not None
        assert cat.name == "Transporte"
        assert cat.kind == "EGR"

    def test_duplicate_raises(self, db, test_user, user_categories):
        with pytest.raises(ValueError, match="Ya existe una categoría"):
            create_category(db, USER_TID, "Alimentación", "EGR", sort_order=99)

    def test_invalid_kind_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Tipo de categoría inválido"):
            create_category(db, USER_TID, "Test", "MOV", sort_order=1)

    def test_empty_name_raises(self, db, test_user):
        with pytest.raises(ValueError, match="obligatorio"):
            create_category(db, USER_TID, "  ", "EGR", sort_order=1)


# ── update_category ───────────────────────────────────────────────────────────

class TestUpdateCategory:
    def test_updates_name(self, db, test_user, user_categories):
        cat = user_categories["alimentacion"]
        cat.is_system = False
        db.commit()
        updated = update_category(db, cat.id, USER_TID, "Comida", "EGR", sort_order=1)
        assert updated.name == "Comida"

    def test_not_found_raises(self, db, test_user):
        with pytest.raises(ValueError, match="Categoría no encontrada"):
            update_category(db, 99999, USER_TID, "x", "EGR", sort_order=1)

    def test_system_category_cannot_be_renamed(self, db, test_user, user_categories):
        cat = user_categories["alimentacion"]
        cat.is_system = True
        db.commit()
        with pytest.raises(ValueError, match="No puedes renombrar"):
            update_category(db, cat.id, USER_TID, "Nuevo nombre", "EGR", sort_order=1)


# ── set_category_active ───────────────────────────────────────────────────────

class TestSetCategoryActive:
    def test_deactivate_non_system(self, db, test_user, user_categories):
        cat = user_categories["alimentacion"]
        result = set_category_active(db, cat.id, USER_TID, False)
        assert result.is_active is False

    def test_system_category_cannot_be_deactivated(self, db, test_user, user_categories):
        cat = user_categories["alimentacion"]
        cat.is_system = True
        db.commit()
        with pytest.raises(ValueError, match="No puedes desactivar"):
            set_category_active(db, cat.id, USER_TID, False)


# ── list_loan_people / create_loan_person ─────────────────────────────────────

class TestLoanPeople:
    def test_empty_list(self, db, test_user):
        result = list_loan_people(db, USER_TID)
        assert result["items"] == []

    def test_create_and_list(self, db, test_user):
        p = create_loan_person(db, USER_TID, "Roberto")
        assert p.id is not None
        assert p.name == "Roberto"
        result = list_loan_people(db, USER_TID)
        assert any(item["name"] == "Roberto" for item in result["items"])

    def test_duplicate_name_raises(self, db, test_user):
        create_loan_person(db, USER_TID, "Ana")
        with pytest.raises(ValueError, match="Ya existe"):
            create_loan_person(db, USER_TID, "Ana")

    def test_empty_name_raises(self, db, test_user):
        with pytest.raises(ValueError, match="obligatorio"):
            create_loan_person(db, USER_TID, "   ")
