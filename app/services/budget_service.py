from datetime import date
from decimal import Decimal

import pytz
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Budget, Category, Movement, User


def _today_gt() -> date:
    return datetime.now(pytz.timezone("America/Guatemala")).date()


def _get_user(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def list_budgets(db: Session, telegram_user_id: int) -> list[dict]:
    user = _get_user(db, telegram_user_id)
    today = _today_gt()
    month_start = date(today.year, today.month, 1)

    budgets = db.scalars(
        select(Budget).where(Budget.user_id == user.id)
    ).all()

    if not budgets:
        return []

    category_ids = [b.category_id for b in budgets]
    categories = db.scalars(
        select(Category).where(Category.id.in_(category_ids))
    ).all()
    cat_name_by_id = {c.id: c.name for c in categories}

    # Gasto real del mes actual por categoría (solo EGR propios, sin TC de terceros)
    egr_movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.movement_type == "EGR",
            Movement.movement_date >= month_start,
            Movement.movement_date <= today,
            Movement.is_void == False,
            Movement.is_third_party == False,
            Movement.category_id.in_(category_ids),
        )
    ).all()

    spent_by_cat: dict[int, float] = {}
    for m in egr_movements:
        spent_by_cat[m.category_id] = spent_by_cat.get(m.category_id, 0.0) + float(m.amount)

    result = []
    for b in sorted(budgets, key=lambda x: cat_name_by_id.get(x.category_id, "").lower()):
        spent = round(spent_by_cat.get(b.category_id, 0.0), 2)
        monthly = float(b.monthly_amount)
        pct = round(spent / monthly, 4) if monthly > 0 else 0.0
        remaining = round(monthly - spent, 2)
        exceeded_by = round(max(0.0, spent - monthly), 2)

        result.append({
            "id": int(b.id),
            "category_id": b.category_id,
            "category_name": cat_name_by_id.get(b.category_id, "—"),
            "monthly_amount": monthly,
            "spent_this_month": spent,
            "pct_used": pct,
            "remaining": remaining,
            "exceeded_by": exceeded_by,
        })

    return result


def create_budget(
    db: Session,
    telegram_user_id: int,
    category_id: int,
    monthly_amount: float,
) -> Budget:
    user = _get_user(db, telegram_user_id)

    category = db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user.id,
            Category.kind == "EGR",
            Category.is_active == True,
        )
    )
    if not category:
        raise ValueError("Categoría de egreso no encontrada.")

    existing = db.scalar(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category_id == category_id,
        )
    )
    if existing:
        raise ValueError(f"Ya existe un presupuesto para '{category.name}'.")

    budget = Budget(
        user_id=user.id,
        category_id=category_id,
        monthly_amount=Decimal(str(monthly_amount)),
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def update_budget(
    db: Session,
    budget_id: int,
    telegram_user_id: int,
    monthly_amount: float,
) -> Budget:
    user = _get_user(db, telegram_user_id)

    budget = db.get(Budget, budget_id)
    if not budget or budget.user_id != user.id:
        raise ValueError("Presupuesto no encontrado.")

    budget.monthly_amount = Decimal(str(monthly_amount))
    db.commit()
    db.refresh(budget)
    return budget


def delete_budget(db: Session, budget_id: int, telegram_user_id: int) -> None:
    user = _get_user(db, telegram_user_id)

    budget = db.get(Budget, budget_id)
    if not budget or budget.user_id != user.id:
        raise ValueError("Presupuesto no encontrado.")

    db.delete(budget)
    db.commit()
