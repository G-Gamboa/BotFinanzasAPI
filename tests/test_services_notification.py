"""Tests para notification_service.run_daily_tc_notifications."""
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from app.db.models import Account, Movement
from app.services.notification_service import (
    _telegram_send,
    run_daily_tc_notifications,
)


USER_TID = 999_999_999


# ── run_daily_tc_notifications ────────────────────────────────────────────────

class TestRunDailyTcNotifications:
    def test_no_tc_cards_returns_zero(self, db, test_user):
        result = run_daily_tc_notifications(db)
        assert result["sent"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert "date" in result

    def test_tc_with_no_matching_date_no_sent(self, db, test_user):
        # Tarjeta con fechas que nunca coinciden con hoy
        cc = Account(
            user_id=test_user.id, name="Visa",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ",
            billing_close_day=1,   # corte el 1
            payment_due_day=1,     # pago el 1
        )
        db.add(cc)
        db.commit()
        # Si hoy no es día 1, ni 6 días antes del 1, ni 2 días antes → 0 enviados
        result = run_daily_tc_notifications(db)
        assert result["sent"] == 0

    def test_skipped_when_build_cc_balances_raises(self, db, test_user):
        with patch(
            "app.services.notification_service.build_cc_balances",
            side_effect=Exception("DB error"),
        ):
            result = run_daily_tc_notifications(db)
        assert result["skipped"] == 1

    def test_send_error_counted(self, db, test_user):
        """_telegram_send falla → errors++ pero no se propaga."""
        today = date(2026, 6, 24)
        cc = Account(
            user_id=test_user.id, name="Visa Test",
            account_type="credit_card", currency="GTQ",
            is_active=True, is_system=False, sort_order=10,
            tc_type="GTQ",
            billing_close_day=today.day,  # corte hoy → disparará notificación
            payment_due_day=today.day + 5 if today.day + 5 <= 28 else 28,
        )
        db.add(cc)
        db.commit()

        fake_tc_item = {
            "id": cc.id,
            "name": "Visa Test",
            "tc_type": "GTQ",
            "balance": 500.0,
            "balance_gtq": 500.0,
            "regular_balance": 500.0,
            "visacuota_balance": 0.0,
            "balance_at_close_gtq": 500.0,
            "pending_to_pay_gtq": 500.0,
            "billing_close_day": today.day,
            "payment_due_day": today.day + 5 if today.day + 5 <= 28 else 28,
        }

        with patch("app.services.notification_service.build_cc_balances", return_value=[fake_tc_item]), \
             patch("app.services.notification_service.today_gt", return_value=today), \
             patch("app.services.notification_service._telegram_send", side_effect=Exception("timeout")):
            result = run_daily_tc_notifications(db)

        assert result["errors"] >= 1

    def test_successful_send_counted(self, db, test_user):
        today = date(2026, 6, 24)
        fake_tc_item = {
            "name": "Visa Send",
            "tc_type": "GTQ",
            "balance": 300.0,
            "balance_gtq": 300.0,
            "regular_balance": 300.0,
            "visacuota_balance": 0.0,
            "balance_at_close_gtq": 300.0,
            "pending_to_pay_gtq": 300.0,
            "billing_close_day": today.day,   # corte hoy → mensaje enviado
            "payment_due_day": 28,
        }

        with patch("app.services.notification_service.build_cc_balances", return_value=[fake_tc_item]), \
             patch("app.services.notification_service.today_gt", return_value=today), \
             patch("app.services.notification_service._telegram_send") as mock_send:
            result = run_daily_tc_notifications(db)

        assert result["sent"] == 1
        assert result["errors"] == 0
        mock_send.assert_called_once()

    def test_result_has_correct_structure(self, db, test_user):
        result = run_daily_tc_notifications(db)
        assert set(result.keys()) == {"sent", "skipped", "errors", "date"}
        assert isinstance(result["sent"], int)
        assert isinstance(result["skipped"], int)
        assert isinstance(result["errors"], int)
