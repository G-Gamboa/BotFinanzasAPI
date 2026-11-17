"""Comparación del estado de cuenta del banco con la app (sin PDF: el lector se prueba aparte)."""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Account, CreditCardInstallmentPlan, CreditCardPayment, Loan, LoanPayment, LoanPerson, Movement,
)
from app.services.bi_statement_parser import _column_sides
from app.services.finance_db_service import _add_months, _last_close_date, today_gt
from app.services.statement_reconcile_service import reconcile
from app.security.telegram_auth import get_current_telegram_auth

USER_TID = 999_999_999


@pytest.fixture
def setup(db, test_user):
    today = today_gt()
    day = min(today.day, 28)
    close = _last_close_date(today, day)
    card = Account(user_id=test_user.id, name="TC Bi", account_type="credit_card", currency="GTQ",
                   is_active=True, is_system=False, sort_order=1, billing_close_day=day, payment_due_day=7,
                   tc_type="MIXTO", tc_exchange_rate=8, credit_limit=5600)
    bank = Account(user_id=test_user.id, name="Banco BI", account_type="bank", currency="GTQ",
                   is_active=True, is_system=False, sort_order=2)
    db.add_all([card, bank])
    db.flush()
    plan = CreditCardInstallmentPlan(user_id=test_user.id, credit_card_account_id=card.id, name="Tenis",
                                     total_amount=1375.02, total_installments=6, monthly_amount=229.17,
                                     purchase_date=close - timedelta(days=150),
                                     first_charge_date=_add_months(close, -4), status="active", is_active=True,
                                     created_at=datetime.now(timezone.utc))
    db.add(plan)
    db.flush()
    d = lambda n: close - timedelta(days=n)

    def mov(when, amount, note, **kw):
        db.add(Movement(user_id=test_user.id, movement_type="EGR", movement_date=when, amount=amount, note=note,
                        payment_method="credit_card", credit_card_account_id=card.id, **kw))

    mov(d(8), 832.41, "Akisí")                  # el banco lo parte en 780.38 + 52.03
    mov(d(6), 1575, "Préstamo")                 # el banco: transferencia 1,500 + comisión 75
    mov(d(5), 124, "Pizza")                     # exacto
    mov(d(4), 99.99, "Nunca llegó al banco")    # solo en la app
    mov(d(1), 236, "Pastel")                    # exacto, un día de diferencia
    mov(close, 35, "Cuetes")                    # el banco aún no lo procesa
    mov(d(32), 22, "Croissant")                 # del ciclo anterior, el banco lo procesó tarde
    mov(d(7), 160, "Claude", amount_foreign=20)  # dólares
    mov(close, 108.33, "Visacuota: Regalo")     # junto con la siguiente = una línea del banco
    mov(close, 6.67, "Visacuota: Empaque")
    for n in range(5):                          # cuotas 1 a 5 del plan
        mov(_add_months(close, n - 4), 229.17, "Visacuota: Tenis", installment_plan_id=plan.id)
    db.add(CreditCardPayment(credit_card_account_id=card.id, user_id=test_user.id, amount=3053.16,
                             payment_date=d(8), account_id=bank.id))
    person = LoanPerson(user_id=test_user.id, name="Akisí", is_active=True)
    db.add(person)
    db.flush()
    loan = Loan(user_id=test_user.id, loan_person_id=person.id, loan_type="lent", principal_amount=1601,
                loan_date=d(9), status="active", note="Akisí", source_tc_account_id=card.id)
    db.add(loan)
    db.flush()
    db.add(LoanPayment(loan_id=loan.id, user_id=test_user.id, amount=1601, payment_date=d(6), account_id=card.id,
                       note="Akisí"))
    db.commit()

    iso = lambda n: d(n).isoformat()
    line = lambda n, desc, amount, side="debit", cur="GTQ", section="compras", inst=None: {
        "section": section, "currency": cur, "side": side, "op_date": iso(max(n - 1, 0)), "date": iso(n),
        "description": desc, "amount": amount, "installment": inst}
    statement = {
        "close_date": close.isoformat(), "payment_date": _add_months(close, 1).isoformat(),
        "card_last4": "3327", "contado_q": 6325.66, "contado_usd": 32.99, "checks_ok": True, "problems": [],
        "lines": [
            line(32, "SAN MARTIN", 22.0),
            line(8, "PRONET PGW GT", 780.38), line(8, "PRONET PGW GT", 52.03),
            line(6, "BI-APP QUET. A QUET.", 1500.0),
            line(6, "COMISION POR TRANSFEREN", 75.0, section="otros_cargos"),
            line(5, "LITTLE CAESARS", 124.0),
            line(2, "PATSY PRADERA", 236.0),
            line(3, "TIENDA DESCONOCIDA", 45.5),
            line(8, "GRACIAS POR SU PAGO", 3053.16, side="credit"),
            line(6, "GRACIAS POR SU PAGO", 1601.0, side="credit"),
            line(7, "ANTHROPIC* CLAUDE", 20.0, cur="USD"),
            line(0, "PACIFIKO PGW", 115.0, section="cuotas", inst={"number": 1, "total": 3}),
            line(0, "THE PUMA STORE", 229.17, section="cuotas", inst={"number": 5, "total": 6}),
        ],
    }
    return {"card": card, "statement": statement, "close": close}


def test_reconcile_matches_exact_split_and_late_lines(db, setup):
    res = reconcile(db, USER_TID, setup["card"].id, setup["statement"])
    hows = {(g["how"], tuple(sorted(b["amount"] for b in g["bank"])), tuple(sorted(a["amount"] for a in g["app"])))
            for g in res["matched"]}
    assert ("partido en el banco", (52.03, 780.38), (832.41,)) in hows
    assert ("partido en el banco", (75.0, 1500.0), (1575.0,)) in hows
    assert ("partido en la app", (115.0,), (6.67, 108.33)) in hows
    assert ("exacto", (22.0,), (22.0,)) in hows            # procesado tarde, igual cuadra
    assert ("exacto", (236.0,), (236.0,)) in hows
    assert ("exacto", (20.0,), (20.0,)) in hows            # dólares contra dólares
    assert ("exacto", (3053.16,), (3053.16,)) in hows      # abono
    assert ("exacto", (1601.0,), (1601.0,)) in hows        # cobro de préstamo abonado a la tarjeta

    assert [b["description"] for b in res["bank_only"]] == ["TIENDA DESCONOCIDA"]
    assert [a["label"] for a in res["app_only"]] == ["Nunca llegó al banco"]
    assert [a["label"] for a in res["pending_next"]] == ["Cuetes"]


def test_reconcile_checks_installment_counter_and_contado(db, setup):
    res = reconcile(db, USER_TID, setup["card"].id, setup["statement"])
    tenis = next(i for i in res["installments"] if i["plan_name"] == "Tenis")
    assert tenis["bank_number"] == 5 and tenis["app_number"] == 5 and tenis["ok"] is True
    c = res["contado"]
    assert c["current_cycle"] is True and c["bank_q"] == 6325.66 and c["bank_usd"] == 32.99
    assert c["app_q"] is not None and c["app_usd"] == 20.0


def test_reconcile_warns_when_card_does_not_fit(db, setup):
    card = setup["card"]
    card.billing_close_day = 1 if setup["close"].day != 1 else 2
    card.tc_type = "GTQ"
    db.commit()
    res = reconcile(db, USER_TID, card.id, setup["statement"])
    assert any("corta el día" in w for w in res["warnings"])
    assert any("trae dólares" in w for w in res["warnings"])
    assert res["contado"]["current_cycle"] is False


def test_column_sides_splits_debit_and_credit_by_position():
    text = "\n".join([
        "14/10/26   12/10/26   SAN MARTIN ANDARIA GT" + " " * 40 + "22.00",
        "04/11/26   04/11/26   GRACIAS POR SU PAGO" + " " * 63 + "248.00",
        "07/11/26   07/11/26   BI-APP QUET. A QUET." + " " * 38 + "1,500.00",
    ])
    sides = _column_sides([text])
    assert sides[("14/10/26", "12/10/26", "SAN MARTIN ANDARIA GT", 22.0)] == ["debit"]
    assert sides[("04/11/26", "04/11/26", "GRACIAS POR SU PAGO", 248.0)] == ["credit"]
    assert sides[("07/11/26", "07/11/26", "BI-APP QUET. A QUET.", 1500.0)] == ["debit"]


def test_endpoint_rejects_non_pdf(client, setup):
    from app.main import app
    app.dependency_overrides[get_current_telegram_auth] = lambda: {"user": {"id": USER_TID}}
    r = client.post(f"/tc/{setup['card'].id}/estado-cuenta", json={
        "telegram_user_id": USER_TID, "pdf_base64": base64.b64encode(b"hola, no soy un pdf").decode()})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
