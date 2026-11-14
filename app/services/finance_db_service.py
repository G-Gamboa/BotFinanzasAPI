from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta, datetime

import pytz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Account, UserSetting, SavingsGoal
from app.services.finance_context import FinanceContext, resolve_context


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


def build_saldos_map(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict[str, float]:
    ctx = resolve_context(db, telegram_user_id, ctx)
    if "saldos" in ctx.memo:
        return dict(ctx.memo["saldos"])
    account_by_id = ctx.account_by_id
    saldos: dict[str, float] = defaultdict(float)

    # ING / EGR / MOV (non-loan transfers)
    movements = ctx.movements

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
    loans = [loan for loan in ctx.loans if loan.loan_type == "lent"]
    for loan in loans:
        saldos["Prestamos"] += float(loan.principal_amount)
        if loan.source_account_id and loan.source_account_id in account_by_id:
            saldos[account_by_id[loan.source_account_id].name] -= float(loan.principal_amount)

    # Loan payments (collected): liquid account credited + Prestamos decreases.
    # The original COBRAR movements (MOV type) credited the target liquid account
    # and debited Prestamos. We replicate that here from the loan_payments table.
    for payment in ctx.loan_payments:
        if payment.account_id in account_by_id:
            acc = account_by_id[payment.account_id]
            if acc.account_type != "credit_card":
                # Cobro de préstamo TC: account_id apunta a la TC, no a líquido
                saldos[acc.name] += float(payment.amount)
        saldos["Prestamos"] -= float(payment.amount)

    # Debt payments: liquid account decreases (replaces the old EGR movement)
    for dp in ctx.debt_payments:
        if dp.account_id in account_by_id:
            saldos[account_by_id[dp.account_id].name] -= float(dp.amount)

    # Credit card payments (abonos): liquid account decreases when paying TC bill
    for cp in ctx.cc_payments:
        if cp.account_id in account_by_id:
            saldos[account_by_id[cp.account_id].name] -= float(cp.amount)

    for acc in account_by_id.values():
        if acc.account_type != "credit_card":
            saldos[acc.name] += 0.0

    result = dict(sorted(saldos.items(), key=lambda x: x[0]))
    ctx.memo["saldos"] = result
    return dict(result)


def build_ahorro_breakdown(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    if "ahorro" in ctx.memo:
        return ctx.memo["ahorro"]
    account_by_id = ctx.account_by_id

    ahorro_por_cuenta = defaultdict(float)

    movements = [m for m in ctx.movements if m.movement_type == "MOV"]

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

    ctx.memo["ahorro"] = {
        "total": total,
        "items": items,
    }
    return ctx.memo["ahorro"]


def build_debts(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    debts = ctx.debts

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


def _last_close_date(today: date, billing_close_day: int) -> date:
    """Fecha de corte más reciente en o antes de hoy para el día de corte dado."""
    max_this = monthrange(today.year, today.month)[1]
    candidate = today.replace(day=min(billing_close_day, max_this))
    if candidate <= today:
        return candidate
    prev_month = today.month - 1 or 12
    prev_year  = today.year if today.month > 1 else today.year - 1
    return date(prev_year, prev_month, min(billing_close_day, monthrange(prev_year, prev_month)[1]))


def build_cc_balances(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> list[dict]:
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
    ctx = resolve_context(db, telegram_user_id, ctx)
    if "cc_balances" in ctx.memo:
        return ctx.memo["cc_balances"]

    cc_accounts = sorted(
        (a for a in ctx.accounts if a.account_type == "credit_card" and a.is_active),
        key=lambda a: (a.sort_order, a.name),
    )

    if not cc_accounts:
        return []

    cc_ids = {a.id for a in cc_accounts}
    tc_type_by_id = {a.id: (a.tc_type or "GTQ") for a in cc_accounts}

    _today = today_gt()
    close_date_by_id: dict[int, date | None] = {
        a.id: (_last_close_date(_today, a.billing_close_day) if a.billing_close_day else None)
        for a in cc_accounts
    }

    # ── Acumuladores de cargos ────────────────────────────────────────────────
    # charges_q   : cargos en Q  (GTQ TC: todos; MIXTO: porción Q; USD TC: 0)
    # charges_usd : cargos en $  (USD TC: m.amount; MIXTO porción $: m.amount_foreign)
    # charges_visacuota_q : cuotas de plan de cuotas (siempre en Q para GTQ/MIXTO)
    # charges_visacuota_usd: cuotas de plan de cuotas para USD TC (en $)
    # charges_loans_gtq: cargos is_third_party=True convertidos a Q (para desglose préstamos TC)
    charges_q:             dict[int, float] = defaultdict(float)
    charges_usd:           dict[int, float] = defaultdict(float)
    charges_visacuota_q:   dict[int, float] = defaultdict(float)
    charges_visacuota_usd: dict[int, float] = defaultdict(float)
    charges_loans_gtq:     dict[int, float] = defaultdict(float)

    # Cargos acumulados hasta la fecha de corte (para balance_at_close)
    charges_q_at_close:   dict[int, float] = defaultdict(float)
    charges_usd_at_close: dict[int, float] = defaultdict(float)

    tc_movements = [m for m in ctx.movements if m.credit_card_account_id in cc_ids]

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

        # Acumular cargos de préstamos TC separados (is_third_party) en Q equivalente
        if m.is_third_party:
            if tc_type == "USD":
                charges_loans_gtq[m.credit_card_account_id] += float(m.amount) * float(
                    next((a.tc_exchange_rate or 8.0 for a in cc_accounts if a.id == m.credit_card_account_id), 8.0)
                )
            elif tc_type == "MIXTO" and m.amount_foreign is not None:
                charges_loans_gtq[m.credit_card_account_id] += float(m.amount_foreign) * float(
                    next((a.tc_exchange_rate or 8.0 for a in cc_accounts if a.id == m.credit_card_account_id), 8.0)
                )
            else:
                charges_loans_gtq[m.credit_card_account_id] += float(m.amount)

        # Acumular cargos hasta la fecha de corte
        close_date = close_date_by_id.get(m.credit_card_account_id)
        if close_date and m.movement_date <= close_date:
            if tc_type == "USD":
                charges_usd_at_close[m.credit_card_account_id] += float(m.amount)
            elif tc_type == "MIXTO":
                if m.amount_foreign is not None:
                    charges_usd_at_close[m.credit_card_account_id] += float(m.amount_foreign)
                else:
                    charges_q_at_close[m.credit_card_account_id] += float(m.amount)
            else:
                charges_q_at_close[m.credit_card_account_id] += float(m.amount)

    # ── Acumuladores de pagos ─────────────────────────────────────────────────
    # Cuando amount_usd IS NOT NULL → pago de porción $ (GTQ o MIXTO)
    #   amount_usd reduce el saldo en $
    #   amount     = Q salidos de la cuenta líquida (no reduce saldo Q de la TC)
    # Cuando amount_usd IS NULL → pago de porción Q
    #   amount     = Q salidos de la cuenta Y reducen saldo Q de la TC
    payments_q_portion:   dict[int, float] = defaultdict(float)  # reduce saldo Q de la TC
    payments_usd_portion: dict[int, float] = defaultdict(float)  # reduce saldo $ de la TC

    # Pagos hasta corte y después del corte (para pending_to_pay)
    payments_q_at_close:    dict[int, float] = defaultdict(float)
    payments_usd_at_close:  dict[int, float] = defaultdict(float)
    payments_q_since_close:   dict[int, float] = defaultdict(float)
    payments_usd_since_close: dict[int, float] = defaultdict(float)

    tc_payments = [p for p in ctx.cc_payments if p.credit_card_account_id in cc_ids]

    for p in tc_payments:
        if p.amount_usd is not None:
            payments_usd_portion[p.credit_card_account_id] += float(p.amount_usd)
        else:
            payments_q_portion[p.credit_card_account_id] += float(p.amount)

        close_date = close_date_by_id.get(p.credit_card_account_id)
        if close_date:
            if p.payment_date <= close_date:
                if p.amount_usd is not None:
                    payments_usd_at_close[p.credit_card_account_id] += float(p.amount_usd)
                else:
                    payments_q_at_close[p.credit_card_account_id] += float(p.amount)
            else:
                if p.amount_usd is not None:
                    payments_usd_since_close[p.credit_card_account_id] += float(p.amount_usd)
                else:
                    payments_q_since_close[p.credit_card_account_id] += float(p.amount)

    # ── Cobros de préstamos TC (LoanPayments donde account_id es una TC) ────────
    # Cuando alguien paga de vuelta un préstamo que salió de TC, el cobro se
    # registra con account_id = cc_account.id. Eso equivale a un abono a la TC.
    loan_repayments_received_q: dict[int, float] = defaultdict(float)
    tc_loan_payments = [lp for lp in ctx.loan_payments if lp.account_id in cc_ids]
    for lp in tc_loan_payments:
        payments_q_portion[lp.account_id] += float(lp.amount)
        loan_repayments_received_q[lp.account_id] += float(lp.amount)
        close_date = close_date_by_id.get(lp.account_id)
        if close_date:
            if lp.payment_date <= close_date:
                payments_q_at_close[lp.account_id] += float(lp.amount)
            else:
                payments_q_since_close[lp.account_id] += float(lp.amount)

    # ── Restante de planes de cuotas activos (visacuotas) ─────────────────────
    # visacuota_remaining = cuotas pendientes × monthly_amount (compromiso futuro)
    active_plans = [
        p for p in ctx.plans
        if p.credit_card_account_id in cc_ids and p.status == "active" and p.is_active
    ]
    _paid_by_plan = ctx.paid_by_plan

    visacuota_remaining_by_acc: dict[int, float] = defaultdict(float)
    for plan in active_plans:
        paid_count = _paid_by_plan.get(plan.id, 0)
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

        # ── Balance al corte y pendiente por pagar ───────────────────────────
        close_date = close_date_by_id.get(acc.id)
        pending_usd_portion = None
        if close_date:
            if tc_type == "USD":
                _bal_close_usd = round(charges_usd_at_close[acc.id] - payments_usd_at_close[acc.id], 2)
                balance_at_close_gtq = round(max(0.0, _bal_close_usd) * rate, 2)
                _pend_usd        = max(0.0, round(_bal_close_usd - payments_usd_since_close[acc.id], 2))
                pending_to_pay_gtq   = round(_pend_usd * rate, 2)
                pending_usd_portion  = _pend_usd
            elif tc_type == "MIXTO":
                _bal_close_q   = round(charges_q_at_close[acc.id]   - payments_q_at_close[acc.id], 2)
                _bal_close_usd = round(charges_usd_at_close[acc.id] - payments_usd_at_close[acc.id], 2)
                balance_at_close_gtq = round(max(0.0, _bal_close_q) + max(0.0, _bal_close_usd) * rate, 2)
                _pend_q   = max(0.0, round(_bal_close_q   - payments_q_since_close[acc.id], 2))
                _pend_usd = max(0.0, round(_bal_close_usd - payments_usd_since_close[acc.id], 2))
                pending_to_pay_gtq  = round(_pend_q + _pend_usd * rate, 2)
                pending_usd_portion = _pend_usd
            else:  # GTQ
                _bal_close_q     = round(charges_q_at_close[acc.id] - payments_q_at_close[acc.id], 2)
                balance_at_close_gtq = max(0.0, _bal_close_q)
                pending_to_pay_gtq   = max(0.0, round(_bal_close_q - payments_q_since_close[acc.id], 2))
        else:
            balance_at_close_gtq = None
            pending_to_pay_gtq   = None

        # ── Desglose préstamos TC ─────────────────────────────────────────────
        # balance_loans_gtq: saldo pendiente de préstamos TC (lo que deben de devolverte)
        # balance_own_gtq:   saldo que realmente debes pagar tú al banco
        _loans_charges = round(charges_loans_gtq.get(acc.id, 0.0), 2)
        _loans_received = round(loan_repayments_received_q.get(acc.id, 0.0), 2)
        _loans_raw = max(0.0, _loans_charges - _loans_received)
        # Nunca mostrar préstamos > saldo total (pasa cuando el usuario pagó al banco
        # parte que "correspondía" a préstamos antes de cobrarlos)
        _balance_floor = max(0.0, balance_gtq)
        balance_loans_gtq_val = round(min(_loans_raw, _balance_floor), 2)
        balance_own_gtq_val = round(_balance_floor - balance_loans_gtq_val, 2)

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
            "last_close_date": close_date.isoformat() if close_date else None,
            "balance_at_close_gtq": balance_at_close_gtq,
            "pending_to_pay_gtq": pending_to_pay_gtq,
            "pending_usd_portion": pending_usd_portion,
            "balance_loans_gtq": balance_loans_gtq_val,
            "balance_own_gtq": balance_own_gtq_val,
        })

    ctx.memo["cc_balances"] = result
    return result


def build_networth(db: Session, telegram_user_id: int, fallback_tc: float, ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    tc = float(ctx.setting.usd_to_gtq) if ctx.setting else fallback_tc

    account_type_map = {a.name: a.account_type for a in ctx.accounts}

    saldos = build_saldos_map(db, telegram_user_id, ctx)
    ahorro_data = build_ahorro_breakdown(db, telegram_user_id, ctx)

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

    loan_person_by_id = {lp.id: lp.name for lp in ctx.loan_people}

    prestamos_tmp: dict[str, float] = defaultdict(float)

    loans = [loan for loan in ctx.loans if loan.loan_type == "lent"]
    loans_by_id = {loan.id: loan for loan in loans}
    # Préstamos TC (source_tc_account_id != None) se excluyen del networth:
    # su activo (alguien me debe) y su pasivo (yo le debo al banco) se anulan.
    # pasivos_tc ya usa balance_own_gtq que los excluye, así que aquí tampoco
    # los contamos como activo para mantener la simetría.
    tc_loan_ids = {loan.id for loan in loans if loan.source_tc_account_id is not None}

    for loan in loans:
        if loan.source_tc_account_id is not None:
            continue
        person = loan_person_by_id.get(loan.loan_person_id, "General")
        prestamos_tmp[person] += float(loan.principal_amount)

    for payment in ctx.loan_payments:
        if payment.loan_id in tc_loan_ids:
            continue
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
    ctx: FinanceContext | None = None,
) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    networth = _networth if _networth is not None else build_networth(db, telegram_user_id, fallback_tc, ctx)

    debts = [d for d in ctx.debts if d.status == "active"]

    pasivos_deudas = round(
        sum((d.total_installments - d.paid_installments) * float(d.installment_amount) for d in debts),
        2,
    )

    # Credit card outstanding balances also count as pasivos.
    # Solo se cuenta balance_own_gtq (gastos propios); balance_loans_gtq lo cubrirán
    # los prestatarios vía cobro de préstamo, no es pasivo real del usuario.
    cc_balances = build_cc_balances(db, telegram_user_id, ctx)
    pasivos_tc = round(sum(cc["balance_own_gtq"] for cc in cc_balances if cc["balance_own_gtq"] > 0), 2)

    pasivos = round(pasivos_deudas + pasivos_tc, 2)
    patrimonio_bruto = round(networth["total_gtq"], 2)
    patrimonio_neto = round(patrimonio_bruto - pasivos, 2)

    # ── Compromiso Visacuotas: cuotas futuras aún no generadas ───────────────
    # Las cuotas ya generadas (EGR) forman parte del saldo TC (pasivos_tc).
    # Las cuotas futuras aún no se han generado, por tanto no son pasivos
    # actuales — pero sí representan un compromiso financiero futuro.
    today = today_gt()
    active_plans = [p for p in ctx.plans if p.is_active and p.status == "active" and not p.is_loan]
    _neto_paid_by_plan = ctx.paid_by_plan

    compromiso_futuro = 0.0
    for plan in active_plans:
        paid = _neto_paid_by_plan.get(plan.id, 0)
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
    ctx: FinanceContext | None = None,
) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)

    movements = [m for m in ctx.movements if fecha_inicio <= m.movement_date <= fecha_fin]

    category_by_id = {c.id: c for c in ctx.categories}

    ingresos = 0.0
    egresos = 0.0
    gastos_por_categoria: dict[str, float] = defaultdict(float)
    detalle_por_categoria: dict[str, list[dict]] = defaultdict(list)

    for m in movements:
        if m.movement_type == "ING":
            ingresos += float(m.amount)

        elif m.movement_type == "EGR":
            if m.is_third_party:
                continue  # cargo TC de préstamo a tercero: no es gasto propio
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
    debt_pmts = [dp for dp in ctx.debt_payments if fecha_inicio <= dp.payment_date <= fecha_fin]
    debts_by_id = {d.id: d for d in ctx.debts}
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


def build_savings_goals(
    db: Session,
    telegram_user_id: int,
    ahorro_breakdown: dict[str, float] = None,
    ctx: FinanceContext | None = None,
) -> list[dict]:
    ctx = resolve_context(db, telegram_user_id, ctx)
    goals = db.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == ctx.user.id, SavingsGoal.is_active == True)
    ).all()

    # Sum movements tagged to each goal (GUARDAR adds, RETIRAR subtracts)
    # Since only GUARDAR movements receive savings_goal_id today, all will be positive.
    # If a RETIRAR is ever tagged, it would be subtracted via source_account logic — for now
    # we treat every tagged movement's amount as a deposit (+).
    tagged_movs = [m for m in ctx.movements if m.savings_goal_id is not None]

    account_by_id = ctx.account_by_id

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


def build_dashboard(db: Session, telegram_user_id: int, fallback_tc: float, ctx: FinanceContext | None = None) -> dict:
    from app.services.loans_view_service import build_loans_view

    ctx = resolve_context(db, telegram_user_id, ctx)
    today = today_gt()
    dia_inicio, dia_fin = day_range(today)
    sem_inicio, sem_fin = week_range(today)
    mes_inicio, mes_fin = month_range(today)

    # Calcular networth una sola vez y reutilizarlo en build_neto
    networth = build_networth(db, telegram_user_id, fallback_tc, ctx)

    return {
        "networth": networth,
        "neto": build_neto(db, telegram_user_id, fallback_tc, _networth=networth, ctx=ctx),
        "resumen_dia": build_period_summary(db, telegram_user_id, "dia", dia_inicio, dia_fin, ctx),
        "resumen_semana": build_period_summary(db, telegram_user_id, "semana", sem_inicio, sem_fin, ctx),
        "resumen_mes": build_period_summary(db, telegram_user_id, "mes", mes_inicio, mes_fin, ctx),
        "prestamos_resumen": build_loans_view(db, telegram_user_id, ctx),
        "savings_goals": build_savings_goals(db, telegram_user_id, ctx=ctx),
    }