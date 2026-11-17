"""Metas de ahorro conjuntas.

El dinero no se mueve entre personas: cada miembro guarda en su propio Ahorro
y el movimiento queda etiquetado con la meta. La meta suma lo de todos, y cada
miembro ve solo la meta y los aportes, nunca las cuentas del otro.
"""
import json
import logging
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Account, Movement, SharedGoal, SharedGoalMember, User
from app.schemas.transactions import MovementCreateRequest
from app.services.finance_db_service import today_gt
from app.services.transaction_service import create_movement
from app.ws.manager import manager

logger = logging.getLogger(__name__)

MAX_CONTRIBUTIONS_SHOWN = 30


def _user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def _display_name(user: User) -> str:
    return (user.first_name or user.username or f"ID {user.telegram_user_id}").strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe usar formato YYYY-MM-DD.")


def can_use_shared_goals(user: User) -> bool:
    return int(user.telegram_user_id) in get_settings().private_palette_user_ids


def eligible_partners(db: Session, user: User) -> list[User]:
    """Personas con las que este usuario puede abrir una meta conjunta."""
    if not can_use_shared_goals(user):
        return []
    ids = [i for i in get_settings().private_palette_user_ids if i != int(user.telegram_user_id)]
    if not ids:
        return []
    return list(db.scalars(
        select(User).where(User.telegram_user_id.in_(ids), User.is_active == True).order_by(User.first_name)
    ).all())


def _months_left(today: date, target: date) -> int:
    months = (target.year - today.year) * 12 + (target.month - today.month)
    return max(months + (1 if target.day >= today.day else 0), 1)


def list_shared_goals(db: Session, telegram_user_id: int) -> dict:
    user = _user_or_raise(db, telegram_user_id)
    partners = eligible_partners(db, user)

    goal_ids = list(db.scalars(select(SharedGoalMember.goal_id).where(SharedGoalMember.user_id == user.id)).all())
    goals = []
    if goal_ids:
        goals = db.scalars(
            select(SharedGoal).where(SharedGoal.id.in_(goal_ids), SharedGoal.is_active == True).order_by(SharedGoal.id)
        ).all()

    items: list[dict] = []
    if goals:
        ids = [g.id for g in goals]
        members = db.scalars(select(SharedGoalMember).where(SharedGoalMember.goal_id.in_(ids))).all()
        users = {u.id: u for u in db.scalars(
            select(User).where(User.id.in_({m.user_id for m in members}))
        ).all()}
        movements = db.scalars(
            select(Movement).where(Movement.shared_goal_id.in_(ids), Movement.is_void == False)
        ).all()
        target_ids = {m.target_account_id for m in movements if m.target_account_id}
        savings_ids = set()
        if target_ids:
            savings_ids = {
                a.id for a in db.scalars(select(Account).where(Account.id.in_(target_ids))).all()
                if a.account_type == "savings" or a.name.lower() == "ahorro"
            }

        today = today_gt()
        for goal in goals:
            by_user: dict[int, float] = defaultdict(float)
            contributions = []
            for m in movements:
                if m.shared_goal_id != goal.id:
                    continue
                signed = float(m.amount) if m.target_account_id in savings_ids else -float(m.amount)
                by_user[m.user_id] += signed
                who = users.get(m.user_id)
                contributions.append({
                    "id": int(m.id),
                    "date": m.movement_date.isoformat(),
                    "name": _display_name(who) if who else "—",
                    "is_me": m.user_id == user.id,
                    "amount": round(signed, 2),
                })
            contributions.sort(key=lambda c: (c["date"], c["id"]), reverse=True)

            total = round(sum(by_user.values()), 2)
            target = float(goal.target_amount)
            remaining = round(max(target - total, 0.0), 2)
            monthly_needed = None
            if goal.target_date and remaining > 0 and goal.target_date >= today:
                monthly_needed = round(remaining / _months_left(today, goal.target_date), 2)

            goal_members = [m for m in members if m.goal_id == goal.id]
            items.append({
                "id": int(goal.id),
                "name": goal.name,
                "target_amount": round(target, 2),
                "target_date": goal.target_date.isoformat() if goal.target_date else None,
                "total": total,
                "remaining": remaining,
                "pct": round(min(total / target, 1.0), 4) if target > 0 else 0.0,
                "monthly_needed": monthly_needed,
                "is_creator": goal.created_by == user.id,
                "my_amount": round(by_user.get(user.id, 0.0), 2),
                "members": sorted([
                    {
                        "name": _display_name(users[m.user_id]) if m.user_id in users else "—",
                        "is_me": m.user_id == user.id,
                        "amount": round(by_user.get(m.user_id, 0.0), 2),
                    }
                    for m in goal_members
                ], key=lambda x: (not x["is_me"], x["name"].lower())),
                "contributions": contributions[:MAX_CONTRIBUTIONS_SHOWN],
            })

    return {
        "can_use": can_use_shared_goals(user),
        "partners": [{"telegram_user_id": int(p.telegram_user_id), "name": _display_name(p)} for p in partners],
        "items": items,
    }


def _goal_for_member(db: Session, user: User, goal_id: int) -> SharedGoal:
    goal = db.scalar(select(SharedGoal).where(SharedGoal.id == goal_id, SharedGoal.is_active == True))
    is_member = goal is not None and db.scalar(select(SharedGoalMember).where(
        SharedGoalMember.goal_id == goal_id, SharedGoalMember.user_id == user.id,
    )) is not None
    if not is_member:
        raise ValueError("Meta conjunta no encontrada.")
    return goal


def create_shared_goal(db: Session, telegram_user_id: int, name: str, target_amount: float,
                       target_date: str | None, partner_ids: list[int]) -> SharedGoal:
    user = _user_or_raise(db, telegram_user_id)
    if not can_use_shared_goals(user):
        raise ValueError("Tu cuenta no puede crear metas conjuntas.")
    allowed = {int(p.telegram_user_id): p for p in eligible_partners(db, user)}
    chosen = [allowed[i] for i in dict.fromkeys(partner_ids) if i in allowed]
    if not chosen or len(chosen) != len(set(partner_ids)):
        raise ValueError("Elige con quién compartir la meta.")

    goal = SharedGoal(
        name=name.strip(), target_amount=target_amount, target_date=_parse_date(target_date),
        created_by=user.id, is_active=True, created_at=datetime.now(timezone.utc),
    )
    db.add(goal)
    db.flush()
    for member in [user, *chosen]:
        db.add(SharedGoalMember(goal_id=goal.id, user_id=member.id))
    db.commit()
    db.refresh(goal)
    _broadcast(db, goal.id)
    return goal


def update_shared_goal(db: Session, telegram_user_id: int, goal_id: int, name: str,
                       target_amount: float, target_date: str | None) -> SharedGoal:
    user = _user_or_raise(db, telegram_user_id)
    goal = _goal_for_member(db, user, goal_id)
    goal.name = name.strip()
    goal.target_amount = target_amount
    goal.target_date = _parse_date(target_date)
    db.commit()
    _broadcast(db, goal.id)
    return goal


def close_shared_goal(db: Session, telegram_user_id: int, goal_id: int) -> None:
    user = _user_or_raise(db, telegram_user_id)
    goal = _goal_for_member(db, user, goal_id)
    if goal.created_by != user.id:
        raise ValueError("Solo quien creó la meta puede cerrarla.")
    goal.is_active = False
    db.commit()
    _broadcast(db, goal.id)


def _member_users(db: Session, goal_id: int) -> list[User]:
    ids = db.scalars(select(SharedGoalMember.user_id).where(SharedGoalMember.goal_id == goal_id)).all()
    return list(db.scalars(select(User).where(User.id.in_(ids))).all()) if ids else []


def _broadcast(db: Session, goal_id: int) -> None:
    for member in _member_users(db, goal_id):
        manager.broadcast_from_sync(member.telegram_user_id, {"event": "invalidate", "scope": "financial"})


def _send_plain(token: str, chat_id: int, text: str) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _notify_others(db: Session, actor: User, goal_id: int, text: str) -> None:
    token = get_settings().telegram_bot_token
    for member in _member_users(db, goal_id):
        if member.id == actor.id or not member.is_active:
            continue
        try:
            _send_plain(token, member.telegram_user_id, text)
        except Exception as exc:
            logger.warning("No se pudo avisar del aporte: user=%s error=%s", member.telegram_user_id, exc)


def _goal_snapshot(db: Session, telegram_user_id: int, goal_id: int) -> dict:
    return next(g for g in list_shared_goals(db, telegram_user_id)["items"] if g["id"] == goal_id)


def contribute(db: Session, telegram_user_id: int, goal_id: int, amount: float,
               account_name: str, movement_date: str) -> dict:
    """Guarda desde una cuenta propia hacia el Ahorro propio y lo suma a la meta."""
    user = _user_or_raise(db, telegram_user_id)
    goal = _goal_for_member(db, user, goal_id)
    goal_name = goal.name

    movement = create_movement(db, MovementCreateRequest(
        telegram_user_id=telegram_user_id, movement_type="MOV", movement_date=movement_date,
        amount=amount, note=f"Aporte a {goal_name}", mov_subtype="AHORRO", mov_direction="GUARDAR",
        source_account_name=account_name,
    ))
    movement.shared_goal_id = goal_id
    db.commit()

    snapshot = _goal_snapshot(db, telegram_user_id, goal_id)
    _notify_others(db, user, goal_id, (
        f"{_display_name(user)} aportó Q{amount:,.2f} a {goal_name}. "
        f"Van Q{snapshot['total']:,.2f} de Q{snapshot['target_amount']:,.2f}."
    ))
    _broadcast(db, goal_id)
    return snapshot


def withdraw(db: Session, telegram_user_id: int, goal_id: int, amount: float,
             account_name: str, movement_date: str) -> dict:
    """Retira del Ahorro propio a una cuenta propia; resta solo de lo que aportó quien retira."""
    user = _user_or_raise(db, telegram_user_id)
    goal = _goal_for_member(db, user, goal_id)
    goal_name = goal.name

    mine = _goal_snapshot(db, telegram_user_id, goal_id)["my_amount"]
    if round(amount, 2) > round(mine, 2):
        raise ValueError(f"Solo puedes retirar lo que aportaste a esta meta: Q {mine:,.2f}.")

    movement = create_movement(db, MovementCreateRequest(
        telegram_user_id=telegram_user_id, movement_type="MOV", movement_date=movement_date,
        amount=amount, note=f"Retiro de {goal_name}", mov_subtype="AHORRO", mov_direction="RETIRAR",
        target_account_name=account_name,
    ))
    movement.shared_goal_id = goal_id
    db.commit()

    snapshot = _goal_snapshot(db, telegram_user_id, goal_id)
    _notify_others(db, user, goal_id, (
        f"{_display_name(user)} retiró Q{amount:,.2f} de {goal_name}. "
        f"Quedan Q{snapshot['total']:,.2f} de Q{snapshot['target_amount']:,.2f}."
    ))
    _broadcast(db, goal_id)
    return snapshot
