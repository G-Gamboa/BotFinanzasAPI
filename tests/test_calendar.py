"""Calendario, endpoint de arranque y carga inicial."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.calendar_seed import SEED_TELEGRAM_USER_ID, seed_admin_calendar
from app.db.models import (
    Account, CreditCardPayment, Debt, Movement, ScheduledItem, ScheduledOccurrence, User, UserSetting,
)
from app.security.telegram_auth import get_current_telegram_auth
from app.services.availability_service import build_disponibles
from app.services.calendar_service import build_calendar, item_dates, next_payment_date
from app.services.finance_db_service import build_cc_balances, build_dashboard, build_debts, today_gt
from tests.finance_dataset import seed_finance_dataset

USER_ID = 999_999_999


@pytest.fixture
def data(db, test_user):
    return seed_finance_dataset(db, test_user)


@pytest.fixture
def auth_client(client):
    from app.main import app
    app.dependency_overrides[get_current_telegram_auth] = lambda: {"user": {"id": USER_ID}}
    return client


def _item(**kw):
    base = dict(kind="ingreso", concept="X", amount=100, currency="GTQ", recurrence="none", is_active=True)
    return ScheduledItem(**{**base, **kw})


# ── Fechas ────────────────────────────────────────────────────────────────────

def test_item_dates_monthly_clamps_and_respects_end():
    item = _item(start_date=date(2026, 1, 31), recurrence="monthly", end_date=date(2026, 4, 30))
    assert item_dates(item, date(2026, 2, 1), date(2026, 2, 28)) == [date(2026, 2, 28)]
    assert item_dates(item, date(2026, 5, 1), date(2026, 5, 31)) == []


def test_item_dates_biweekly_and_single():
    item = _item(start_date=date(2026, 11, 6), recurrence="biweekly")
    assert item_dates(item, date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 6), date(2026, 11, 20)]
    once = _item(start_date=date(2026, 11, 15))
    assert item_dates(once, date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 15)]
    assert item_dates(once, date(2026, 12, 1), date(2026, 12, 31)) == []


def test_next_payment_date_rolls_to_next_month():
    assert next_payment_date(date(2026, 11, 13), 7) == date(2026, 12, 7)
    assert next_payment_date(date(2026, 12, 13), 7) == date(2027, 1, 7)
    assert next_payment_date(date(2026, 11, 3), 20) == date(2026, 11, 20)


# ── Arranque ──────────────────────────────────────────────────────────────────

def test_bootstrap_matches_individual_builders(auth_client, db, data):
    r = auth_client.get(f"/bootstrap/{USER_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["registered"] is True
    db.expire_all()
    assert body["dashboard"]["networth"] == build_dashboard(db, USER_ID, 7.7)["networth"]
    assert body["dashboard"]["neto"] == build_dashboard(db, USER_ID, 7.7)["neto"]
    assert body["disponibles"] == build_disponibles(db, USER_ID)
    assert body["deudas"] == build_debts(db, USER_ID)
    assert body["tcBalances"]["items"] == build_cc_balances(db, USER_ID)
    assert {"catalogos", "cuentas", "categorias", "loanPeople", "preferencias",
            "installmentPlans", "presupuesto", "calendario"} <= set(body)
    assert len(body["installmentPlans"]["items"]) == 2


def test_bootstrap_rejects_other_user(auth_client, data):
    assert auth_client.get("/bootstrap/123").status_code == 403


def test_bootstrap_unregistered_user(client):
    from app.main import app
    app.dependency_overrides[get_current_telegram_auth] = lambda: {"user": {"id": 555}}
    r = client.get("/bootstrap/555")
    assert r.status_code == 200
    assert r.json() == {"registered": False, "days_remaining": None}


# ── Calendario ────────────────────────────────────────────────────────────────

def test_calendar_derives_debts_cards_and_visacuotas(db, test_user, data):
    today = today_gt()
    cal = build_calendar(db, USER_ID, today.year, today.month)
    sources = {r["source"] for r in cal["items"]}
    assert "card" in sources
    paid = [r for r in cal["items"] if r["key"].startswith("dp:")]
    assert all(r["done"] for r in paid)
    assert cal["summary"]["is_current_month"] is True
    card = next(c for c in cal["cards"] if c["name"] == "Visa Q")
    assert card["pending_gtq"] == 2200.0
    assert card["loans_gtq"] == 500.0


def test_debt_projection_only_first_is_confirmable(db, test_user, data):
    debt = data["deuda"]
    months = set()
    rows = []
    for n in range(0, 6):
        d = debt.due_date + timedelta(days=31 * n)
        if (d.year, d.month) in months:
            continue
        months.add((d.year, d.month))
        rows += [r for r in build_calendar(db, USER_ID, d.year, d.month)["items"]
                 if r["key"].startswith(f"d:{debt.id}:")]
    assert len(rows) == 4  # 6 cuotas, 2 pagadas
    assert [r["action"] for r in rows] == ["confirm", None, None, None]


def _create(client, **kw):
    payload = {"telegram_user_id": USER_ID, "kind": "ingreso", "concept": "Quincena", "amount": 3168.16,
               "start_date": today_gt().isoformat(), **kw}
    r = client.post("/calendario/items", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _month(client):
    r = client.get(f"/calendario/{USER_ID}")
    assert r.status_code == 200, r.text
    return r.json()


def test_confirm_income_creates_movement_and_void_reopens(client, db, data):
    today = today_gt().isoformat()
    item_id = _create(client, recurrence="monthly")
    row = next(r for r in _month(client)["items"] if r["item_id"] == item_id)
    assert row["action"] == "confirm" and row["recurring"] is True

    r = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": item_id, "due_date": today, "payment_date": today,
        "amount": 3000, "category_name": "Salario", "payment_method": "transfer", "account_name": "Banco BI",
    })
    assert r.status_code == 200, r.text
    movement_id = r.json()["record_id"]
    movement = db.get(Movement, movement_id)
    assert movement.movement_type == "ING" and float(movement.amount) == 3000

    row = next(r for r in _month(client)["items"] if r["item_id"] == item_id)
    assert row["done"] is True and row["category_name"] == "Salario" and row["account_name"] == "Banco BI"

    again = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": item_id, "due_date": today, "payment_date": today,
        "amount": 3000, "category_name": "Salario", "payment_method": "transfer", "account_name": "Banco BI",
    })
    assert again.status_code == 400

    assert client.patch(f"/movimientos/{movement_id}/anular",
                        json={"telegram_user_id": USER_ID, "reason": "x"}).status_code == 200
    row = next(r for r in _month(client)["items"] if r["item_id"] == item_id)
    assert row["done"] is False and row["action"] == "confirm"


def test_confirm_abono_usd_and_card_charge(client, db, data):
    today = today_gt().isoformat()
    tc = db.scalar(select(Account).where(Account.name == "Visa Mixta"))
    abono = _create(client, kind="abono", concept="Dólares del corte", amount=20, currency="USD",
                    credit_card_account_id=tc.id)
    r = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": abono, "due_date": today, "payment_date": today,
        "amount": 20, "amount_gtq": 155.5, "account_name": "Banco BI", "credit_card_account_id": tc.id,
    })
    assert r.status_code == 200, r.text
    payment = db.get(CreditCardPayment, r.json()["record_id"])
    assert float(payment.amount) == 155.5 and float(payment.amount_usd) == 20

    cargo = _create(client, kind="cargo_tc", concept="Meta", amount=50, currency="USD",
                    credit_card_account_id=tc.id)
    r = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": cargo, "due_date": today, "payment_date": today,
        "amount": 50, "category_name": "Servicios", "credit_card_account_id": tc.id,
    })
    assert r.status_code == 200, r.text
    movement = db.get(Movement, r.json()["record_id"])
    assert float(movement.amount_foreign) == 50 and float(movement.amount) == 390.0
    assert movement.credit_card_account_id == tc.id


def test_needs_amount_then_skip_occurrence(client, db, data):
    today = today_gt().isoformat()
    luz = _create(client, kind="cargo_tc", concept="Luz", amount=None, recurrence="monthly")
    row = next(r for r in _month(client)["items"] if r["item_id"] == luz)
    assert row["needs_amount"] is True

    r = client.patch("/calendario/ocurrencia", json={
        "telegram_user_id": USER_ID, "item_id": luz, "due_date": today, "amount": 618})
    assert r.status_code == 200, r.text
    row = next(r for r in _month(client)["items"] if r["item_id"] == luz)
    assert row["amount"] == 618 and row["needs_amount"] is False

    r = client.patch("/calendario/ocurrencia", json={
        "telegram_user_id": USER_ID, "item_id": luz, "due_date": today, "skip": True})
    assert r.status_code == 200
    assert not [r for r in _month(client)["items"] if r["item_id"] == luz]


def test_undated_item_gets_dated_on_confirm(client, db, data):
    today = today_gt().isoformat()
    boa = _create(client, concept="Boa Estudio", amount=1800, start_date=None)
    assert [r for r in _month(client)["undated"] if r["item_id"] == boa]
    r = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": boa, "due_date": None, "payment_date": today,
        "amount": 1800, "category_name": "Salario", "payment_method": "cash",
    })
    assert r.status_code == 200, r.text
    month = _month(client)
    assert not [r for r in month["undated"] if r["item_id"] == boa]
    assert next(r for r in month["items"] if r["item_id"] == boa)["done"] is True


def test_reminder_done_and_undo(client, data):
    today = today_gt().isoformat()
    rec = _create(client, kind="recordatorio", concept="Revisar estado de cuenta", amount=None)
    body = {"telegram_user_id": USER_ID, "item_id": rec, "due_date": today, "payment_date": today}
    assert client.post("/calendario/confirmar", json=body).status_code == 200
    assert next(r for r in _month(client)["items"] if r["item_id"] == rec)["done"] is True
    r = client.patch("/calendario/ocurrencia", json={
        "telegram_user_id": USER_ID, "item_id": rec, "due_date": today, "undo": True})
    assert r.status_code == 200
    assert next(r for r in _month(client)["items"] if r["item_id"] == rec)["done"] is False


def test_confirm_debt_installment(client, db, data):
    debt_id = data["deuda"].id
    r = client.post("/calendario/confirmar-deuda", json={
        "telegram_user_id": USER_ID, "debt_id": debt_id, "payment_date": today_gt().isoformat(),
        "payment_method": "transfer", "account_name": "Banco BI"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Debt, debt_id).paid_installments == 3


def test_delete_item_and_notes(client, data):
    item_id = _create(client)
    assert client.delete(f"/calendario/items/{item_id}?telegram_user_id={USER_ID}").status_code == 200
    assert not [r for r in _month(client)["items"] if r["item_id"] == item_id]
    note = client.post("/calendario/notas", json={"telegram_user_id": USER_ID, "text": "Todo o nada"}).json()
    assert _month(client)["notes"] == [{"id": note["id"], "text": "Todo o nada"}]
    assert client.delete(f"/calendario/notas/{note['id']}?telegram_user_id={USER_ID}").status_code == 200
    assert _month(client)["notes"] == []


def test_planned_abonos_cover_card_payment(client, db, data):
    tc = data["tc_q"]
    _create(client, kind="abono", concept="Abonar de la quincena", amount=1500, credit_card_account_id=tc.id)
    card = next(c for c in _month(client)["cards"] if c["id"] == tc.id)
    assert card["planned_gtq"] == 1500.0
    assert card["gap_gtq"] == 700.0


# ── Carga inicial ─────────────────────────────────────────────────────────────

def test_seed_applies_once_and_skips_known_debts(db):
    now = datetime.now(timezone.utc)
    user = User(telegram_user_id=SEED_TELEGRAM_USER_ID, first_name="G", is_active=True,
                can_use_loans=True, theme_key="neutral")
    db.add(user)
    db.flush()
    db.add(UserSetting(user_id=user.id, preferred_currency="GTQ", usd_to_gtq=7.7, hide_amounts_default=False,
                       show_amounts_default=False, default_tab="movimientos", created_at=now, updated_at=now))
    card = Account(user_id=user.id, name="TC Bi", account_type="credit_card", currency="GTQ", is_active=True,
                   is_system=False, sort_order=1, billing_close_day=13, payment_due_day=7, tc_type="MIXTO",
                   tc_exchange_rate=7.7733)
    db.add(card)
    db.add(Debt(user_id=user.id, name="Moto", creditor="Banco", due_date=date(2026, 11, 24),
                installment_amount=312.5, total_installments=6, paid_installments=2,
                status="active", payment_frequency="monthly"))
    db.commit()

    assert seed_admin_calendar(db) is True
    items = db.scalars(select(ScheduledItem).where(ScheduledItem.user_id == user.id)).all()
    concepts = [i.concept for i in items]
    assert concepts.count("Quincena") == 2
    assert "Corte de la tarjeta Bi" not in concepts          # la tarjeta ya tiene día de corte
    amounts = {float(i.amount) for i in items if i.concept == "Pago de deuda"}
    assert amounts == {900.0}                                 # la de 312.50 ya existe como deuda
    assert all(i.credit_card_account_id == card.id for i in items if i.kind in ("abono", "cargo_tc"))
    luz = next(i for i in items if i.concept == "Luz")
    occ = db.scalar(select(ScheduledOccurrence).where(ScheduledOccurrence.item_id == luz.id))
    assert float(occ.amount) == 618 and occ.due_date == date(2026, 11, 25)

    assert seed_admin_calendar(db) is False
    assert len(db.scalars(select(ScheduledItem).where(ScheduledItem.user_id == user.id)).all()) == len(items)

    nov = build_calendar(db, SEED_TELEGRAM_USER_ID, 2026, 11)
    assert nov["notes"][0]["text"].startswith("Todo o nada")
    assert next(r for r in nov["items"] if r["concept"] == "Luz")["amount"] == 618
    assert len(nov["undated"]) == 4


def test_seed_without_user_is_noop(db):
    assert seed_admin_calendar(db) is False


# ── Confirmar sin registrar ───────────────────────────────────────────────────

def test_confirm_without_registering_creates_no_movement(client, db, data):
    today = today_gt().isoformat()
    item_id = _create(client)
    before = len(db.scalars(select(Movement)).all())
    r = client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": item_id, "due_date": today, "payment_date": today,
        "create_record": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["record_id"] is None
    db.expire_all()
    assert len(db.scalars(select(Movement)).all()) == before
    row = next(r for r in _month(client)["items"] if r["item_id"] == item_id)
    assert row["done"] is True and row["record_type"] is None

    r = client.patch("/calendario/ocurrencia", json={
        "telegram_user_id": USER_ID, "item_id": item_id, "due_date": today, "undo": True})
    assert r.status_code == 200
    assert next(r for r in _month(client)["items"] if r["item_id"] == item_id)["done"] is False


# ── Saldo día a día ───────────────────────────────────────────────────────────

def test_projection_runs_balance_and_flags_negative():
    from app.services.calendar_service import build_projection

    def row(day, kind, amount, done=False, method=None):
        return {"date": day, "kind": kind, "amount_gtq": amount, "done": done, "payment_method": method}

    today = date(2026, 11, 14)
    rows = [
        row("2026-11-10", "pago", 300),                       # atrasado: cuenta como hoy
        row("2026-11-15", "pago", 900),
        row("2026-11-15", "cargo_tc", 500),                   # no mueve efectivo
        row("2026-11-18", "pago", 200, method="credit_card"),  # sale de la tarjeta
        row("2026-11-20", "ingreso", 3000),
        row("2026-11-22", "abono", 1500),
        row("2026-11-25", "ingreso", 100, done=True),
        row("2026-12-05", "ingreso", 999),                    # fuera del rango
    ]
    p = build_projection(1000.0, rows, today, date(2026, 11, 30))
    assert [(d["date"], d["balance"]) for d in p["days"]] == [
        ("2026-11-14", 700.0), ("2026-11-15", -200.0), ("2026-11-20", 2800.0), ("2026-11-22", 1300.0),
    ]
    assert p["first_negative"] == "2026-11-15"
    assert p["lowest"] == {"date": "2026-11-15", "balance": -200.0}
    assert p["end_balance"] == 1300.0
    assert build_projection(1000.0, rows, today, date(2026, 10, 31)) is None


def test_calendar_includes_projection_for_current_month(client, data):
    month = _month(client)
    assert month["projection"]["start_balance"] == month["summary"]["cash_now"]
    assert month["summary"]["projected_end"] == month["projection"]["end_balance"]


# ── Cierre de mes ─────────────────────────────────────────────────────────────

def test_past_month_has_close_with_unconfirmed(client, db, test_user, data):
    today = today_gt()
    prev = (today.replace(day=1) - timedelta(days=1)).replace(day=10)
    _create(client, kind="pago", concept="Renta vieja", amount=700, start_date=prev.isoformat())
    r = client.get(f"/calendario/{USER_ID}?year={prev.year}&month={prev.month}")
    close = r.json()["close"]
    assert close["month"] == prev.month
    assert close["balance"] == round(close["ingresos"] - close["egresos"], 2)
    assert [u["concept"] for u in close["unconfirmed"]] == ["Renta vieja"]
    assert r.json()["projection"] is None


# ── Recordatorios por Telegram ────────────────────────────────────────────────

def test_daily_reminder_lists_today_and_late(client, db, data):
    from app.services.calendar_reminders import build_daily_reminder

    today = today_gt()
    _create(client, concept="Quincena de prueba", amount=3168.16)
    _create(client, kind="abono", concept="Abono viejo", amount=135,
            start_date=(today - timedelta(days=2)).isoformat(), credit_card_account_id=data["tc_q"].id)
    _create(client, kind="pago", concept="Muy viejo", amount=50,
            start_date=(today - timedelta(days=20)).isoformat())
    done = _create(client, kind="recordatorio", concept="Ya hecho", amount=None)
    client.post("/calendario/confirmar", json={
        "telegram_user_id": USER_ID, "item_id": done, "due_date": today.isoformat(),
        "payment_date": today.isoformat()})

    db.expire_all()
    text = build_daily_reminder(db, USER_ID, today)
    assert "Ingreso: Quincena de prueba · Q3,168.16" in text
    assert "Abono a tarjeta: Abono viejo · Q135.00 (era el" in text
    assert "Muy viejo" not in text          # más de una semana: ya no se insiste
    assert "Ya hecho" not in text
    assert text.endswith("Confírmalos en la pestaña Calendario.")


def test_daily_reminder_is_none_when_nothing_due(db, test_user, user_accounts):
    from app.services.calendar_reminders import build_daily_reminder
    assert build_daily_reminder(db, USER_ID, date(2026, 11, 14)) is None


def test_month_close_message_on_day_one(client, db, data):
    from app.services.calendar_reminders import build_daily_reminder

    first = (today_gt().replace(day=1) + timedelta(days=32)).replace(day=1)
    db.expire_all()
    text = build_daily_reminder(db, USER_ID, first)
    assert "Cierre de" in text and "- Entró: Q" in text and "- Ahorro del mes: Q" in text


def test_notify_daily_sends_calendar_reminders(client, db, data, monkeypatch):
    from app.services import calendar_reminders, notification_service

    sent = []
    monkeypatch.setattr(calendar_reminders, "_send_plain", lambda token, chat_id, text: sent.append((chat_id, text)))
    monkeypatch.setattr(notification_service, "_telegram_send", lambda *a, **k: None)
    _create(client, concept="Quincena de prueba", amount=3168.16)
    r = client.post("/admin/notify-daily", headers={"Authorization": "Bearer test-secret"})
    assert r.status_code == 200
    assert r.json()["calendar"] == {"sent": 1, "errors": 0}
    assert sent[0][0] == USER_ID and "Quincena de prueba" in sent[0][1]
