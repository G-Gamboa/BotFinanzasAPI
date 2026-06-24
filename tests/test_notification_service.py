"""
Capa 2: Tests unitarios de servicios — lógica de negocio pura, sin BD ni HTTP.
"""
from datetime import date

import pytest

from app.services.notification_service import _effective_day, _fmt_q


# ── _effective_day ────────────────────────────────────────────────────────────

class TestEffectiveDay:
    """Verifica que el día de corte/pago se clampea al último día del mes."""

    # Meses de 31 días: Enero(1), Marzo(3), Mayo(5), Julio(7),
    # Agosto(8), Octubre(10), Diciembre(12)
    def test_day_31_in_31_day_month_stays(self):
        assert _effective_day(date(2026, 1, 15), 31) == 31

    def test_day_31_in_june_clamps_to_30(self):
        # Junio tiene 30 días
        assert _effective_day(date(2026, 6, 15), 31) == 30

    def test_day_31_in_april_clamps_to_30(self):
        # Abril tiene 30 días
        assert _effective_day(date(2026, 4, 15), 31) == 30

    def test_day_31_in_february_non_leap_clamps_to_28(self):
        assert _effective_day(date(2025, 2, 1), 31) == 28

    def test_day_31_in_february_leap_clamps_to_29(self):
        # 2024 es bisiesto
        assert _effective_day(date(2024, 2, 1), 31) == 29

    def test_day_29_in_february_non_leap_clamps_to_28(self):
        assert _effective_day(date(2025, 2, 1), 29) == 28

    def test_day_29_in_february_leap_stays(self):
        assert _effective_day(date(2024, 2, 1), 29) == 29

    def test_day_28_always_valid(self):
        # Día 28 es válido en todos los meses
        for month in range(1, 13):
            assert _effective_day(date(2025, month, 1), 28) == 28

    def test_day_1_always_stays(self):
        assert _effective_day(date(2026, 2, 1), 1) == 1

    def test_normal_day_unchanged(self):
        assert _effective_day(date(2026, 3, 15), 15) == 15

    # Casos de borde: el día efectivo cae exactamente en el mes actual
    def test_june_close_day_30_stays(self):
        assert _effective_day(date(2026, 6, 1), 30) == 30

    def test_june_close_day_31_becomes_30_and_matches_notification(self):
        """Simula que hoy es 30 de junio y el corte está configurado en 31."""
        today = date(2026, 6, 30)
        configured = 31
        assert today.day == _effective_day(today, configured)


# ── _fmt_q ────────────────────────────────────────────────────────────────────

class TestFmtQ:
    def test_formats_with_two_decimals(self):
        assert _fmt_q(121.42) == "Q121.42"

    def test_formats_zero(self):
        assert _fmt_q(0.0) == "Q0.00"

    def test_formats_thousands(self):
        assert _fmt_q(1500.0) == "Q1,500.00"

    def test_formats_large_amount(self):
        assert _fmt_q(10_000.50) == "Q10,000.50"
