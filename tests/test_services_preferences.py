"""Tests para preferences_service."""
import pytest

from app.services.preferences_service import (
    get_preferences,
    update_preferences,
    get_or_create_user_settings,
    VALID_TABS,
)


USER_TID = 999_999_999


class TestGetOrCreateUserSettings:
    def test_returns_existing_settings(self, db, test_user):
        settings = get_or_create_user_settings(db, test_user.id)
        assert settings.user_id == test_user.id

    def test_creates_if_missing(self, db, test_user):
        # Eliminar settings existentes del test_user para forzar creación
        from sqlalchemy import delete
        from app.db.models import UserSetting
        db.execute(delete(UserSetting).where(UserSetting.user_id == test_user.id))
        db.commit()

        settings = get_or_create_user_settings(db, test_user.id)
        assert float(settings.usd_to_gtq) == pytest.approx(7.7)
        assert settings.default_tab == "movimientos"


class TestGetPreferences:
    def test_returns_all_fields(self, db, test_user):
        result = get_preferences(db, USER_TID)
        assert result["telegram_user_id"] == USER_TID
        assert "show_amounts_default" in result
        assert "default_tab" in result
        assert "usd_to_gtq" in result
        assert "theme_key" in result

    def test_usd_is_float(self, db, test_user):
        result = get_preferences(db, USER_TID)
        assert isinstance(result["usd_to_gtq"], float)

    def test_prestamos_tab_blocked_without_loans(self, db, test_user):
        test_user.can_use_loans = False
        db.commit()
        from app.db.models import UserSetting
        from sqlalchemy import select
        settings = db.scalar(select(UserSetting).where(UserSetting.user_id == test_user.id))
        settings.default_tab = "prestamos"
        db.commit()

        result = get_preferences(db, USER_TID)
        assert result["default_tab"] == "movimientos"

    def test_user_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Usuario no encontrado"):
            get_preferences(db, 0)

    def test_tab_order_parsed_from_json(self, db, test_user):
        import json
        from app.db.models import UserSetting
        from sqlalchemy import select
        s = db.scalar(select(UserSetting).where(UserSetting.user_id == test_user.id))
        s.tab_order = json.dumps(["movimientos", "historial"])
        db.commit()

        result = get_preferences(db, USER_TID)
        assert result["tab_order"] == ["movimientos", "historial"]

    def test_invalid_tab_order_json_returns_none(self, db, test_user):
        from app.db.models import UserSetting
        from sqlalchemy import select
        s = db.scalar(select(UserSetting).where(UserSetting.user_id == test_user.id))
        s.tab_order = "not-valid-json{"
        db.commit()

        result = get_preferences(db, USER_TID)
        assert result["tab_order"] is None


class TestUpdatePreferences:
    def test_updates_simple_fields(self, db, test_user):
        update_preferences(
            db, USER_TID,
            show_amounts_default=True,
            default_tab="dashboard",
            usd_to_gtq=8.0,
            theme_key="dark",
        )
        result = get_preferences(db, USER_TID)
        assert result["show_amounts_default"] is True
        assert result["default_tab"] == "dashboard"
        assert result["usd_to_gtq"] == 8.0
        assert result["theme_key"] == "dark"

    def test_prestamos_tab_blocked_without_loans(self, db, test_user):
        test_user.can_use_loans = False
        db.commit()
        with pytest.raises(ValueError, match="préstamos"):
            update_preferences(
                db, USER_TID,
                show_amounts_default=False,
                default_tab="prestamos",
                usd_to_gtq=7.7,
                theme_key=None,
            )

    def test_prestamos_tab_allowed_with_loans(self, db, test_user):
        # test_user.can_use_loans = True por defecto
        update_preferences(
            db, USER_TID,
            show_amounts_default=False,
            default_tab="prestamos",
            usd_to_gtq=7.7,
            theme_key=None,
        )
        result = get_preferences(db, USER_TID)
        assert result["default_tab"] == "prestamos"

    def test_tab_order_sanitized(self, db, test_user):
        update_preferences(
            db, USER_TID,
            show_amounts_default=False,
            default_tab="movimientos",
            usd_to_gtq=7.7,
            theme_key=None,
            tab_order=["movimientos", "historial", "invalid_tab", "movimientos"],
        )
        result = get_preferences(db, USER_TID)
        # invalid_tab eliminado, duplicado eliminado
        assert result["tab_order"] == ["movimientos", "historial"]

    def test_tab_order_none_clears_field(self, db, test_user):
        update_preferences(
            db, USER_TID,
            show_amounts_default=False,
            default_tab="movimientos",
            usd_to_gtq=7.7,
            theme_key=None,
            tab_order=None,
        )
        result = get_preferences(db, USER_TID)
        assert result["tab_order"] is None

    def test_all_valid_tabs_accepted(self, db, test_user):
        tabs = sorted(VALID_TABS)  # all valid, no duplicates
        update_preferences(
            db, USER_TID,
            show_amounts_default=False,
            default_tab="movimientos",
            usd_to_gtq=7.7,
            theme_key=None,
            tab_order=tabs,
        )
        result = get_preferences(db, USER_TID)
        # Todos deben estar presentes (aunque el orden puede variar)
        assert set(result["tab_order"]) == VALID_TABS
