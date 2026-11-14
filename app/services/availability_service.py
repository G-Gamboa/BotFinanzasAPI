from collections import defaultdict

from sqlalchemy.orm import Session

from app.services.finance_context import FinanceContext, resolve_context
from app.services.finance_db_service import (
    build_saldos_map,
    build_ahorro_breakdown,
)


LIQUID_TYPES = {"cash", "bank"}


def _loan_balances_by_person(ctx: FinanceContext) -> dict[str, float]:
    people_by_id = {p.id: p.name for p in ctx.loan_people}
    loans = [loan for loan in ctx.loans if loan.loan_type == "lent"]
    loans_by_id = {loan.id: loan for loan in loans}
    balances: dict[str, float] = defaultdict(float)

    for loan in loans:
        person = people_by_id.get(loan.loan_person_id)
        if person:
            balances[person] += float(loan.principal_amount)

    for payment in ctx.loan_payments:
        parent_loan = loans_by_id.get(payment.loan_id)
        if not parent_loan:
            continue
        person = people_by_id.get(parent_loan.loan_person_id)
        if person:
            balances[person] -= float(payment.amount)

    return {k: round(v, 2) for k, v in balances.items()}


def build_disponibles(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)

    liquid_names = {
        a.name for a in ctx.accounts if a.account_type in LIQUID_TYPES
    }

    saldos_map = build_saldos_map(db, telegram_user_id, ctx)
    ahorro_data = build_ahorro_breakdown(db, telegram_user_id, ctx)
    loan_balances = _loan_balances_by_person(ctx)

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