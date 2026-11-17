"""Calendario financiero: lo planeado (programados) más lo que el bot ya sabe
(cuotas de deudas, cortes y pagos de tarjeta, visacuotas), y su confirmación
como movimientos reales."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CalendarNote, ScheduledItem, ScheduledOccurrence
from app.schemas.transactions import CreditCardPaymentRequest, MovementCreateRequest
from app.services.debt_service import advance_due_date, pay_debt
from app.services.finance_context import FinanceContext, resolve_context
from app.services.loan_collection_service import collection_rows
from app.services.finance_db_service import (
    _add_months,
    build_cc_balances,
    build_period_summary,
    build_saldos_map,
    today_gt,
)
from app.services.transaction_service import create_movement, create_tc_payment

KINDS = {"ingreso", "pago", "abono", "cargo_tc", "recordatorio"}
RECURRENCES = {"none", "weekly", "biweekly", "monthly"}
LIQUID_TYPES = {"cash", "bank"}
MAX_OCCURRENCES = 400


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe usar formato YYYY-MM-DD.")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def item_dates(item: ScheduledItem, start: date, end: date) -> list[date]:
    """Fechas de un programado que caen dentro de [start, end]."""
    first = item.start_date
    if first is None or first > end:
        return []
    last = min(end, item.end_date) if item.end_date else end
    if item.recurrence == "none":
        return [first] if start <= first <= last else []

    dates: list[date] = []
    for n in range(MAX_OCCURRENCES):
        if item.recurrence == "weekly":
            current = first + timedelta(weeks=n)
        elif item.recurrence == "biweekly":
            current = first + timedelta(weeks=2 * n)
        else:
            current = _add_months(first, n)
        if current > last:
            break
        if current >= start:
            dates.append(current)
    return dates


def next_payment_date(close_date: date, payment_due_day: int) -> date:
    """Primera fecha de pago posterior a un corte."""
    day = min(payment_due_day, monthrange(close_date.year, close_date.month)[1])
    candidate = close_date.replace(day=day)
    if candidate > close_date:
        return candidate
    following = _add_months(close_date.replace(day=1), 1)
    return following.replace(day=min(payment_due_day, monthrange(following.year, following.month)[1]))


def _day_in_month(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


class _Lookups:
    def __init__(self, ctx: FinanceContext):
        self.accounts = ctx.account_by_id
        self.categories = {c.id: c for c in ctx.categories}
        self.rate_default = float(ctx.setting.usd_to_gtq) if ctx.setting else 7.7
        self.live_movements = {m.id for m in ctx.movements}
        self.live_cc_payments = {p.id for p in ctx.cc_payments}

    def rate_for(self, credit_card_account_id: int | None) -> float:
        acc = self.accounts.get(credit_card_account_id) if credit_card_account_id else None
        if acc is not None and acc.tc_exchange_rate is not None:
            return float(acc.tc_exchange_rate)
        return self.rate_default

    def record_alive(self, occ: ScheduledOccurrence) -> bool:
        if occ.record_type == "movement":
            return occ.record_id in self.live_movements
        if occ.record_type == "cc_payment":
            return occ.record_id in self.live_cc_payments
        return True


def _load_scheduled(db: Session, user_id: int):
    items = db.scalars(
        select(ScheduledItem).where(ScheduledItem.user_id == user_id, ScheduledItem.is_active == True)
    ).all()
    occs = db.scalars(select(ScheduledOccurrence).where(ScheduledOccurrence.user_id == user_id)).all()
    by_key = {(o.item_id, o.due_date): o for o in occs}
    return items, by_key


def _scheduled_row(item: ScheduledItem, due: date | None, occ: ScheduledOccurrence | None,
                   look: _Lookups, today: date) -> dict | None:
    if occ is not None and occ.status == "skipped":
        return None
    done = occ is not None and occ.status == "done" and look.record_alive(occ)
    amount = None
    if occ is not None and occ.amount is not None:
        amount = float(occ.amount)
    elif item.amount is not None:
        amount = float(item.amount)

    rate = look.rate_for(item.credit_card_account_id)
    amount_gtq = None
    if amount is not None:
        amount_gtq = round(amount * rate, 2) if item.currency == "USD" else round(amount, 2)

    account = look.accounts.get(item.account_id) if item.account_id else None
    category = look.categories.get(item.category_id) if item.category_id else None
    card = look.accounts.get(item.credit_card_account_id) if item.credit_card_account_id else None

    return {
        "key": f"s:{item.id}:{due.isoformat() if due else 'none'}",
        "source": "scheduled",
        "item_id": int(item.id),
        "date": due.isoformat() if due else None,
        "kind": item.kind,
        "concept": item.concept,
        "amount": amount,
        "currency": item.currency,
        "amount_gtq": amount_gtq,
        "note": item.note,
        "done": done,
        "late": bool(due and due < today and not done and item.kind in ("abono", "pago")),
        "action": None if done else "confirm",
        "recurring": item.recurrence != "none",
        "recurrence": item.recurrence,
        "needs_amount": amount is None and item.kind != "recordatorio",
        "account_name": account.name if account else None,
        "category_name": category.name if category else None,
        "payment_method": item.payment_method,
        "credit_card_account_id": int(card.id) if card else None,
        "credit_card_name": card.name if card else None,
        "record_type": occ.record_type if done and occ else None,
        "record_id": int(occ.record_id) if done and occ and occ.record_id else None,
    }


def _derived_row(key: str, source: str, due: date, kind: str, concept: str, amount: float | None,
                 today: date, *, done: bool = False, action: str | None = None, note: str | None = None,
                 currency: str = "GTQ", amount_gtq: float | None = None, **extra) -> dict:
    return {
        "key": key,
        "source": source,
        "item_id": None,
        "date": due.isoformat(),
        "kind": kind,
        "concept": concept,
        "amount": amount,
        "currency": currency,
        "amount_gtq": amount_gtq if amount_gtq is not None else amount,
        "note": note,
        "done": done,
        "late": bool(due < today and not done and kind in ("abono", "pago") and action),
        "action": action,
        "recurring": False,
        "recurrence": "none",
        "needs_amount": False,
        "account_name": None,
        "category_name": None,
        "payment_method": None,
        "credit_card_account_id": None,
        "credit_card_name": None,
        "record_type": None,
        "record_id": None,
        **extra,
    }


def _debt_rows(ctx: FinanceContext, start: date, end: date, today: date) -> list[dict]:
    rows: list[dict] = []
    debts_by_id = {d.id: d for d in ctx.debts}

    for debt in ctx.debts:
        if debt.status != "active":
            continue
        account = ctx.account_by_id.get(debt.payment_account_id) if debt.payment_account_id else None
        pending = max(debt.total_installments - debt.paid_installments, 0)
        current = debt.due_date
        if current is None:
            continue  # sin fecha fija: va en la lista "Sin fecha"
        for n in range(pending):
            if current > end:
                break
            if current >= start:
                left = pending - n - 1
                rows.append(_derived_row(
                    f"d:{debt.id}:{current.isoformat()}", "debt", current, "pago",
                    f"Cuota de {debt.name}", round(float(debt.installment_amount), 2), today,
                    action="confirm" if n == 0 else None,
                    note=(f"{debt.creditor} · queda 1 después de esta" if left == 1
                          else f"{debt.creditor} · quedan {left} después de esta" if left
                          else f"{debt.creditor} · última cuota"),
                    debt_id=int(debt.id),
                    account_name=account.name if account else None,
                ))
            if debt.payment_frequency == "none":
                break
            current = advance_due_date(current, debt.payment_frequency)

    for dp in ctx.debt_payments:
        if start <= dp.payment_date <= end:
            debt = debts_by_id.get(dp.debt_id)
            rows.append(_derived_row(
                f"dp:{dp.id}", "debt", dp.payment_date, "pago",
                f"Cuota de {debt.name}" if debt else "Pago de deuda",
                round(float(dp.amount), 2), today, done=True,
                record_type="debt_payment", record_id=int(dp.id),
            ))
    return rows


def _undated_debt_rows(ctx: FinanceContext, today: date) -> list[dict]:
    """Deudas activas sin fecha fija: se muestran aparte y no entran a la proyección."""
    rows: list[dict] = []
    for debt in ctx.debts:
        if debt.status != "active" or debt.due_date is not None:
            continue
        account = ctx.account_by_id.get(debt.payment_account_id) if debt.payment_account_id else None
        pending = max(debt.total_installments - debt.paid_installments, 0)
        if not pending:
            continue
        row = _derived_row(
            f"d:{debt.id}:none", "debt", today, "pago",
            f"Cuota de {debt.name}", round(float(debt.installment_amount), 2), today,
            action="confirm",
            note=(f"{debt.creditor} · sin fecha fija · "
                  + ("última cuota" if pending == 1 else f"quedan {pending} cuotas")),
            debt_id=int(debt.id),
            account_name=account.name if account else None,
        )
        row["date"] = None
        row["late"] = False
        rows.append(row)
    return rows


def _card_rows(cc_balances: list[dict], start: date, end: date, today: date) -> list[dict]:
    rows: list[dict] = []
    for tc in cc_balances:
        close_day = tc.get("billing_close_day")
        pay_day = tc.get("payment_due_day")
        last_close = date.fromisoformat(tc["last_close_date"]) if tc.get("last_close_date") else None
        upcoming_pay = next_payment_date(last_close, pay_day) if last_close and pay_day else None

        if close_day:
            due = _day_in_month(start.year, start.month, close_day)
            rows.append(_derived_row(
                f"tc:close:{tc['id']}:{due.isoformat()}", "card", due, "tarjeta",
                f"Corte de {tc['name']}", None, today,
                credit_card_account_id=tc["id"], credit_card_name=tc["name"],
            ))
        if pay_day:
            due = _day_in_month(start.year, start.month, pay_day)
            is_upcoming = upcoming_pay == due
            pending = float(tc.get("pending_to_pay_gtq") or 0.0) if is_upcoming else None
            paid_up = is_upcoming and pending is not None and pending <= 0.005
            rows.append(_derived_row(
                f"tc:pay:{tc['id']}:{due.isoformat()}", "card", due, "tarjeta",
                f"Fecha de pago de {tc['name']}", pending, today,
                done=paid_up,
                action="abonar" if is_upcoming and not paid_up else None,
                note="Falta por abonar para dejar el corte en cero" if is_upcoming and not paid_up else None,
                credit_card_account_id=tc["id"], credit_card_name=tc["name"],
            ))
    return rows


def _visacuota_rows(ctx: FinanceContext, start: date, end: date, today: date) -> list[dict]:
    rows: list[dict] = []
    paid_by_plan = ctx.paid_by_plan
    people = {p.id: p.name for p in ctx.loan_people}
    for plan in ctx.plans:
        if not plan.is_active or plan.status != "active":
            continue
        paid = paid_by_plan.get(plan.id, 0)
        card = ctx.account_by_id.get(plan.credit_card_account_id)
        for n in range(paid, plan.total_installments):
            due = _add_months(plan.first_charge_date, n)
            if due > end:
                break
            if due < start:
                continue
            who = people.get(plan.loan_person_id) if plan.is_loan else None
            rows.append(_derived_row(
                f"vc:{plan.id}:{due.isoformat()}", "visacuota", due, "cargo_tc",
                f"Visacuota {plan.name}", round(float(plan.monthly_amount), 2), today,
                note=f"Cuota {n + 1} de {plan.total_installments} · se carga sola"
                     + (f" · préstamo a {who}" if who else ""),
                credit_card_account_id=int(card.id) if card else None,
                credit_card_name=card.name if card else None,
            ))
    return rows


_KIND_ORDER = {"ingreso": 0, "cobro": 1, "abono": 2, "pago": 3, "cargo_tc": 4, "tarjeta": 5, "recordatorio": 6}


def _card_summaries(cc_balances: list[dict], scheduled_rows: list[dict]) -> list[dict]:
    """Por tarjeta: cuánto falta para el próximo pago y si los abonos planeados lo cubren."""
    cards = []
    for tc in cc_balances:
        last_close = date.fromisoformat(tc["last_close_date"]) if tc.get("last_close_date") else None
        pay_day = tc.get("payment_due_day")
        if not last_close or not pay_day:
            continue
        pay_date = next_payment_date(last_close, pay_day)
        at_close = float(tc.get("balance_at_close_gtq") or 0.0)
        pending = float(tc.get("pending_to_pay_gtq") or 0.0)
        planned = 0.0
        for row in scheduled_rows:
            if row["done"] or row["amount_gtq"] is None:
                continue
            if row["kind"] == "abono":
                if row["credit_card_account_id"] not in (None, tc["id"]):
                    continue
            elif row["kind"] != "cobro" or row["credit_card_account_id"] != tc["id"]:
                continue
            if row["date"] is None or row["date"] <= pay_date.isoformat():
                planned += row["amount_gtq"]
        cards.append({
            "id": tc["id"],
            "name": tc["name"],
            "close_date": last_close.isoformat(),
            "payment_date": pay_date.isoformat(),
            "at_close_gtq": round(at_close, 2),
            "paid_gtq": round(max(at_close - pending, 0.0), 2),
            "pending_gtq": round(pending, 2),
            "pending_usd": tc.get("pending_usd_portion"),
            "planned_gtq": round(planned, 2),
            "gap_gtq": round(pending - planned, 2),
            "loans_gtq": float(tc.get("balance_loans_gtq") or 0.0),
            "own_gtq": float(tc.get("balance_own_gtq") or 0.0),
            "tc_type": tc.get("tc_type") or "GTQ",
            "rate": float(tc.get("tc_exchange_rate") or 0.0) or None,
            "statement_override": bool(tc.get("statement_override")),
            "statement_q": tc.get("statement_q"),
            "statement_usd": tc.get("statement_usd"),
            "statement_computed_q": tc.get("statement_computed_q"),
            "statement_computed_usd": tc.get("statement_computed_usd"),
        })
    return cards


PLAN_DAYS_AFTER_INCOME = 2


def attach_payment_plans(cards: list[dict], ctx: FinanceContext, items, occ_by_key, look: "_Lookups",
                         cash_now: float, today: date) -> list[dict]:
    """Agrega a cada tarjeta un plan sugerido de abonos para dejar su corte en cero.

    - Lo ya abonado (desde Registrar o el Calendario) ya está descontado del pendiente.
    - Los abonos que ya planeaste y los cobros de préstamos de TC se respetan: se planea solo lo que falta.
    - Cada abono se sugiere 2 días después de un ingreso, y nunca deja tu efectivo por debajo
      del colchón mínimo en lo que resta hasta la última fecha de pago.
    - Con varias tarjetas, primero la que vence antes.
    - La porción en dólares va en un solo abono, el primer día en que alcanza completa,
      para saber qué día se pagan los dólares. Lo de quetzales se reparte como siempre.
    """
    buffer = float(ctx.setting.min_cash_buffer) if ctx.setting and ctx.setting.min_cash_buffer is not None else 500.0
    active = [c for c in cards if c["pending_gtq"] > 0.005 and c["payment_date"] >= today.isoformat()]
    for card in cards:
        card["plan"] = None
    if not active:
        return cards

    horizon = max(date.fromisoformat(c["payment_date"]) for c in active)
    rows = _cash_rows(ctx, items, occ_by_key, look, today - timedelta(days=LATE_WINDOW_DAYS), horizon, today)

    # Movimiento neto del efectivo por día; lo atrasado cuenta como hoy
    net: dict[date, float] = {}
    incomes: list[tuple[date, dict]] = []
    for row in rows:
        effect = cash_effect(row)
        if not effect:
            continue
        day = max(date.fromisoformat(row["date"]), today)
        net[day] = net.get(day, 0.0) + effect
        if effect > 0:
            incomes.append((day, row))

    days = sorted(set(net) | {today})
    end_balance: dict[date, float] = {}
    running = cash_now
    for day in days:
        running += net.get(day, 0.0)
        end_balance[day] = running

    def free_from(start: date) -> float:
        """Lo que se puede sacar el día `start` sin bajar del colchón en ningún día siguiente."""
        lowest = min(
            (bal for day, bal in end_balance.items() if day >= start),
            default=None,
        )
        before = [bal for day, bal in sorted(end_balance.items()) if day <= start]
        at_start = before[-1] if before else cash_now
        candidates = [at_start] + ([lowest] if lowest is not None else [])
        return min(candidates) - buffer

    def take(start: date, amount: float) -> None:
        if start not in end_balance:
            before = [bal for day, bal in sorted(end_balance.items()) if day < start]
            end_balance[start] = before[-1] if before else cash_now
        for day in list(end_balance):
            if day >= start:
                end_balance[day] -= amount

    liquid = [a for a in ctx.accounts if a.account_type in LIQUID_TYPES and a.is_active]
    saldos = build_saldos_map(ctx.db, ctx.telegram_user_id, ctx)
    richest = max(liquid, key=lambda a: saldos.get(a.name, 0.0)).name if liquid else None

    for card in sorted(active, key=lambda c: c["payment_date"]):
        pay_date = date.fromisoformat(card["payment_date"])
        # Lo ya planeado a mano (con fecha) y los cobros de TC cuentan como cubierto
        planned_rows = [
            r for r in rows
            if not r["done"] and r["amount_gtq"] and r["date"] <= card["payment_date"] and (
                (r["kind"] == "abono" and r["credit_card_account_id"] in (None, card["id"]))
                or (r["kind"] == "cobro" and r["credit_card_account_id"] == card["id"])
            )
        ]
        planned = round(sum(r["amount_gtq"] for r in planned_rows), 2)
        need = round(card["pending_gtq"] - planned, 2)

        # Dólares: lo que falta de la porción en $ después de los abonos en $ ya planeados
        rate = look.rate_for(card["id"])
        usd_pending = float(card.get("pending_usd") or 0.0)
        planned_usd_gtq = sum(
            r["amount_gtq"] for r in planned_rows if r["kind"] == "abono" and r.get("currency") == "USD"
        )
        usd_need = round(min(max(usd_pending * rate - planned_usd_gtq, 0.0), max(need, 0.0)), 2)
        usd_suggestion = None
        usd_unplaced = 0.0

        moments: list[tuple[date, str, str | None]] = [(today, "con lo que tienes hoy", None)]
        for income_day, row in incomes:
            when = min(income_day + timedelta(days=PLAN_DAYS_AFTER_INCOME), pay_date)
            if today <= income_day <= pay_date:
                label = f"2 días después de {row['concept']} ({income_day.day}/{income_day.month})"
                moments.append((max(when, today), label, row.get("account_name")))
        moments.sort(key=lambda m: m[0])

        suggestions = []
        if usd_need > 0.005:
            for when, reason, account in moments:
                if free_from(when) + 0.005 >= usd_need:
                    take(when, usd_need)
                    usd_suggestion = {
                        "date": when.isoformat(), "amount": usd_need, "usd": round(usd_need / rate, 2),
                        "currency": "USD", "account": account or richest, "reason": reason,
                    }
                    break
            if usd_suggestion is None:
                usd_unplaced = usd_need
            need = round(need - usd_need, 2)

        for when, reason, account in moments:
            if need <= 0.005:
                break
            free = free_from(when)
            amount = min(need, float(int(free))) if free < need else need
            if amount < 1:
                continue
            amount = round(amount, 2)
            take(when, amount)
            need = round(need - amount, 2)
            suggestions.append({
                "date": when.isoformat(), "amount": amount, "currency": "GTQ",
                "account": account or richest, "reason": reason,
            })

        if usd_suggestion:
            suggestions.append(usd_suggestion)
            suggestions.sort(key=lambda s: (s["date"], s["currency"] != "USD"))
        need = round(need + usd_unplaced, 2)

        card["plan"] = {
            "buffer": round(buffer, 2),
            "planned": planned,
            "suggestions": suggestions,
            "covered": need <= 0.005,
            "shortfall": round(max(need, 0.0), 2),
            "usd_unplaced": round(usd_unplaced / rate, 2) if usd_unplaced else None,
        }
    return cards


def _cash_rows(ctx: FinanceContext, items, occ_by_key, look: _Lookups,
               start: date, end: date, today: date) -> list[dict]:
    """Programados con fecha y cuotas de deuda dentro de [start, end]."""
    rows: list[dict] = []
    for item in items:
        for due in item_dates(item, start, end):
            row = _scheduled_row(item, due, occ_by_key.get((item.id, due)), look, today)
            if row:
                rows.append(row)
    rows += _debt_rows(ctx, start, end, today)
    rows += collection_rows(ctx, start, end, today)
    return rows


def cash_effect(row: dict) -> float:
    """Cuánto mueve el efectivo una fila pendiente: positivo entra, negativo sale."""
    if row["done"] or row["amount_gtq"] is None:
        return 0.0
    if row["kind"] == "ingreso":
        return row["amount_gtq"]
    if row["kind"] == "cobro":
        # El cobro de un préstamo de TC se abona a la tarjeta, no entra a tu efectivo
        return 0.0 if row["credit_card_account_id"] else row["amount_gtq"]
    if row["kind"] in ("pago", "abono") and row["payment_method"] != "credit_card":
        return -row["amount_gtq"]
    return 0.0


LATE_WINDOW_DAYS = 62


def build_projection(cash_now: float, rows: list[dict], today: date, end: date) -> dict | None:
    """Saldo esperado en cada fecha con movimiento, desde hoy hasta `end`.

    Lo atrasado sin confirmar se cuenta como si ocurriera hoy.
    """
    if end < today:
        return None
    by_day: dict[str, dict] = {}
    for row in rows:
        effect = cash_effect(row)
        if not effect or row["date"] > end.isoformat():
            continue
        day = max(row["date"], today.isoformat())
        slot = by_day.setdefault(day, {"in": 0.0, "out": 0.0})
        slot["in" if effect > 0 else "out"] += abs(effect)

    balance = cash_now
    days = []
    lowest = {"date": today.isoformat(), "balance": round(cash_now, 2)}
    first_negative = None
    for day in sorted(by_day):
        balance += by_day[day]["in"] - by_day[day]["out"]
        rounded = round(balance, 2)
        days.append({"date": day, "in": round(by_day[day]["in"], 2), "out": round(by_day[day]["out"], 2),
                     "balance": rounded})
        if rounded < lowest["balance"]:
            lowest = {"date": day, "balance": rounded}
        if first_negative is None and rounded < 0:
            first_negative = day
    return {
        "start_balance": round(cash_now, 2),
        "days": days,
        "end_balance": round(balance, 2),
        "lowest": lowest,
        "first_negative": first_negative,
    }


def build_month_close(db: Session, ctx: FinanceContext, year: int, month: int, today: date,
                      items=None, occ_by_key=None, look: _Lookups | None = None) -> dict:
    """Cierre de un mes ya terminado: qué entró, qué salió, cuánto se ahorró y qué quedó sin confirmar."""
    start, end = month_bounds(year, month)
    if items is None:
        items, occ_by_key = _load_scheduled(db, ctx.user.id)
    look = look or _Lookups(ctx)

    period = build_period_summary(db, ctx.telegram_user_id, "mes", start, end, ctx)

    saved = 0.0
    for m in ctx.movements:
        if m.movement_type != "MOV" or not (start <= m.movement_date <= end):
            continue
        source = ctx.account_by_id.get(m.source_account_id)
        target = ctx.account_by_id.get(m.target_account_id)
        if target is not None and target.name == "Ahorro" and (source is None or source.name != "Ahorro"):
            saved += float(m.amount)
        elif source is not None and source.name == "Ahorro" and (target is None or target.name != "Ahorro"):
            saved -= float(m.destination_amount) if m.destination_amount is not None else float(m.amount)

    pending = [
        r for r in _cash_rows(ctx, items, occ_by_key, look, start, end, today)
        if not r["done"] and r["kind"] != "recordatorio" and (r["source"] == "scheduled" or r["action"])
    ]
    pending.sort(key=lambda r: (r["date"], r["concept"].lower()))

    return {
        "year": year,
        "month": month,
        "ingresos": period["ingresos"],
        "egresos": period["egresos"],
        "balance": period["balance"],
        "ahorro": round(saved, 2),
        "top_gastos": period["top_gastos"][:3],
        "unconfirmed": [
            {"key": r["key"], "date": r["date"], "kind": r["kind"], "concept": r["concept"],
             "amount_gtq": r["amount_gtq"]}
            for r in pending
        ],
    }


def build_calendar(db: Session, telegram_user_id: int, year: int, month: int,
                   ctx: FinanceContext | None = None) -> dict:
    ctx = resolve_context(db, telegram_user_id, ctx)
    today = today_gt()
    start, end = month_bounds(year, month)
    look = _Lookups(ctx)
    cc_balances = build_cc_balances(db, telegram_user_id, ctx)
    items, occ_by_key = _load_scheduled(db, ctx.user.id)

    rows: list[dict] = []
    undated: list[dict] = []
    for item in items:
        if item.start_date is None:
            row = _scheduled_row(item, None, occ_by_key.get((item.id, None)), look, today)
            if row and not row["done"]:
                undated.append(row)
            continue
        for due in item_dates(item, start, end):
            row = _scheduled_row(item, due, occ_by_key.get((item.id, due)), look, today)
            if row:
                rows.append(row)

    rows += _debt_rows(ctx, start, end, today)
    rows += _card_rows(cc_balances, start, end, today)
    rows += _visacuota_rows(ctx, start, end, today)
    horizon_end = _add_months(end, 2)
    cobros = collection_rows(ctx, min(start, today - timedelta(days=LATE_WINDOW_DAYS)), horizon_end, today)
    rows += [r for r in cobros if start.isoformat() <= r["date"] <= end.isoformat()]
    rows.sort(key=lambda r: (r["date"], _KIND_ORDER.get(r["kind"], 9), r["concept"].lower()))
    undated += _undated_debt_rows(ctx, today)
    undated.sort(key=lambda r: (_KIND_ORDER.get(r["kind"], 9), r["concept"].lower()))

    is_current = (today.year, today.month) == (year, month)
    overdue: list[dict] = []
    if is_current and start < today:
        before_month = start - timedelta(days=1)
        overdue = [
            r for r in _cash_rows(ctx, items, occ_by_key, look,
                                  today - timedelta(days=LATE_WINDOW_DAYS), before_month, today)
            if not r["done"] and r["action"] and r["kind"] != "recordatorio"
        ]
        for r in overdue:
            r["late"] = True
            r["show_on"] = today.isoformat()

    totals = {"ingreso": 0.0, "abono": 0.0, "pago": 0.0, "cargo_tc": 0.0}
    for row in rows:
        if row["amount_gtq"] is None:
            continue
        if row["kind"] == "cobro":
            totals["abono" if row["credit_card_account_id"] else "ingreso"] += row["amount_gtq"]
        elif row["kind"] in totals:
            totals[row["kind"]] += row["amount_gtq"]

    # Lo atrasado no suma a los totales del mes, pero sí a lo que falta por entrar o salir
    rows = overdue + rows
    pending_in = sum(
        r["amount_gtq"] or 0.0 for r in rows
        if not r["done"] and (r["kind"] == "ingreso" or (r["kind"] == "cobro" and not r["credit_card_account_id"]))
    )
    pending_out = sum(
        r["amount_gtq"] or 0.0 for r in rows
        if r["kind"] in ("pago", "abono") and not r["done"] and r["payment_method"] != "credit_card"
    )
    account_types = {a.name: a.account_type for a in ctx.accounts}
    saldos = build_saldos_map(db, telegram_user_id, ctx)
    cash_now = round(sum(v for k, v in saldos.items() if account_types.get(k) in LIQUID_TYPES), 2)

    # Los abonos planeados que cuentan para una tarjeta incluyen los de meses
    # siguientes hasta su fecha de pago, no solo los del mes en pantalla.
    horizon_rows = [r for r in rows if r["source"] == "scheduled"] + undated + cobros
    for item in items:
        if item.kind != "abono" or item.start_date is None:
            continue
        for due in item_dates(item, end + timedelta(days=1), horizon_end):
            row = _scheduled_row(item, due, occ_by_key.get((item.id, due)), look, today)
            if row:
                horizon_rows.append(row)

    notes = db.scalars(
        select(CalendarNote).where(CalendarNote.user_id == ctx.user.id).order_by(CalendarNote.id)
    ).all()

    # Saldo esperado día a día: todo lo pendiente desde lo atrasado hasta fin del mes en pantalla
    projection = build_projection(
        cash_now,
        _cash_rows(ctx, items, occ_by_key, look, today - timedelta(days=LATE_WINDOW_DAYS), end, today),
        today, end,
    )

    # Cierre: el del mes en pantalla si ya terminó; en la primera semana, el del mes anterior
    close = None
    if end < today:
        close = build_month_close(db, ctx, year, month, today, items, occ_by_key, look)
    elif is_current and today.day <= 7:
        prev = _add_months(start, -1)
        close = build_month_close(db, ctx, prev.year, prev.month, today, items, occ_by_key, look)

    return {
        "year": year,
        "month": month,
        "today": today.isoformat(),
        "items": rows,
        "undated": undated,
        "fixed": list_fixed_payments(db, telegram_user_id, ctx),
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "summary": {
            "is_current_month": is_current,
            "cash_now": cash_now,
            "pending_in": round(pending_in, 2),
            "pending_out": round(pending_out, 2),
            "projected_end": projection["end_balance"] if projection else None,
        },
        "projection": projection,
        "close": close,
        "cards": attach_payment_plans(
            _card_summaries(cc_balances, horizon_rows), ctx, items, occ_by_key, look, cash_now, today,
        ),
        "notes": [{"id": int(n.id), "text": n.text} for n in notes],
    }


# ── Programados: alta, edición, baja ─────────────────────────────────────────

def _resolve_refs(ctx: FinanceContext, kind: str, account_name: str | None, category_name: str | None,
                  payment_method: str | None, credit_card_account_id: int | None) -> dict:
    account_id = None
    if account_name:
        acc = next((a for a in ctx.accounts if a.name.lower() == account_name.strip().lower() and a.is_active), None)
        if not acc or acc.account_type not in LIQUID_TYPES:
            raise ValueError("La cuenta debe ser una cuenta líquida activa.")
        account_id = acc.id

    category_id = None
    if category_name:
        wanted = "ING" if kind == "ingreso" else "EGR"
        cat = next((c for c in ctx.categories
                    if c.name.lower() == category_name.strip().lower() and c.kind == wanted and c.is_active), None)
        if not cat:
            raise ValueError(f"La categoría no existe: {category_name}")
        category_id = cat.id

    cc_id = None
    if credit_card_account_id:
        card = ctx.account_by_id.get(credit_card_account_id)
        if not card or card.account_type != "credit_card" or not card.is_active:
            raise ValueError("Tarjeta de crédito no encontrada o inactiva.")
        cc_id = card.id

    if payment_method not in (None, "cash", "transfer", "credit_card"):
        raise ValueError("Método de pago inválido.")
    return {"account_id": account_id, "category_id": category_id,
            "credit_card_account_id": cc_id, "payment_method": payment_method}


def create_item(db: Session, telegram_user_id: int, data) -> ScheduledItem:
    ctx = FinanceContext(db, telegram_user_id)
    if data.kind not in KINDS:
        raise ValueError("Tipo inválido.")
    if data.recurrence not in RECURRENCES:
        raise ValueError("Repetición inválida.")
    start = _parse_date(data.start_date)
    end = _parse_date(data.end_date)
    if start is None and data.recurrence != "none":
        raise ValueError("Un programado que se repite necesita fecha de inicio.")
    if start and end and end < start:
        raise ValueError("La fecha final no puede ser anterior a la inicial.")

    refs = _resolve_refs(ctx, data.kind, data.account_name, data.category_name,
                         data.payment_method, data.credit_card_account_id)
    item = ScheduledItem(
        user_id=ctx.user.id, kind=data.kind, concept=data.concept.strip(),
        amount=data.amount, currency=data.currency, start_date=start,
        recurrence=data.recurrence, end_date=end, note=(data.note or "").strip() or None,
        is_active=True, created_at=datetime.now(timezone.utc), **refs,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _get_item(db: Session, user_id: int, item_id: int) -> ScheduledItem:
    item = db.scalar(select(ScheduledItem).where(
        ScheduledItem.id == item_id, ScheduledItem.user_id == user_id, ScheduledItem.is_active == True,
    ))
    if not item:
        raise ValueError("Programado no encontrado.")
    return item


def update_item(db: Session, telegram_user_id: int, item_id: int, data) -> ScheduledItem:
    ctx = FinanceContext(db, telegram_user_id)
    item = _get_item(db, ctx.user.id, item_id)
    fields = data.model_fields_set

    if "concept" in fields and data.concept:
        item.concept = data.concept.strip()
    if "amount" in fields:
        item.amount = data.amount
    if "currency" in fields and data.currency:
        item.currency = data.currency
    if "note" in fields:
        item.note = (data.note or "").strip() or None
    if "start_date" in fields:
        item.start_date = _parse_date(data.start_date)
    if "end_date" in fields:
        item.end_date = _parse_date(data.end_date)
    if "recurrence" in fields and data.recurrence:
        if data.recurrence not in RECURRENCES:
            raise ValueError("Repetición inválida.")
        item.recurrence = data.recurrence
    if item.start_date is None and item.recurrence != "none":
        raise ValueError("Un programado que se repite necesita fecha de inicio.")

    if fields & {"account_name", "category_name", "payment_method", "credit_card_account_id"}:
        refs = _resolve_refs(ctx, item.kind, data.account_name, data.category_name,
                             data.payment_method, data.credit_card_account_id)
        if "account_name" in fields:
            item.account_id = refs["account_id"]
        if "category_name" in fields:
            item.category_id = refs["category_id"]
        if "payment_method" in fields:
            item.payment_method = refs["payment_method"]
        if "credit_card_account_id" in fields:
            item.credit_card_account_id = refs["credit_card_account_id"]

    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, telegram_user_id: int, item_id: int) -> None:
    ctx = FinanceContext(db, telegram_user_id)
    item = _get_item(db, ctx.user.id, item_id)
    item.is_active = False
    db.commit()


def _get_or_create_occurrence(db: Session, item: ScheduledItem, due: date | None) -> ScheduledOccurrence:
    stmt = select(ScheduledOccurrence).where(ScheduledOccurrence.item_id == item.id)
    stmt = stmt.where(ScheduledOccurrence.due_date.is_(None) if due is None else ScheduledOccurrence.due_date == due)
    occ = db.scalar(stmt)
    if occ is None:
        occ = ScheduledOccurrence(item_id=item.id, user_id=item.user_id, due_date=due, status="pending")
        db.add(occ)
    return occ


def _check_due(item: ScheduledItem, due: date | None) -> None:
    if due is None:
        if item.start_date is not None:
            raise ValueError("Falta la fecha de la ocurrencia.")
        return
    if due not in item_dates(item, due, due):
        raise ValueError("Esa fecha no corresponde a este programado.")


def set_occurrence(db: Session, telegram_user_id: int, item_id: int, due_date: str | None,
                   *, amount: float | None = None, set_amount: bool = False,
                   skip: bool | None = None) -> None:
    """Anota el monto de una fecha concreta u omite solo esa fecha."""
    ctx = FinanceContext(db, telegram_user_id)
    item = _get_item(db, ctx.user.id, item_id)
    due = _parse_date(due_date)
    _check_due(item, due)
    occ = _get_or_create_occurrence(db, item, due)
    if occ.status == "done":
        raise ValueError("Esa fecha ya está confirmada.")
    if set_amount:
        occ.amount = amount
    if skip is not None:
        occ.status = "skipped" if skip else "pending"
    db.commit()


# ── Confirmar: convierte lo planeado en un registro real ─────────────────────

def _liquid_payment(payment_method: str | None, account_name: str | None) -> tuple[str, str]:
    method = payment_method or ("transfer" if account_name and account_name.strip().lower() != "efectivo" else "cash")
    if method not in ("cash", "transfer"):
        raise ValueError("Elige efectivo o transferencia.")
    name = "Efectivo" if method == "cash" else (account_name or "")
    if not name:
        raise ValueError("Elige la cuenta.")
    return method, name


def confirm_scheduled(db: Session, telegram_user_id: int, data) -> dict:
    ctx = FinanceContext(db, telegram_user_id)
    item = _get_item(db, ctx.user.id, data.item_id)
    due = _parse_date(data.due_date)
    _check_due(item, due)

    stmt = select(ScheduledOccurrence).where(ScheduledOccurrence.item_id == item.id)
    stmt = stmt.where(ScheduledOccurrence.due_date.is_(None) if due is None else ScheduledOccurrence.due_date == due)
    existing = db.scalar(stmt)
    if existing is not None and existing.status == "done" and _Lookups(ctx).record_alive(existing):
        raise ValueError("Esta fecha ya está confirmada.")

    when = data.payment_date
    paid_on = _parse_date(when)
    if paid_on is None:
        raise ValueError("Falta la fecha.")
    if paid_on > today_gt() + timedelta(days=7):
        raise ValueError("La fecha no puede ser más de 7 días en el futuro.")
    record_type = None
    record_id = None
    look = _Lookups(ctx)
    occ_amount = data.amount
    # create_record=False: ya está registrado por otro lado; solo se marca como hecho
    register = bool(getattr(data, "create_record", True)) and item.kind != "recordatorio"

    if register:
        if data.amount is None or data.amount <= 0:
            raise ValueError("Escribe el monto.")
        note = (data.note or "").strip() or item.concept
        refs = _resolve_refs(ctx, item.kind, None, data.category_name, None, None)

    if not register:
        pass
    elif item.kind == "ingreso":
        if not data.category_name:
            raise ValueError("Elige la categoría.")
        method, account_name = _liquid_payment(data.payment_method, data.account_name)
        movement = create_movement(db, MovementCreateRequest(
            telegram_user_id=telegram_user_id, movement_type="ING", movement_date=when,
            amount=data.amount, note=note, category_name=data.category_name,
            payment_method=method, account_name=account_name,
        ))
        record_type, record_id = "movement", movement.id

    elif item.kind in ("pago", "cargo_tc"):
        if not data.category_name:
            raise ValueError("Elige la categoría.")
        use_card = item.kind == "cargo_tc" or data.payment_method == "credit_card"
        if use_card:
            card = ctx.account_by_id.get(data.credit_card_account_id) if data.credit_card_account_id else None
            if not card or card.account_type != "credit_card":
                raise ValueError("Elige la tarjeta.")
            charge_currency = data.charge_currency or item.currency
            amount, amount_foreign = card_charge(card, data.amount, charge_currency, look.rate_default)
            occ_amount = _in_item_currency(item, data.amount, charge_currency, look.rate_for(card.id))
            movement = create_movement(db, MovementCreateRequest(
                telegram_user_id=telegram_user_id, movement_type="EGR", movement_date=when,
                amount=amount, amount_foreign=amount_foreign, note=note,
                category_name=data.category_name, payment_method="credit_card",
                credit_card_account_id=card.id,
            ))
        else:
            method, account_name = _liquid_payment(data.payment_method, data.account_name)
            movement = create_movement(db, MovementCreateRequest(
                telegram_user_id=telegram_user_id, movement_type="EGR", movement_date=when,
                amount=data.amount, note=note, category_name=data.category_name,
                payment_method=method, account_name=account_name,
            ))
        record_type, record_id = "movement", movement.id

    elif item.kind == "abono":
        if not data.credit_card_account_id:
            raise ValueError("Elige la tarjeta.")
        if not data.account_name:
            raise ValueError("Elige la cuenta de donde sale el abono.")
        card = ctx.account_by_id.get(data.credit_card_account_id)
        if not card or card.account_type != "credit_card":
            raise ValueError("Elige la tarjeta.")
        check_card_payment(card, data.usd_paid)
        if data.usd_paid:
            occ_amount = (data.usd_paid if item.currency == "USD"
                          else round(data.usd_paid * look.rate_for(card.id), 2))
        else:
            occ_amount = (round(data.amount / look.rate_for(card.id), 2) if item.currency == "USD"
                          else data.amount)
        payment = create_tc_payment(db, CreditCardPaymentRequest(
            telegram_user_id=telegram_user_id, credit_card_account_id=card.id,
            amount=data.amount, amount_usd=data.usd_paid, payment_date=when,
            account_name=data.account_name, note=note,
        ))
        record_type, record_id = "cc_payment", payment.id

    # Sin tarjeta, el monto se registra en quetzales; en la fecha se guarda en la moneda del programado
    paid_without_card = item.kind == "ingreso" or (item.kind == "pago" and data.payment_method != "credit_card")
    if register and paid_without_card and item.currency == "USD":
        occ_amount = round(data.amount / look.rate_default, 2)

    # Lo confirmado queda como sugerencia para la próxima vez
    item = _get_item(db, ctx.user.id, data.item_id)
    if register:
        if refs["category_id"]:
            item.category_id = refs["category_id"]
        if data.credit_card_account_id:
            item.credit_card_account_id = data.credit_card_account_id
        if data.account_name:
            acc = next((a for a in ctx.accounts if a.name.lower() == data.account_name.strip().lower()), None)
            if acc and acc.account_type in LIQUID_TYPES:
                item.account_id = acc.id
        if data.payment_method:
            item.payment_method = data.payment_method

    if due is None:
        # Un pendiente sin fecha queda fechado el día en que se confirma
        due = _parse_date(when)
        item.start_date = due
        occ = _get_or_create_occurrence(db, item, None)
        occ.due_date = due
    else:
        occ = _get_or_create_occurrence(db, item, due)
    occ.status = "done"
    if occ_amount is not None:
        occ.amount = occ_amount
    occ.record_type = record_type
    occ.record_id = record_id
    occ.done_at = datetime.now(timezone.utc)
    db.commit()
    return {"record_type": record_type, "record_id": int(record_id) if record_id else None}


def card_charge(card, amount: float, currency: str, rate_default: float) -> tuple[float, float | None]:
    """Monto y monto en dólares de un cargo, según en qué moneda lleva su saldo la tarjeta.

    - Tarjeta en quetzales: el cargo se registra en los quetzales que cobró el banco.
    - Tarjeta en dólares: el saldo se lleva en dólares, el cargo va en dólares.
    - Tarjeta mixta: un cargo en dólares va a la porción en dólares (amount_foreign)
      y `amount` queda como referencia en quetzales al tipo de cambio de la tarjeta.
    """
    tc_type = card.tc_type or "GTQ"
    if tc_type == "GTQ":
        if currency != "GTQ":
            raise ValueError(
                f"{card.name} lleva su saldo en quetzales: escribe los quetzales que cobró el banco."
            )
        return round(amount, 2), None
    if tc_type == "USD":
        if currency != "USD":
            raise ValueError(f"{card.name} lleva su saldo en dólares: escribe el cargo en dólares.")
        return round(amount, 2), None
    if currency == "USD":
        rate = float(card.tc_exchange_rate or rate_default)
        return round(amount * rate, 2), round(amount, 2)
    return round(amount, 2), None


def check_card_payment(card, usd_paid: float | None) -> None:
    """Un abono en dólares solo tiene sentido en tarjetas que llevan saldo en dólares."""
    tc_type = card.tc_type or "GTQ"
    if tc_type == "GTQ" and usd_paid:
        raise ValueError(f"{card.name} lleva su saldo en quetzales: el abono va solo en quetzales.")
    if tc_type == "USD" and not usd_paid:
        raise ValueError(f"{card.name} lleva su saldo en dólares: escribe los dólares que abonaste.")


def _in_item_currency(item: ScheduledItem, amount: float, currency: str, rate: float) -> float:
    """Convierte el monto confirmado a la moneda del programado, para mostrarlo igual que el plan."""
    if currency == item.currency:
        return amount
    if item.currency == "USD":
        return round(amount / rate, 2)
    return round(amount * rate, 2)


_MONTHLY_FACTOR = {"monthly": 1.0, "biweekly": 26 / 12, "weekly": 52 / 12}


def list_fixed_payments(db: Session, telegram_user_id: int, ctx: FinanceContext | None = None) -> dict:
    """Suscripciones y pagos fijos: pagos o cargos a tarjeta que se repiten."""
    ctx = resolve_context(db, telegram_user_id, ctx)
    if "fixed" in ctx.memo:
        return ctx.memo["fixed"]
    today = today_gt()
    look = _Lookups(ctx)
    items, _ = _load_scheduled(db, ctx.user.id)

    result = []
    monthly_total = 0.0
    for item in items:
        if item.kind not in ("pago", "cargo_tc") or item.recurrence == "none" or item.start_date is None:
            continue
        if item.end_date and item.end_date < today:
            continue
        upcoming = item_dates(item, today, today + timedelta(days=400))
        amount = float(item.amount) if item.amount is not None else None
        rate = look.rate_for(item.credit_card_account_id)
        amount_gtq = None
        if amount is not None:
            amount_gtq = round(amount * rate, 2) if item.currency == "USD" else round(amount, 2)
            monthly_total += amount_gtq * _MONTHLY_FACTOR.get(item.recurrence, 1.0)
        card = look.accounts.get(item.credit_card_account_id) if item.credit_card_account_id else None
        account = look.accounts.get(item.account_id) if item.account_id else None
        category = look.categories.get(item.category_id) if item.category_id else None
        result.append({
            "item_id": int(item.id),
            "kind": item.kind,
            "concept": item.concept,
            "amount": amount,
            "currency": item.currency,
            "amount_gtq": amount_gtq,
            "recurrence": item.recurrence,
            "start_date": item.start_date.isoformat(),
            "end_date": item.end_date.isoformat() if item.end_date else None,
            "next_date": upcoming[0].isoformat() if upcoming else None,
            "note": item.note,
            "credit_card_account_id": int(card.id) if card else None,
            "credit_card_name": card.name if card else None,
            "card_type": (card.tc_type or "GTQ") if card else None,
            "account_name": account.name if account else None,
            "category_name": category.name if category else None,
        })
    result.sort(key=lambda r: (r["next_date"] or "9999", r["concept"].lower()))
    ctx.memo["fixed"] = {
        "items": result,
        "monthly_gtq": round(monthly_total, 2),
        "yearly_gtq": round(monthly_total * 12, 2),
    }
    return ctx.memo["fixed"]


def undo_reminder(db: Session, telegram_user_id: int, item_id: int, due_date: str | None) -> None:
    """Desmarca algo hecho sin registro. Lo que generó un registro se deshace anulándolo en Historial."""
    ctx = FinanceContext(db, telegram_user_id)
    item = _get_item(db, ctx.user.id, item_id)
    due = _parse_date(due_date)
    occ = db.scalar(select(ScheduledOccurrence).where(
        ScheduledOccurrence.item_id == item.id, ScheduledOccurrence.due_date == due,
    ))
    if not occ or occ.status != "done":
        raise ValueError("Esa fecha no está marcada como hecha.")
    if occ.record_type:
        raise ValueError("Para deshacerlo, anula el movimiento desde Historial.")
    occ.status = "pending"
    occ.done_at = None
    db.commit()


def confirm_debt(db: Session, telegram_user_id: int, data) -> dict:
    method, account_name = _liquid_payment(data.payment_method, data.account_name)
    debt = pay_debt(
        db=db, telegram_user_id=telegram_user_id, debt_id=data.debt_id,
        payment_date=data.payment_date, payment_method=method,
        account_name=account_name, note=(data.note or "").strip() or None,
    )
    return {"record_type": "debt_payment", "record_id": None, "debt_id": int(debt.id)}


# ── Notas ────────────────────────────────────────────────────────────────────

def add_note(db: Session, telegram_user_id: int, text: str) -> CalendarNote:
    ctx = FinanceContext(db, telegram_user_id)
    note = CalendarNote(user_id=ctx.user.id, text=text.strip(), created_at=datetime.now(timezone.utc))
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, telegram_user_id: int, note_id: int) -> None:
    ctx = FinanceContext(db, telegram_user_id)
    note = db.scalar(select(CalendarNote).where(CalendarNote.id == note_id, CalendarNote.user_id == ctx.user.id))
    if not note:
        raise ValueError("Nota no encontrada.")
    db.delete(note)
    db.commit()
