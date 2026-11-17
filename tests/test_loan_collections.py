"""Planes de cobro de préstamos en el Calendario."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import LoanCollectionPlan, LoanPayment, LoanPerson
from app.services.calendar_service import build_calendar
from app.services.debt_service import advance_due_date
from app.services.finance_context import FinanceContext
from app.services.finance_db_service import today_gt
from app.services.loan_collection_service import collection_rows, list_collections
from tests.finance_dataset import seed_finance_dataset

USER_ID = 999_999_999


@pytest.fixture
def data(db, test_user):
    d = seed_finance_dataset(db, test_user)
    d["luis"] = db.scalar(select(LoanPerson).where(LoanPerson.name == "Luis"))
    return d


def _save(client, person_id, concept, amount, days=5, frequency="monthly"):
    r = client.post("/prestamos/planes-cobro", json={
        "telegram_user_id": USER_ID, "loan_person_id": person_id, "concept": concept,
        "installment_amount": amount, "frequency": frequency,
        "next_due_date": (today_gt() + timedelta(days=days)).isoformat(),
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _rows(db, days_ahead=200):
    db.expire_all()
    today = today_gt()
    return collection_rows(FinanceContext(db, USER_ID), today - timedelta(days=60),
                           today + timedelta(days=days_ahead), today)


def test_list_includes_cash_tc_and_upcoming_visacuota(db, data):
    items = {(i["person"], i["concept"]): i for i in list_collections(db, USER_ID)["items"]}
    assert items[("Ana", "General")]["balance"] == 100.0
    assert items[("Ana", "Carro")]["balance"] == 350.0 and items[("Ana", "Carro")]["is_tc"] is False
    regalo = items[("Luis", "Regalo")]
    assert regalo["balance"] == 500.0 and regalo["is_tc"] is True and regalo["card_name"] == "Visa Q"
    cel = items[("Luis", "Cel Luis")]
    assert cel["balance"] == 0.0 and cel["upcoming"] == 1200.0
    assert cel["is_visacuota"] is True and cel["default_amount"] == 300.0
    assert all(i["plan"] is None for i in items.values())


def test_loans_without_plan_do_not_reach_the_calendar(db, data):
    today = today_gt()
    cal = build_calendar(db, USER_ID, today.year, today.month)
    assert not [r for r in cal["items"] if r["kind"] == "cobro"]


def test_cash_plan_projects_until_balance_is_covered(client, db, data):
    _save(client, data["ana"].id, "Carro", 150)
    rows = [r for r in _rows(db) if not r["done"]]
    assert [r["amount"] for r in rows] == [150.0, 150.0, 50.0]
    assert [r["action"] for r in rows] == ["confirm", None, None]
    assert rows[-1]["note"] == "Último cobro"
    assert rows[0]["concept"] == "Cobro a Ana · Carro" and rows[0]["credit_card_account_id"] is None
    first = today_gt() + timedelta(days=5)
    assert [r["date"] for r in rows] == [
        first.isoformat(), advance_due_date(first, "monthly").isoformat(),
        advance_due_date(advance_due_date(first, "monthly"), "monthly").isoformat(),
    ]


def test_cash_cobro_counts_in_projection(client, db, data):
    today = today_gt()
    before = build_calendar(db, USER_ID, today.year, today.month)
    _save(client, data["ana"].id, "General", 100, days=0)
    db.expire_all()
    after = build_calendar(db, USER_ID, today.year, today.month)
    assert after["summary"]["pending_in"] == round(before["summary"]["pending_in"] + 100, 2)
    assert after["projection"]["end_balance"] == round(before["projection"]["end_balance"] + 100, 2)


def test_tc_cobro_covers_card_not_cash(client, db, data):
    today = today_gt()
    before = build_calendar(db, USER_ID, today.year, today.month)
    _save(client, data["luis"].id, "Regalo", 250, days=1)
    db.expire_all()
    after = build_calendar(db, USER_ID, today.year, today.month)
    card_before = next(c for c in before["cards"] if c["name"] == "Visa Q")
    card_after = next(c for c in after["cards"] if c["name"] == "Visa Q")
    assert card_after["planned_gtq"] == round(card_before["planned_gtq"] + 250, 2)
    assert after["projection"]["end_balance"] == before["projection"]["end_balance"]
    row = next(r for r in _rows(db) if r["kind"] == "cobro")
    assert row["credit_card_account_id"] == data["tc_q"].id and "se abona a Visa Q" in row["note"]


def test_visacuota_plan_uses_upcoming_charges(client, db, data):
    _save(client, data["luis"].id, "Cel Luis", 300, days=25)
    rows = [r for r in _rows(db, 200) if not r["done"]]
    assert [r["amount"] for r in rows] == [300.0, 300.0, 300.0, 300.0]

    r = client.post("/calendario/confirmar-cobro", json={
        "telegram_user_id": USER_ID, "plan_id": rows[0]["plan_id"],
        "payment_date": today_gt().isoformat(), "amount": 300})
    assert r.status_code == 400 and "Todavía no hay saldo" in r.json()["detail"]


def test_confirm_registers_payment_and_advances(client, db, data):
    plan_id = _save(client, data["ana"].id, "Carro", 150, days=0)
    r = client.post("/calendario/confirmar-cobro", json={
        "telegram_user_id": USER_ID, "plan_id": plan_id, "payment_date": today_gt().isoformat(),
        "amount": 150, "account_name": "Banco BI"})
    assert r.status_code == 200, r.text
    db.expire_all()
    payment = db.get(LoanPayment, r.json()["record_id"])
    assert float(payment.amount) == 150
    plan = db.get(LoanCollectionPlan, plan_id)
    assert plan.next_due_date == advance_due_date(today_gt(), "monthly")
    rows = _rows(db)
    assert [r["amount"] for r in rows if not r["done"]] == [150.0, 50.0]
    assert payment.id in {r["record_id"] for r in rows if r["done"]}


def test_confirm_without_record_only_advances(client, db, data):
    plan_id = _save(client, data["ana"].id, "Carro", 150, days=0)
    before = len(db.scalars(select(LoanPayment)).all())
    r = client.post("/calendario/confirmar-cobro", json={
        "telegram_user_id": USER_ID, "plan_id": plan_id, "payment_date": today_gt().isoformat(),
        "create_record": False})
    assert r.status_code == 200 and r.json()["record_id"] is None
    db.expire_all()
    assert len(db.scalars(select(LoanPayment)).all()) == before
    assert db.get(LoanCollectionPlan, plan_id).next_due_date == advance_due_date(today_gt(), "monthly")


def test_cash_cobro_needs_an_account(client, data):
    plan_id = _save(client, data["ana"].id, "Carro", 150, days=0)
    r = client.post("/calendario/confirmar-cobro", json={
        "telegram_user_id": USER_ID, "plan_id": plan_id, "payment_date": today_gt().isoformat(),
        "amount": 150})
    assert r.status_code == 400


def test_save_twice_updates_and_delete_removes(client, db, data):
    first = _save(client, data["ana"].id, "Carro", 150)
    second = _save(client, data["ana"].id, "Carro", 200)
    assert first == second
    items = {(i["person"], i["concept"]): i for i in list_collections(db, USER_ID)["items"]}
    assert items[("Ana", "Carro")]["plan"]["installment_amount"] == 200.0
    assert client.delete(f"/prestamos/planes-cobro/{first}?telegram_user_id={USER_ID}").status_code == 200
    assert _rows(db) == []


def test_reminder_includes_cobro_due_today(client, db, data):
    from app.services.calendar_reminders import build_daily_reminder
    _save(client, data["ana"].id, "General", 100, days=0)
    db.expire_all()
    assert "Cobro: Cobro a Ana · Q100.00" in build_daily_reminder(db, USER_ID, today_gt())


def test_bootstrap_includes_cobros(client, data):
    from app.main import app
    from app.security.telegram_auth import get_current_telegram_auth
    app.dependency_overrides[get_current_telegram_auth] = lambda: {"user": {"id": USER_ID}}
    body = client.get(f"/bootstrap/{USER_ID}").json()
    assert len(body["cobros"]["items"]) == 4
