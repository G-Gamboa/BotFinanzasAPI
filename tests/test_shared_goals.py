"""Metas de ahorro conjuntas: dos usuarios, cada uno con sus cuentas."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Account, Category, Movement, User, UserSetting
from app.dependencies import get_current_app_user
from app.security.telegram_auth import get_current_telegram_auth
from app.services import shared_goal_service as svc
from app.services.finance_db_service import build_saldos_map, today_gt

ME = 999_999_999
PARTNER = 888_888_888
OUTSIDER = 777_777_777


@pytest.fixture
def world(db, db_engine, test_user, client, monkeypatch):
    """Dos personas elegibles y una ajena, cada una con Efectivo, Banco y Ahorro fondeados."""
    monkeypatch.setattr(get_settings(), "private_palette_user_ids", [ME, PARTNER])
    sent = []
    monkeypatch.setattr(svc, "_send_plain", lambda token, chat_id, text: sent.append((chat_id, text)))

    now = datetime.now(timezone.utc)
    users = {ME: test_user}
    for tid, name in ((PARTNER, "Ana"), (OUTSIDER, "Otro")):
        u = User(telegram_user_id=tid, first_name=name, is_active=True, can_use_loans=False, theme_key="neutral")
        db.add(u)
        db.flush()
        db.add(UserSetting(user_id=u.id, preferred_currency="GTQ", usd_to_gtq=7.7, hide_amounts_default=False,
                           show_amounts_default=False, default_tab="movimientos", created_at=now, updated_at=now))
        users[tid] = u
    for u in users.values():
        banco = Account(user_id=u.id, name="Banco", account_type="bank", currency="GTQ",
                        is_active=True, is_system=False, sort_order=1)
        db.add_all([
            banco,
            Account(user_id=u.id, name="Efectivo", account_type="cash", currency="GTQ",
                    is_active=True, is_system=True, sort_order=0),
            Account(user_id=u.id, name="Ahorro", account_type="savings", currency="GTQ",
                    is_active=True, is_system=True, sort_order=2),
        ])
        cat = Category(user_id=u.id, name="Salario", kind="ING", is_active=True, is_system=False,
                       sort_order=1, created_at=now, updated_at=now)
        db.add(cat)
        db.flush()
        db.add(Movement(user_id=u.id, movement_type="ING", movement_date=today_gt() - timedelta(days=3),
                        amount=5000, payment_method="transfer", transfer_account_id=banco.id, category_id=cat.id))
    db.commit()

    from app.main import app
    Factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def act_as(tid):
        def current():
            s = Factory()
            try:
                return s.scalar(select(User).where(User.telegram_user_id == tid))
            finally:
                s.close()
        app.dependency_overrides[get_current_app_user] = current
        app.dependency_overrides[get_current_telegram_auth] = lambda: {"user": {"id": tid}}

    act_as(ME)
    return {"client": client, "act_as": act_as, "sent": sent, "today": today_gt().isoformat()}


def _create(w, **kw):
    payload = {"telegram_user_id": ME, "name": "Viaje", "target_amount": 10000, "partner_ids": [PARTNER], **kw}
    r = w["client"].post("/metas-conjuntas", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _move(w, tid, goal_id, action, amount, account="Banco"):
    return w["client"].post(f"/metas-conjuntas/{goal_id}/{action}", json={
        "telegram_user_id": tid, "amount": amount, "account_name": account, "movement_date": w["today"]})


def test_partner_listing_and_eligibility(world):
    c = world["client"]
    mine = c.get(f"/metas-conjuntas/{ME}").json()
    assert mine["can_use"] is True
    assert mine["partners"] == [{"telegram_user_id": PARTNER, "name": "Ana"}]

    world["act_as"](OUTSIDER)
    other = c.get(f"/metas-conjuntas/{OUTSIDER}").json()
    assert other == {"can_use": False, "partners": [], "items": []}
    r = c.post("/metas-conjuntas", json={
        "telegram_user_id": OUTSIDER, "name": "X", "target_amount": 100, "partner_ids": [ME]})
    assert r.status_code == 400


def test_cannot_share_with_someone_not_eligible(world):
    r = world["client"].post("/metas-conjuntas", json={
        "telegram_user_id": ME, "name": "X", "target_amount": 100, "partner_ids": [OUTSIDER]})
    assert r.status_code == 400


def test_both_contribute_and_goal_sums(world, db):
    c = world["client"]
    goal_id = _create(world, target_date=(today_gt() + timedelta(days=150)).isoformat())

    r = _move(world, ME, goal_id, "aportar", 1500)
    assert r.status_code == 200, r.text
    assert r.json()["goal"]["total"] == 1500.0

    world["act_as"](PARTNER)
    assert _move(world, PARTNER, goal_id, "aportar", 700).status_code == 200
    hers = c.get(f"/metas-conjuntas/{PARTNER}").json()["items"][0]
    assert hers["total"] == 2200.0 and hers["my_amount"] == 700.0 and hers["is_creator"] is False
    assert hers["remaining"] == 7800.0 and hers["monthly_needed"] > 0
    assert [(m["name"], m["is_me"], m["amount"]) for m in hers["members"]] == [("Ana", True, 700.0), ("Test", False, 1500.0)]
    assert [(x["name"], x["amount"]) for x in hers["contributions"]] == [("Ana", 700.0), ("Test", 1500.0)]

    # Cada quien movió su propio dinero a su propio Ahorro
    db.expire_all()
    assert build_saldos_map(db, ME)["Banco"] == 3500.0 and build_saldos_map(db, ME)["Ahorro"] == 1500.0
    assert build_saldos_map(db, PARTNER)["Banco"] == 4300.0 and build_saldos_map(db, PARTNER)["Ahorro"] == 700.0

    # A cada aporte se le avisa al otro
    assert world["sent"][0][0] == PARTNER and "Test aportó Q1,500.00 a Viaje" in world["sent"][0][1]
    assert world["sent"][1][0] == ME and "Van Q2,200.00 de Q10,000.00" in world["sent"][1][1]


def test_withdraw_only_own_contribution(world):
    goal_id = _create(world)
    assert _move(world, ME, goal_id, "aportar", 1000).status_code == 200
    world["act_as"](PARTNER)
    assert _move(world, PARTNER, goal_id, "aportar", 400).status_code == 200

    r = _move(world, PARTNER, goal_id, "retirar", 500)
    assert r.status_code == 400 and "Q 400.00" in r.json()["detail"]
    r = _move(world, PARTNER, goal_id, "retirar", 150)
    assert r.status_code == 200, r.text
    goal = r.json()["goal"]
    assert goal["total"] == 1250.0 and goal["my_amount"] == 250.0


def test_insufficient_balance_is_rejected(world):
    goal_id = _create(world)
    r = _move(world, ME, goal_id, "aportar", 9000)
    assert r.status_code == 400 and "Saldo insuficiente" in r.json()["detail"]
    assert world["client"].get(f"/metas-conjuntas/{ME}").json()["items"][0]["total"] == 0.0


def test_voiding_the_movement_lowers_the_goal(world):
    c = world["client"]
    goal_id = _create(world)
    _move(world, ME, goal_id, "aportar", 800)
    movement_id = c.get(f"/metas-conjuntas/{ME}").json()["items"][0]["contributions"][0]["id"]
    assert c.patch(f"/movimientos/{movement_id}/anular", json={"reason": "x"}).status_code == 200
    assert c.get(f"/metas-conjuntas/{ME}").json()["items"][0]["total"] == 0.0


def test_edit_by_any_member_close_only_by_creator(world):
    c = world["client"]
    goal_id = _create(world)
    world["act_as"](PARTNER)
    r = c.patch(f"/metas-conjuntas/{goal_id}", json={
        "telegram_user_id": PARTNER, "name": "Viaje a la playa", "target_amount": 12000, "target_date": None})
    assert r.status_code == 200
    assert c.delete(f"/metas-conjuntas/{goal_id}?telegram_user_id={PARTNER}").status_code == 400

    world["act_as"](ME)
    assert c.get(f"/metas-conjuntas/{ME}").json()["items"][0]["name"] == "Viaje a la playa"
    assert c.delete(f"/metas-conjuntas/{goal_id}?telegram_user_id={ME}").status_code == 200
    assert c.get(f"/metas-conjuntas/{ME}").json()["items"] == []


def test_outsider_cannot_touch_the_goal(world):
    goal_id = _create(world)
    world["act_as"](OUTSIDER)
    assert _move(world, OUTSIDER, goal_id, "aportar", 100).status_code == 400
    assert world["client"].get(f"/metas-conjuntas/{OUTSIDER}").json()["items"] == []


def test_bootstrap_includes_shared_goals(world):
    goal_id = _create(world)
    _move(world, ME, goal_id, "aportar", 300)
    body = world["client"].get(f"/bootstrap/{ME}").json()
    assert body["sharedGoals"]["can_use"] is True
    assert body["sharedGoals"]["items"][0]["total"] == 300.0
