"""Tests para history_service."""
from datetime import date, datetime, timezone

import pytest

from app.db.models import Movement, Category
from app.services.history_service import (
    build_history,
    detect_subtype,
    parse_optional_date,
)


USER_TID = 999_999_999


# ── parse_optional_date ───────────────────────────────────────────────────────

class TestParseOptionalDate:
    def test_none_returns_none(self):
        assert parse_optional_date(None) is None

    def test_empty_string_returns_none(self):
        assert parse_optional_date("") is None

    def test_valid_date(self):
        assert parse_optional_date("2026-06-15") == date(2026, 6, 15)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_optional_date("15-06-2026")


# ── detect_subtype ────────────────────────────────────────────────────────────

class TestDetectSubtype:
    def _mock_mov(self, movement_type):
        class FakeMov:
            pass
        m = FakeMov()
        m.movement_type = movement_type
        return m

    def test_ing_returns_ingreso(self):
        assert detect_subtype(self._mock_mov("ING"), None, None, None, None) == "INGRESO"

    def test_egr_returns_egreso(self):
        assert detect_subtype(self._mock_mov("EGR"), None, None, None, None) == "EGRESO"

    def test_mov_ahorro_source(self):
        assert detect_subtype(self._mock_mov("MOV"), "Ahorro", "Efectivo", None, None) == "AHORRO"

    def test_mov_ahorro_target(self):
        assert detect_subtype(self._mock_mov("MOV"), "Efectivo", "Ahorro", None, None) == "AHORRO"

    def test_mov_prestamo_by_person(self):
        assert detect_subtype(self._mock_mov("MOV"), None, None, None, "Juan") == "PRESTAMO"

    def test_mov_prestamo_by_source(self):
        assert detect_subtype(self._mock_mov("MOV"), "Prestamos", None, None, None) == "PRESTAMO"

    def test_mov_inversion(self):
        assert detect_subtype(self._mock_mov("MOV"), "Efectivo", "Binance", None, None) == "INVERSION"

    def test_mov_normal_cash_transfer(self):
        assert detect_subtype(self._mock_mov("MOV"), "Efectivo", "Banco", None, None) == "NORMAL"

    def test_unknown_type_returns_otro(self):
        assert detect_subtype(self._mock_mov("XXX"), None, None, None, None) == "OTRO"


# ── build_history ─────────────────────────────────────────────────────────────

def _make_ing(db, test_user, user_accounts, user_categories, mov_date="2026-06-10", amount=200.0):
    m = Movement(
        user_id=test_user.id,
        movement_type="ING",
        movement_date=date.fromisoformat(mov_date),
        amount=amount,
        note="Test ING",
        target_account_id=user_accounts["efectivo"].id,
        category_id=user_categories["salario"].id,
        payment_method="cash",
        is_void=False,
    )
    db.add(m)
    db.commit()
    return m


class TestBuildHistory:
    def test_empty_history(self, db, test_user):
        result = build_history(db, USER_TID)
        assert result["items"] == []

    def test_user_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            build_history(db, 0)

    def test_invalid_movement_type_raises(self, db, test_user):
        with pytest.raises(ValueError, match="movement_type"):
            build_history(db, USER_TID, movement_type="INVALID")

    def test_date_range_inverted_raises(self, db, test_user):
        with pytest.raises(ValueError, match="date_from"):
            build_history(db, USER_TID, date_from="2026-06-30", date_to="2026-06-01")

    def test_ingreso_appears_in_history(self, db, test_user, user_accounts, user_categories):
        _make_ing(db, test_user, user_accounts, user_categories)
        result = build_history(db, USER_TID)
        assert len(result["items"]) == 1
        assert result["items"][0]["movement_type"] == "ING"

    def test_voided_movement_excluded(self, db, test_user, user_accounts, user_categories):
        m = _make_ing(db, test_user, user_accounts, user_categories)
        m.is_void = True
        db.commit()
        result = build_history(db, USER_TID)
        assert result["items"] == []

    def test_filter_by_movement_type(self, db, test_user, user_accounts, user_categories):
        _make_ing(db, test_user, user_accounts, user_categories)
        result_ing = build_history(db, USER_TID, movement_type="ING")
        result_egr = build_history(db, USER_TID, movement_type="EGR")
        assert len(result_ing["items"]) == 1
        assert result_egr["items"] == []

    def test_filter_by_date_from(self, db, test_user, user_accounts, user_categories):
        _make_ing(db, test_user, user_accounts, user_categories, mov_date="2026-05-01")
        _make_ing(db, test_user, user_accounts, user_categories, mov_date="2026-06-15")
        result = build_history(db, USER_TID, date_from="2026-06-01")
        assert all(item["movement_date"] >= "2026-06-01" for item in result["items"])

    def test_filter_by_amount_min(self, db, test_user, user_accounts, user_categories):
        _make_ing(db, test_user, user_accounts, user_categories, amount=50.0)
        _make_ing(db, test_user, user_accounts, user_categories, amount=500.0)
        result = build_history(db, USER_TID, amount_min=100.0)
        assert all(item["amount"] >= 100.0 for item in result["items"])

    def test_history_item_has_required_fields(self, db, test_user, user_accounts, user_categories):
        _make_ing(db, test_user, user_accounts, user_categories)
        result = build_history(db, USER_TID)
        item = result["items"][0]
        for field in ("id", "movement_type", "movement_date", "amount", "subtype"):
            assert field in item, f"Campo faltante: {field}"
