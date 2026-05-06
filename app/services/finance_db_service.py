from collections import defaultdict
from datetime import date, timedelta, datetime

import pytz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Account, Category, Movement, Debt, LoanPerson, UserSetting, Loan, LoanPayment, DebtPayment


LIQUID_TYPES = {"cash", "bank"}
INVESTMENT_TYPES = {"investment"}


def today_gt() -> date:
    tz = pytz.timezone("America/Guatemala")
    return datetime.now(tz).date()


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def get_usd_to_gtq(db: Session, user_id: int, fallback: float) -> float:
    setting = db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
    if not setting:
        return fallback
    return float(setting.usd_to_gtq)


def get_accounts_map(db: Session, user_id: int) -> dict[int, Account]:
    accounts = db.scalars(select(Account).where(Account.user_id == user_id)).all()
    return {a.id: a for a in accounts}


def build_saldos_map(db: Session, telegram_user_id: int) -> dict[str, float]:
    user = get_user_or_raise(db, telegram_user_id)
    account_by_id = get_accounts_map(db, user.id)
    saldos: dict[str, float] = defaultdict(float)

    # ING / EGR / MOV (non-loan transfers)
    movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.is_void == False,
        )
    ).all()

    for m in movements:
        if m.movement_type == "ING":
            account_id = (
                m.transfer_account_id
                if (m.payment_method or "").lower() == "transferencia"
                else m.target_account_id
            )
            if account_id and account_id in account_by_id:
                saldos[account_by_id[account_id].name] += float(m.amount)

        elif m.movement_type == "EGR":
            account_id = (
                m.transfer_account_id
                if (m.payment_method or "").lower() == "transferencia"
                else m.source_account_id
            )
            if account_id and account_id in account_by_id:
                saldos[account_by_id[account_id].name] -= float(m.amount)

        elif m.movement_type == "MOV":
            # Skip loan-related MOV rows that may not have been migrated yet
            if m.loan_person_id:
                continue

            if m.source_account_id and m.source_account_id in account_by_id:
                saldos[account_by_id[m.source_account_id].name] -= float(m.amount)

            if m.target_account_id and m.target_account_id in account_by_id:
                incoming = float(m.destination_amount) if m.destination_amount is not None else float(m.amount)
                saldos[account_by_id[m.target_account_id].name] += incoming

    # Loans (lent): Prestamos account increases.
    # The source liquid account is NOT stored in the loans table, so it is not
    # debited here — it must be reconciled via a separate EGR movement if needed.
    loans = db.scalars(
        select(Loan).where(Loan.user_id == user.id, Loan.loan_type == "lent")
    ).all()
    for loan in loans:
        saldos["Prestamos"] += float(loan.principal_amount)

    # Loan payments (collected): liquid account increases, Prestamos account decreases
    loan_payments = db.scalars(
        select(LoanPayment).where(LoanPayment.user_id == user.id)
    ).all()
    for payment in loan_payments:
        if payment.account_id in account_by_id:
            saldos[account_by_id[payment.account_id].name] += float(payment.amount)
        saldos["Prestamos"] -= float(payment.amount)

    # Debt payments: liquid account decreases (replaces the old EGR movement)
    debt_payments = db.scalars(
        select(DebtPayment).where(DebtPayment.user_id == user.id)
    ).all()
    for dp in debt_payments:
        if dp.account_id in account_by_id:
            saldos[account_by_id[dp.account_id].name] -= float(dp.amount)

    for acc in account_by_id.values():
        saldos[acc.name] += 0.0

    return dict(sorted(saldos.items(), key=lambda x: x[0]))


def build_ahorro_breakdown(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    account_by_id = get_accounts_map(db, user.id)

    ahorro_por_cuenta = defaultdict(float)

    movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.movement_type == "MOV",
            Movement.is_void == False,
        )
    ).all()

    for m in movements:
        source_name = account_by_id[m.source_account_id].name if m.source_account_id in account_by_id else None
        target_name = account_by_id[m.target_account_id].name if m.target_account_id in account_by_id else None

        if target_name == "Ahorro" and source_name and source_name != "Ahorro":
            ahorro_por_cuenta[source_name] += float(m.amount)
        elif source_name == "Ahorro" and target_name and target_name != "Ahorro":
            outgoing = float(m.destination_amount) if m.destination_amount is not None else float(m.amount)
            ahorro_por_cuenta[target_name] -= outgoing

    items = [
        {"cuenta": cuenta, "saldo": round(saldo, 2)}
        for cuenta, saldo in sorted(ahorro_por_cuenta.items(), key=lambda x: x[0].lower())
        if abs(saldo) > 1e-9
    ]

    total = round(sum(item["saldo"] for item in items), 2)

    return {
        "total": total,
        "items": items,
    }


def build_debts(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    debts = db.scalars(
        select(Debt).where(Debt.user_id == user.id).order_by(Debt.due_date, Debt.id)
    ).all()

    items = []
    total_pendiente = 0.0

    for d in debts:
        pending_installments = max(d.total_installments - d.paid_installments, 0)
        saldo_pendiente = round(pending_installments * float(d.installment_amount), 2)
        total_pendiente += saldo_pendiente

        items.append({
            "id": int(d.id),
            "name": d.name,
            "creditor": d.creditor,
            "due_date": d.due_date.isoformat(),
            "installment_amount": round(float(d.installment_amount), 2),
            "total_installments": d.total_installments,
            "paid_installments": d.paid_installments,
            "pending_installments": pending_installments,
            "saldo_pendiente": saldo_pendiente,
            "status": d.status,
        })

    return {
        "total_pendiente": round(total_pendiente, 2),
        "items": items,
    }


def build_networth(db: Session, telegram_user_id: int, fallback_tc: float) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    tc = get_usd_to_gtq(db, user.id, fallback_tc)

    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    account_type_map = {a.name: a.account_type for a in accounts}

    saldos = build_saldos_map(db, telegram_user_id)
    ahorro_data = build_ahorro_breakdown(db, telegram_user_id)

    liquid_map = {}
    prestamos_map = {}
    inv_map = {}

    for cuenta, saldo in saldos.items():
        account_type = account_type_map.get(cuenta)

        if cuenta in {"Ahorro", "Prestamos"}:
            continue

        if account_type in LIQUID_TYPES and abs(saldo) > 1e-9:
            liquid_map[cuenta] = round(saldo, 2)
        elif account_type in INVESTMENT_TYPES and abs(saldo) > 1e-9:
            inv_map[cuenta] = round(saldo, 2)

    loan_people = db.scalars(select(LoanPerson).where(LoanPerson.user_id == user.id)).all()
    loan_person_by_id = {lp.id: lp.name for lp in loan_people}

    prestamos_tmp: dict[str, float] = defaultdict(float)

    loans = db.scalars(
        select(Loan).where(Loan.user_id == user.id, Loan.loan_type == "lent")
    ).all()
    loans_by_id = {loan.id: loan for loan in loans}

    for loan in loans:
        person = loan_person_by_id.get(loan.loan_person_id, "General")
        prestamos_tmp[person] += float(loan.principal_amount)

    loan_payments = db.scalars(
        select(LoanPayment).where(LoanPayment.user_id == user.id)
    ).all()
    for payment in loan_payments:
        parent_loan = loans_by_id.get(payment.loan_id)
        person = loan_person_by_id.get(parent_loan.loan_person_id, "General") if parent_loan else "General"
        prestamos_tmp[person] -= float(payment.amount)

    prestamos_map = {
        person: round(value, 2)
        for person, value in sorted(prestamos_tmp.items(), key=lambda x: x[0].lower())
        if abs(value) > 1e-9
    }

    liquidez_gtq = round(sum(liquid_map.values()), 2)
    ahorro_total_gtq = round(ahorro_data["total"], 2)
    prestamos_gtq = round(sum(prestamos_map.values()), 2)
    inv_total_usd = round(sum(inv_map.values()), 2)
    total_gtq = round(liquidez_gtq + ahorro_total_gtq + prestamos_gtq + (inv_total_usd * tc), 2)

    return {
        "liquid_map": liquid_map,
        "liquidez_gtq": liquidez_gtq,
        "ahorro_total_gtq": ahorro_total_gtq,
        "ahorro_por_cuenta": ahorro_data["items"],
        "prestamos_map": prestamos_map,
        "prestamos_gtq": prestamos_gtq,
        "inv_map": inv_map,
        "inv_total_usd": inv_total_usd,
        "total_gtq": total_gtq,
        "tc": tc,
    }


def build_neto(db: Session, telegram_user_id: int, fallback_tc: float) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    networth = build_networth(db, telegram_user_id, fallback_tc)

    debts = db.scalars(
        select(Debt).where(Debt.user_id == user.id, Debt.status == "active")
    ).all()

    pasivos = round(
        sum((d.total_installments - d.paid_installments) * float(d.installment_amount) for d in debts),
        2,
    )

    patrimonio_bruto = round(networth["total_gtq"], 2)
    patrimonio_neto = round(patrimonio_bruto - pasivos, 2)

    return {
        "patrimonio_bruto": patrimonio_bruto,
        "pasivos": pasivos,
        "patrimonio_neto": patrimonio_neto,
    }


def day_range(today: date) -> tuple[date, date]:
    return today, today


def week_range(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def month_range(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def build_period_summary(
    db: Session,
    telegram_user_id: int,
    periodo: str,
    fecha_inicio: date,
    fecha_fin: date,
) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.movement_date >= fecha_inicio,
            Movement.movement_date <= fecha_fin,
            Movement.is_void == False,
        )
    ).all()

    categories = db.scalars(select(Category).where(Category.user_id == user.id)).all()
    category_by_id = {c.id: c for c in categories}

    ingresos = 0.0
    egresos = 0.0
    gastos_por_categoria = defaultdict(float)

    for m in movements:
        if m.movement_type == "ING":
            ingresos += float(m.amount)

        elif m.movement_type == "EGR":
            egresos += float(m.amount)
            cat_name = "Sin categoría"
            if m.category_id and m.category_id in category_by_id:
                cat_name = category_by_id[m.category_id].name
            gastos_por_categoria[cat_name] += float(m.amount)

    gastos_por_categoria = {
        k: round(v, 2)
        for k, v in sorted(gastos_por_categoria.items(), key=lambda x: x[0].lower())
        if abs(v) > 1e-9
    }

    top_gastos = sorted(
        [{"categoria": k, "monto": round(v, 2)} for k, v in gastos_por_categoria.items()],
        key=lambda x: x["monto"],
        reverse=True,
    )[:6]

    return {
        "periodo": periodo,
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "ingresos": round(ingresos, 2),
        "egresos": round(egresos, 2),
        "balance": round(ingresos - egresos, 2),
        "gastos_por_categoria": gastos_por_categoria,
        "top_gastos": top_gastos,
    }


def build_dashboard(db: Session, telegram_user_id: int, fallback_tc: float) -> dict:
    today = today_gt()

    dia_inicio, dia_fin = day_range(today)
    sem_inicio, sem_fin = week_range(today)
    mes_inicio, mes_fin = month_range(today)

    return {
        "networth": build_networth(db, telegram_user_id, fallback_tc),
        "neto": build_neto(db, telegram_user_id, fallback_tc),
        "resumen_dia": build_period_summary(db, telegram_user_id, "dia", dia_inicio, dia_fin),
        "resumen_semana": build_period_summary(db, telegram_user_id, "semana", sem_inicio, sem_fin),
        "resumen_mes": build_period_summary(db, telegram_user_id, "mes", mes_inicio, mes_fin),
    }