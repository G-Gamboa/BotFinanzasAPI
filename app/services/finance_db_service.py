from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta, datetime

import pytz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import User, Account, Category, Movement, Debt, LoanPerson, UserSetting, Loan, LoanPayment, DebtPayment, SavingsGoal, CreditCardPayment, CreditCardInstallmentPlan


LIQUID_TYPES = {"cash", "bank"}
INVESTMENT_TYPES = {"investment"}


def _add_months(d: date, n: int) -> date:
    """Suma n meses a la fecha d, ajustando el día al último del mes si es necesario."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


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
                if m.payment_method == "transfer"
                else m.target_account_id
            )
            if account_id and account_id in account_by_id:
                saldos[account_by_id[account_id].name] += float(m.amount)

        elif m.movement_type == "EGR":
            account_id = (
                m.transfer_account_id
                if m.payment_method == "transfer"
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

    # Loans (lent): Prestamos increases; source liquid account decreases.
    loans = db.scalars(
        select(Loan).where(Loan.user_id == user.id, Loan.loan_type == "lent")
    ).all()
    for loan in loans:
        saldos["Prestamos"] += float(loan.principal_amount)
        if loan.source_account_id and loan.source_account_id in account_by_id:
            saldos[account_by_id[loan.source_account_id].name] -= float(loan.principal_amount)

    # Loan payments (collected): liquid account credited + Prestamos decreases.
    # The original COBRAR movements (MOV type) credited the target liquid account
    # and debited Prestamos. We replicate that here from the loan_payments table.
    loan_payments = db.scalars(
        select(LoanPayment).where(
            LoanPayment.user_id == user.id,
            LoanPayment.is_void == False,
        )
    ).all()
    for payment in loan_payments:
        if payment.account_id in account_by_id:
            saldos[account_by_id[payment.account_id].name] += float(payment.amount)
        saldos["Prestamos"] -= float(payment.amount)

    # Debt payments: liquid account decreases (replaces the old EGR movement)
    debt_payments = db.scalars(
        select(DebtPayment).where(
            DebtPayment.user_id == user.id,
            DebtPayment.is_void == False,
        )
    ).all()
    for dp in debt_payments:
        if dp.account_id in account_by_id:
            saldos[account_by_id[dp.account_id].name] -= float(dp.amount)

    # Credit card payments (abonos): liquid account decreases when paying TC bill
    cc_payments = db.scalars(
        select(CreditCardPayment).where(
            CreditCardPayment.user_id == user.id,
            CreditCardPayment.is_void == False,
        )
    ).all()
    for cp in cc_payments:
        if cp.account_id in account_by_id:
            saldos[account_by_id[cp.account_id].name] -= float(cp.amount)

    for acc in account_by_id.values():
        if acc.account_type != "credit_card":
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
            "payment_frequency": d.payment_frequency or "monthly",
        })

    return {
        "total_pendiente": round(total_pendiente, 2),
        "items": items,
    }


def build_cc_balances(db: Session, telegram_user_id: int) -> list[dict]:
    """Retorna el saldo pendiente de cada tarjeta de crédito activa.

    Lógica por tipo de TC:
    - GTQ   : balance en Q  = sum(EGR.amount) − sum(payment.amount donde amount_usd IS NULL)
    - USD   : balance en $  = sum(EGR.amount) − sum(payment.amount_usd)
              (EGR.amount para USD TC ya se almacena en $)
    - MIXTO : balance dual Q + $
              Cargos Q  → movements donde amount_foreign IS NULL  (m.amount en Q)
              Cargos $  → movements donde amount_foreign IS NOT NULL (m.amount_foreign en $)
              Pago Q-portion → payment donde amount_usd IS NULL  (reduce saldo Q)
              Pago $-portion → payment donde amount_usd IS NOT NULL (reduce saldo $)
              balance total en Q = balance_gtq_portion + balance_usd_portion * tc_exchange_rate
    """
    user = get_user_or_raise(db, telegram_user_id)

    cc_accounts = db.scalars(
        select(Account).where(
            Account.user_id == user.id,
            Account.account_type == "credit_card",
            Account.is_active == True,
        ).order_by(Account.sort_order, Account.name)
    ).all()

    if not cc_accounts:
        return []

    cc_ids = [a.id for a in cc_accounts]
    tc_type_by_id = {a.id: (a.tc_type or "GTQ") for a in cc_accounts}

    # ── Acumuladores de cargos ────────────────────────────────────────────────
    # charges_q   : cargos en Q  (GTQ TC: todos; MIXTO: porción Q; USD TC: 0)
    # charges_usd : cargos en $  (USD TC: m.amount; MIXTO porción $: m.amount_foreign)
    # charges_visacuota_q : cuotas de plan de cuotas (siempre en Q para GTQ/MIXTO)
    # charges_visacuota_usd: cuotas de plan de cuotas para USD TC (en $)
    charges_q:             dict[int, float] = defaultdict(float)
    charges_usd:           dict[int, float] = defaultdict(float)
    charges_visacuota_q:   dict[int, float] = defaultdict(float)
    charges_visacuota_usd: dict[int, float] = defaultdict(float)

    tc_movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.credit_card_account_id.in_(cc_ids),
            Movement.is_void == False,
        )
    ).all()

    for m in tc_movements:
        tc_type = tc_type_by_id.get(m.credit_card_account_id, "GTQ")
        is_plan = m.installment_plan_id is not None

        if tc_type == "USD":
            # m.amount ya está en $ para TC USD
            amt = float(m.amount)
            charges_usd[m.credit_card_account_id] += amt
            if is_plan:
                charges_visacuota_usd[m.credit_card_account_id] += amt

        elif tc_type == "MIXTO":
            if m.amount_foreign is not None:
                # Cargo en USD sobre TC MIXTO → usar amount_foreign ($ reales)
                amt_usd = float(m.amount_foreign)
                charges_usd[m.credit_card_account_id] += amt_usd
                # m.amount es estimación Q (amount_foreign * tc_rate), NO se acumula al saldo Q
            else:
                # Cargo en Q sobre TC MIXTO
                amt_q = float(m.amount)
                charges_q[m.credit_card_account_id] += amt_q
                if is_plan:
                    charges_visacuota_q[m.credit_card_account_id] += amt_q

        else:  # GTQ
            amt = float(m.amount)
            charges_q[m.credit_card_account_id] += amt
            if is_plan:
                charges_visacuota_q[m.credit_card_account_id] += amt

    # ── Acumuladores de pagos ─────────────────────────────────────────────────
    # Cuando amount_usd IS NOT NULL → pago de porción $ (GTQ o MIXTO)
    #   amount_usd reduce el saldo en $
    #   amount     = Q salidos de la cuenta líquida (no reduce saldo Q de la TC)
    # Cuando amount_usd IS NULL → pago de porción Q
    #   amount     = Q salidos de la cuenta Y reducen saldo Q de la TC
    payments_q_portion:   dict[int, float] = defaultdict(float)  # reduce saldo Q de la TC
    payments_usd_portion: dict[int, float] = defaultdict(float)  # reduce saldo $ de la TC

    tc_payments = db.scalars(
        select(CreditCardPayment).where(
            CreditCardPayment.user_id == user.id,
            CreditCardPayment.credit_card_account_id.in_(cc_ids),
            CreditCardPayment.is_void == False,
        )
    ).all()

    for p in tc_payments:
        if p.amount_usd is not None:
            payments_usd_portion[p.credit_card_account_id] += float(p.amount_usd)
        else:
            payments_q_portion[p.credit_card_account_id] += float(p.amount)

    # ── Restante de planes de cuotas activos (visacuotas) ─────────────────────
    # visacuota_remaining = cuotas pendientes × monthly_amount (compromiso futuro)
    active_plans = db.scalars(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.credit_card_account_id.in_(cc_ids),
            CreditCardInstallmentPlan.status == "active",
            CreditCardInstallmentPlan.is_active == True,
        )
    ).all()

    visacuota_remaining_by_acc: dict[int, float] = defaultdict(float)
    for plan in active_plans:
        paid_count = db.scalar(
            select(func.count()).where(
                Movement.installment_plan_id == plan.id,
                Movement.is_void == False,
            )
        ) or 0
        remaining_cuotas = max(0, plan.total_installments - paid_count)
        visacuota_remaining_by_acc[plan.credit_card_account_id] += (
            remaining_cuotas * float(plan.monthly_amount)
        )

    # ── Construcción del resultado ────────────────────────────────────────────
    result = []
    for acc in cc_accounts:
        tc_type = tc_type_by_id[acc.id]
        rate = float(acc.tc_exchange_rate or 8.0)

        if tc_type == "USD":
            balance_usd_portion = round(charges_usd[acc.id] - payments_usd_portion[acc.id], 2)
            balance_gtq_portion = 0.0
            balance     = balance_usd_portion          # mostrado en $
            balance_gtq = round(balance_usd_portion * rate, 2)
            visacuota_balance   = round(charges_visacuota_usd[acc.id], 2)  # en $

        elif tc_type == "MIXTO":
            balance_gtq_portion = round(charges_q[acc.id] - payments_q_portion[acc.id], 2)
            balance_usd_portion = round(charges_usd[acc.id] - payments_usd_portion[acc.id], 2)
            balance_gtq = round(balance_gtq_portion + balance_usd_portion * rate, 2)
            balance     = balance_gtq                  # MIXTO total en Q
            visacuota_balance   = round(charges_visacuota_q[acc.id], 2)   # visacuotas son Q

        else:  # GTQ
            balance_gtq_portion = round(charges_q[acc.id] - payments_q_portion[acc.id], 2)
            balance_usd_portion = 0.0
            balance     = balance_gtq_portion
            balance_gtq = balance
            visacuota_balance   = round(charges_visacuota_q[acc.id], 2)

        # regular_balance: saldo total menos visacuotas (en unidades nativas de la TC)
        regular_balance = round(balance - visacuota_balance, 2)

        result.append({
            "id": int(acc.id),
            "name": acc.name,
            "tc_type": tc_type,
            "balance": balance,
            "balance_gtq": balance_gtq,
            "balance_gtq_portion": balance_gtq_portion,  # MIXTO/GTQ: saldo en Q
            "balance_usd_portion": balance_usd_portion,  # MIXTO/USD: saldo en $
            "regular_balance": regular_balance,
            "visacuota_balance": visacuota_balance,
            "visacuota_remaining": round(visacuota_remaining_by_acc.get(acc.id, 0.0), 2),
            "credit_limit": float(acc.credit_limit) if acc.credit_limit is not None else None,
            "visacuotas_limit": float(acc.visacuotas_limit) if acc.visacuotas_limit is not None else None,
            "tc_exchange_rate": float(acc.tc_exchange_rate) if acc.tc_exchange_rate is not None else None,
            "billing_close_day": acc.billing_close_day,
            "payment_due_day": acc.payment_due_day,
        })

    return result


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
        select(LoanPayment).where(
            LoanPayment.user_id == user.id,
            LoanPayment.is_void == False,
        )
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


def build_neto(
    db: Session,
    telegram_user_id: int,
    fallback_tc: float,
    _networth: dict | None = None,
) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    networth = _networth if _networth is not None else build_networth(db, telegram_user_id, fallback_tc)

    debts = db.scalars(
        select(Debt).where(Debt.user_id == user.id, Debt.status == "active")
    ).all()

    pasivos_deudas = round(
        sum((d.total_installments - d.paid_installments) * float(d.installment_amount) for d in debts),
        2,
    )

    # Credit card outstanding balances also count as pasivos
    # Use balance_gtq so USD-denominated TC balances are converted to Q
    cc_balances = build_cc_balances(db, telegram_user_id)
    pasivos_tc = round(sum(cc["balance_gtq"] for cc in cc_balances if cc["balance_gtq"] > 0), 2)

    pasivos = round(pasivos_deudas + pasivos_tc, 2)
    patrimonio_bruto = round(networth["total_gtq"], 2)
    patrimonio_neto = round(patrimonio_bruto - pasivos, 2)

    # ── Compromiso Visacuotas: cuotas futuras aún no generadas ───────────────
    # Las cuotas ya generadas (EGR) forman parte del saldo TC (pasivos_tc).
    # Las cuotas futuras aún no se han generado, por tanto no son pasivos
    # actuales — pero sí representan un compromiso financiero futuro.
    today = today_gt()
    active_plans = db.scalars(
        select(CreditCardInstallmentPlan).where(
            CreditCardInstallmentPlan.user_id == user.id,
            CreditCardInstallmentPlan.is_active == True,
            CreditCardInstallmentPlan.status == "active",
        )
    ).all()

    compromiso_futuro = 0.0
    for plan in active_plans:
        paid = db.scalar(
            select(func.count()).where(
                Movement.installment_plan_id == plan.id,
                Movement.is_void == False,
            )
        ) or 0
        for i in range(paid, plan.total_installments):
            charge_date = _add_months(plan.first_charge_date, i)
            if charge_date > today:
                compromiso_futuro += float(plan.monthly_amount)

    compromiso_visacuotas = round(compromiso_futuro, 2)
    patrimonio_neto_ajustado = round(patrimonio_neto - compromiso_visacuotas, 2)

    return {
        "patrimonio_bruto": patrimonio_bruto,
        "pasivos": pasivos,
        "patrimonio_neto": patrimonio_neto,
        "compromiso_visacuotas": compromiso_visacuotas,
        "patrimonio_neto_ajustado": patrimonio_neto_ajustado,
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
    gastos_por_categoria: dict[str, float] = defaultdict(float)
    detalle_por_categoria: dict[str, list[dict]] = defaultdict(list)

    for m in movements:
        if m.movement_type == "ING":
            ingresos += float(m.amount)

        elif m.movement_type == "EGR":
            egresos += float(m.amount)
            cat_name = "Sin categoría"
            if m.category_id and m.category_id in category_by_id:
                cat_name = category_by_id[m.category_id].name
            gastos_por_categoria[cat_name] += float(m.amount)
            detalle_por_categoria[cat_name].append({
                "id": int(m.id),
                "date": m.movement_date.isoformat(),
                "amount": round(float(m.amount), 2),
                "note": m.note,
                "record_type": "movement",
            })

    # Debt payments are now stored in debt_payments (migrated from EGR movements).
    # Include them as egresos so period summaries remain accurate.
    debt_pmts = db.scalars(
        select(DebtPayment).where(
            DebtPayment.user_id == user.id,
            DebtPayment.payment_date >= fecha_inicio,
            DebtPayment.payment_date <= fecha_fin,
            DebtPayment.is_void == False,
        )
    ).all()
    debts_by_id = {}
    if debt_pmts:
        debts_by_id = {
            d.id: d
            for d in db.scalars(select(Debt).where(Debt.user_id == user.id)).all()
        }
    for dp in debt_pmts:
        egresos += float(dp.amount)
        debt = debts_by_id.get(dp.debt_id)
        cat_name = f"Deuda: {debt.name}" if debt else "Pagos de deuda"
        gastos_por_categoria[cat_name] += float(dp.amount)
        detalle_por_categoria[cat_name].append({
            "id": int(dp.id),
            "date": dp.payment_date.isoformat(),
            "amount": round(float(dp.amount), 2),
            "note": dp.note,
            "record_type": "debt_payment",
        })

    # Sort items within each category by date desc
    for cat in detalle_por_categoria:
        detalle_por_categoria[cat].sort(key=lambda x: x["date"], reverse=True)

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
        "detalle_por_categoria": dict(detalle_por_categoria),
        "top_gastos": top_gastos,
    }


def build_savings_goals(db: Session, telegram_user_id: int, ahorro_breakdown: dict[str, float] = None) -> list[dict]:
    user = get_user_or_raise(db, telegram_user_id)
    goals = db.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == user.id, SavingsGoal.is_active == True)
    ).all()

    # Sum movements tagged to each goal (GUARDAR adds, RETIRAR subtracts)
    # Since only GUARDAR movements receive savings_goal_id today, all will be positive.
    # If a RETIRAR is ever tagged, it would be subtracted via source_account logic — for now
    # we treat every tagged movement's amount as a deposit (+).
    tagged_movs = db.scalars(
        select(Movement).where(
            Movement.user_id == user.id,
            Movement.savings_goal_id.is_not(None),
            Movement.is_void == False,
        )
    ).all()

    account_by_id = get_accounts_map(db, user.id)

    goal_totals: dict[int, float] = defaultdict(float)
    for m in tagged_movs:
        if m.source_account_id and m.target_account_id:
            target_acc = account_by_id.get(m.target_account_id)
            if target_acc and target_acc.account_type == "savings":
                goal_totals[m.savings_goal_id] += float(m.amount)   # GUARDAR
            else:
                goal_totals[m.savings_goal_id] -= float(m.amount)   # RETIRAR
        else:
            goal_totals[m.savings_goal_id] += float(m.amount)

    return [
        {
            "id": int(g.id),
            "name": g.name,
            "target_amount": float(g.target_amount),
            "account_name": g.account_name,
            "current_amount": round(max(0.0, goal_totals.get(g.id, 0.0)), 2),
            "is_active": g.is_active,
        }
        for g in goals
    ]


def build_dashboard(db: Session, telegram_user_id: int, fallback_tc: float) -> dict:
    from app.services.loans_view_service import build_loans_view

    today = today_gt()
    dia_inicio, dia_fin = day_range(today)
    sem_inicio, sem_fin = week_range(today)
    mes_inicio, mes_fin = month_range(today)

    # Calcular networth una sola vez y reutilizarlo en build_neto
    networth = build_networth(db, telegram_user_id, fallback_tc)

    return {
        "networth": networth,
        "neto": build_neto(db, telegram_user_id, fallback_tc, _networth=networth),
        "resumen_dia": build_period_summary(db, telegram_user_id, "dia", dia_inicio, dia_fin),
        "resumen_semana": build_period_summary(db, telegram_user_id, "semana", sem_inicio, sem_fin),
        "resumen_mes": build_period_summary(db, telegram_user_id, "mes", mes_inicio, mes_fin),
        "prestamos_resumen": build_loans_view(db, telegram_user_id),
        "savings_goals": build_savings_goals(db, telegram_user_id),
    }