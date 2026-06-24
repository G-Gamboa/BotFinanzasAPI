"""
Capa 1: Tests de schemas — verifican que ResponseModel con extra='forbid'
detecta inmediatamente cuando un servicio devuelve un campo no declarado.

Este fue el bug real: CreditCardBalanceItem no tenía los campos
balance_at_close_gtq / pending_to_pay_gtq / etc., Pydantic los descartaba
silenciosamente y la app mostraba cero.
"""
import pytest
from pydantic import ValidationError

from app.schemas.finance import (
    CreditCardBalanceItem,
    CreditCardBalancesResponse,
    DebtItem,
    NetoResponse,
    SavingsGoalDashItem,
)
from app.schemas.history import HistoryItem, HistoryResponse
from app.schemas.savings import SavingsGoalItem, SavingsGoalActionResponse
from app.schemas.preferences import PreferencesResponse, PreferencesUpdateResponse

# ── Helpers ──────────────────────────────────────────────────────────────────

VALID_TC_ITEM = {
    "id": 1,
    "name": "Visa BI",
    "tc_type": "GTQ",
    "balance": 500.0,
    "balance_gtq": 500.0,
    "regular_balance": 500.0,
    "visacuota_balance": 0.0,
    "balance_at_close_gtq": 121.42,
    "pending_to_pay_gtq": 121.42,
}

VALID_HISTORY_ITEM = {
    "id": 1,
    "movement_type": "EGR",
    "movement_date": "2026-06-01",
    "subtype": "NORMAL",
    "amount": 100.0,
    "category_name": "Alimentación",
    "payment_method": "cash",
    "note": None,
    "is_void": False,
}


# ── CreditCardBalanceItem ─────────────────────────────────────────────────────

class TestCreditCardBalanceItem:
    def test_valid_data_passes(self):
        item = CreditCardBalanceItem(**VALID_TC_ITEM)
        assert item.balance_at_close_gtq == 121.42
        assert item.pending_to_pay_gtq == 121.42

    def test_extra_field_raises(self):
        """Reproduce el bug original: campo nuevo en servicio no declarado en schema."""
        with pytest.raises(ValidationError) as exc_info:
            CreditCardBalanceItem(**VALID_TC_ITEM, campo_nuevo_del_servicio=999)
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_optional_fields_default_to_none(self):
        item = CreditCardBalanceItem(**VALID_TC_ITEM)
        assert item.balance_at_close_gtq == 121.42
        assert item.billing_close_day is None
        assert item.payment_due_day is None
        assert item.pending_usd_portion is None

    def test_missing_required_field_raises(self):
        data = {k: v for k, v in VALID_TC_ITEM.items() if k != "balance_gtq"}
        with pytest.raises(ValidationError):
            CreditCardBalanceItem(**data)


# ── DebtItem ──────────────────────────────────────────────────────────────────

class TestDebtItem:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            DebtItem(
                id=1, name="Préstamo", creditor="Banco",
                due_date="2026-12-31", installment_amount=500.0,
                total_installments=12, paid_installments=3,
                pending_installments=9, saldo_pendiente=4500.0,
                status="active", campo_extra="sorpresa",
            )


# ── NetoResponse ──────────────────────────────────────────────────────────────

class TestNetoResponse:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            NetoResponse(
                patrimonio_bruto=10000.0,
                pasivos=2000.0,
                patrimonio_neto=8000.0,
                campo_inesperado=True,
            )

    def test_valid_with_defaults(self):
        neto = NetoResponse(
            patrimonio_bruto=10000.0,
            pasivos=2000.0,
            patrimonio_neto=8000.0,
        )
        assert neto.compromiso_visacuotas == 0.0
        assert neto.patrimonio_neto_ajustado == 0.0


# ── SavingsGoalDashItem ───────────────────────────────────────────────────────

class TestSavingsGoalDashItem:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            SavingsGoalDashItem(
                id=1, name="Vacaciones", target_amount=5000.0,
                current_amount=1000.0, is_active=True,
                campo_nuevo="valor",
            )


# ── HistoryItem ───────────────────────────────────────────────────────────────

class TestHistoryItem:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            HistoryItem(**VALID_HISTORY_ITEM, campo_extra="oops")

    def test_valid_passes(self):
        item = HistoryItem(**VALID_HISTORY_ITEM)
        assert item.amount == 100.0
        assert item.subtype == "NORMAL"
        assert item.record_type == "movement"  # default

    def test_account_name_not_a_field(self):
        """account_name no es campo de HistoryItem (es source_account / target_account)."""
        with pytest.raises(ValidationError):
            HistoryItem(**VALID_HISTORY_ITEM, account_name="Efectivo")


# ── PreferencesResponse ───────────────────────────────────────────────────────

class TestPreferencesResponse:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            PreferencesResponse(
                telegram_user_id=123,
                show_amounts_default=False,
                default_tab="movimientos",
                usd_to_gtq=7.7,
                campo_extra="valor",
            )

    def test_valid_passes(self):
        prefs = PreferencesResponse(
            telegram_user_id=123,
            show_amounts_default=False,
            default_tab="movimientos",
            usd_to_gtq=7.7,
        )
        assert prefs.theme_key is None


# ── SavingsGoalActionResponse ─────────────────────────────────────────────────

class TestSavingsGoalActionResponse:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            SavingsGoalActionResponse(id=1, ok=True, message="ok", extra="no")

    def test_valid_passes(self):
        r = SavingsGoalActionResponse(id=1, ok=True, message="Meta creada.")
        assert r.ok is True
