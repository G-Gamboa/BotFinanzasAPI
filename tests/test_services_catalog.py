"""Tests para catalog_service.build_catalogs."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.db.models import Account, Category, LoanPerson
from app.services.catalog_service import build_catalogs, get_user_or_raise


USER_TID = 999_999_999


def _settings(admin_ids=None, palette_ids=None):
    return Mock(
        admin_telegram_ids=admin_ids or [],
        private_palette_user_ids=palette_ids or [],
    )


# ── get_user_or_raise ─────────────────────────────────────────────────────────

class TestGetUserOrRaise:
    def test_returns_user(self, db, test_user):
        u = get_user_or_raise(db, USER_TID)
        assert u.telegram_user_id == USER_TID

    def test_missing_user_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            get_user_or_raise(db, 0)


# ── build_catalogs ────────────────────────────────────────────────────────────

class TestBuildCatalogs:
    def test_empty_catalog(self, db, test_user):
        result = build_catalogs(db, USER_TID, _settings())
        assert result["accounts"]["liquid"] == []
        assert result["categories"]["ing"] == []
        assert result["loan_people"] == []

    def test_user_flags_non_admin(self, db, test_user):
        result = build_catalogs(db, USER_TID, _settings())
        assert result["user"]["is_admin"] is False
        assert result["user"]["can_use_loans"] is True  # test_user has can_use_loans=True

    def test_user_is_admin_when_in_admin_ids(self, db, test_user):
        result = build_catalogs(db, USER_TID, _settings(admin_ids=[USER_TID]))
        assert result["user"]["is_admin"] is True

    def test_private_palette(self, db, test_user):
        result = build_catalogs(db, USER_TID, _settings(palette_ids=[USER_TID]))
        assert result["user"]["can_use_private_palettes"] is True

    def test_liquid_account_appears(self, db, test_user):
        db.add(Account(
            user_id=test_user.id, name="Efectivo",
            account_type="cash", currency="GTQ",
            is_active=True, is_system=True, sort_order=1,
        ))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        names = [a["name"] for a in result["accounts"]["liquid"]]
        assert "Efectivo" in names

    def test_ahorro_account_separated(self, db, test_user):
        db.add(Account(
            user_id=test_user.id, name="Ahorro",
            account_type="savings", currency="GTQ",
            is_active=True, is_system=True, sort_order=2,
        ))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        assert result["accounts"]["ahorro"] is not None
        assert result["accounts"]["ahorro"]["name"] == "Ahorro"

    def test_credit_card_account_has_extra_fields(self, db, test_user):
        db.add(Account(
            user_id=test_user.id, name="Visa",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=3,
            tc_type="GTQ", billing_close_day=15, payment_due_day=25,
        ))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        ccs = result["accounts"]["credit_cards"]
        assert len(ccs) == 1
        assert ccs[0]["tc_type"] == "GTQ"
        assert ccs[0]["billing_close_day"] == 15

    def test_inactive_account_excluded(self, db, test_user):
        db.add(Account(
            user_id=test_user.id, name="Inactiva",
            account_type="cash", currency="GTQ",
            is_active=False, is_system=False, sort_order=99,
        ))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        names = [a["name"] for a in result["accounts"]["liquid"]]
        assert "Inactiva" not in names

    def test_categories_split_by_kind(self, db, test_user):
        now = datetime.now(timezone.utc)
        db.add_all([
            Category(user_id=test_user.id, name="Salario", kind="ING",
                     is_active=True, is_system=False, sort_order=1,
                     created_at=now, updated_at=now),
            Category(user_id=test_user.id, name="Comida", kind="EGR",
                     is_active=True, is_system=False, sort_order=1,
                     created_at=now, updated_at=now),
        ])
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        assert any(c["name"] == "Salario" for c in result["categories"]["ing"])
        assert any(c["name"] == "Comida" for c in result["categories"]["egr"])

    def test_otros_sorted_last(self, db, test_user):
        now = datetime.now(timezone.utc)
        db.add_all([
            Category(user_id=test_user.id, name="Otros", kind="EGR",
                     is_active=True, is_system=False, sort_order=1,
                     created_at=now, updated_at=now),
            Category(user_id=test_user.id, name="Alimentación", kind="EGR",
                     is_active=True, is_system=False, sort_order=2,
                     created_at=now, updated_at=now),
        ])
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        egr = result["categories"]["egr"]
        assert egr[-1]["name"] == "Otros"

    def test_loan_people_hidden_when_no_loans(self, db, test_user):
        """Usuario sin can_use_loans no ve loan_people."""
        test_user.can_use_loans = False
        db.add(LoanPerson(user_id=test_user.id, name="Juan", is_active=True))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        assert result["loan_people"] == []

    def test_loan_people_visible_when_can_use_loans(self, db, test_user):
        db.add(LoanPerson(user_id=test_user.id, name="Pedro", is_active=True))
        db.commit()
        result = build_catalogs(db, USER_TID, _settings())
        assert any(p["name"] == "Pedro" for p in result["loan_people"])
