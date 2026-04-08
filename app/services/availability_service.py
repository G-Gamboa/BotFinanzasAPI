from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account
from app.services.finance_db_service import (
    build_saldos_map,
    build_ahorro_breakdown,
)
from app.services.transaction_service import (
    get_user_or_raise,
    build_loan_balance_internal,
)


LIQUID_TYPES = {"cash", "bank"}


def build_disponibles(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    accounts = db.scalars(
        select(Account).where(Account.user_id == user.id).order_by(Account.name)
    ).all()

    liquid_names = {
        a.name for a in accounts if a.account_type in LIQUID_TYPES
    }

    saldos_map = build_saldos_map(db, telegram_user_id)
    ahorro_data = build_ahorro_breakdown(db, telegram_user_id)
    loan_balances = build_loan_balance_internal(db, user.id)

    saldos_liquidos = [
        {
            "cuenta": cuenta,
            "saldo": round(saldo, 2),
        }
        for cuenta, saldo in sorted(saldos_map.items(), key=lambda x: x[0].lower())
        if cuenta in liquid_names and abs(saldo) > 1e-9
    ]

    ahorro_por_cuenta = [
        {
            "cuenta": item["cuenta"],
            "saldo": round(item["saldo"], 2),
        }
        for item in ahorro_data["items"]
        if item["saldo"] > 1e-9
    ]

    prestamos_por_persona = [
        {
            "persona": persona,
            "saldo": round(saldo, 2),
        }
        for persona, saldo in sorted(loan_balances.items(), key=lambda x: x[0].lower())
        if saldo > 1e-9
    ]

    return {
        "saldos_liquidos": saldos_liquidos,
        "ahorro_por_cuenta": ahorro_por_cuenta,
        "prestamos_por_persona": prestamos_por_persona,
    }