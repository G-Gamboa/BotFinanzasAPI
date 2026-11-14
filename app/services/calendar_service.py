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
from app.services.finance_db_service import (
    _add_months,
    build_cc_balances,
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
        pending = max(debt.total_installments - debt.paid_installments, 0)
        current = debt.due_date
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


_KIND_ORDER = {"ingreso": 0, "abono": 1, "pago": 2, "cargo_tc": 3, "tarjeta": 4, "recordatorio": 5}


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
            if row["kind"] != "abono" or row["done"] or row["amount_gtq"] is None:
                continue
            if row["credit_card_account_id"] not in (None, tc["id"]):
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
        })
    return cards


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
    rows.sort(key=lambda r: (r["date"], _KIND_ORDER.get(r["kind"], 9), r["concept"].lower()))
    undated.sort(key=lambda r: (_KIND_ORDER.get(r["kind"], 9), r["concept"].lower()))

    totals = {"ingreso": 0.0, "abono": 0.0, "pago": 0.0, "cargo_tc": 0.0}
    for row in rows:
        if row["kind"] in totals and row["amount_gtq"] is not None:
            totals[row["kind"]] += row["amount_gtq"]

    is_current = (today.year, today.month) == (year, month)
    pending_in = sum(r["amount_gtq"] or 0.0 for r in rows if r["kind"] == "ingreso" and not r["done"])
    pending_out = sum(
        r["amount_gtq"] or 0.0 for r in rows
        if r["kind"] in ("pago", "abono") and not r["done"] and r["payment_method"] != "credit_card"
    )
    account_types = {a.name: a.account_type for a in ctx.accounts}
    saldos = build_saldos_map(db, telegram_user_id, ctx)
    cash_now = round(sum(v for k, v in saldos.items() if account_types.get(k) in LIQUID_TYPES), 2)

    # Los abonos planeados que cuentan para una tarjeta incluyen los de meses
    # siguientes hasta su fecha de pago, no solo los del mes en pantalla.
    horizon_rows = [r for r in rows if r["source"] == "scheduled"] + undated
    horizon_end = _add_months(end, 2)
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

    return {
        "year": year,
        "month": month,
        "today": today.isoformat(),
        "items": rows,
        "undated": undated,
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "summary": {
            "is_current_month": is_current,
            "cash_now": cash_now,
            "pending_in": round(pending_in, 2),
            "pending_out": round(pending_out, 2),
            "projected_end": round(cash_now + pending_in - pending_out, 2) if is_current else None,
        },
        "cards": _card_summaries(cc_balances, horizon_rows),
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

    if item.kind != "recordatorio":
        if data.amount is None or data.amount <= 0:
            raise ValueError("Escribe el monto.")
        note = (data.note or "").strip() or item.concept
        refs = _resolve_refs(ctx, item.kind, None, data.category_name, None, None)

    if item.kind == "ingreso":
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
            tc_type = card.tc_type or "GTQ"
            amount, amount_foreign = data.amount, None
            if item.currency == "USD":
                if tc_type == "MIXTO":
                    amount_foreign = data.amount
                    amount = round(data.amount * float(card.tc_exchange_rate or 8.0), 2)
                elif tc_type != "USD":
                    raise ValueError("Esa tarjeta no acepta cargos en dólares.")
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
        amount_usd = None
        amount_gtq = data.amount
        if item.currency == "USD":
            amount_usd = data.amount
            if data.amount_gtq is None or data.amount_gtq <= 0:
                raise ValueError("Escribe cuántos quetzales salieron de tu cuenta.")
            amount_gtq = data.amount_gtq
        payment = create_tc_payment(db, CreditCardPaymentRequest(
            telegram_user_id=telegram_user_id, credit_card_account_id=data.credit_card_account_id,
            amount=amount_gtq, amount_usd=amount_usd, payment_date=when,
            account_name=data.account_name, note=note,
        ))
        record_type, record_id = "cc_payment", payment.id

    # Lo confirmado queda como sugerencia para la próxima vez
    item = _get_item(db, ctx.user.id, data.item_id)
    if item.kind != "recordatorio":
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
    if data.amount is not None:
        occ.amount = data.amount
    occ.record_type = record_type
    occ.record_id = record_id
    occ.done_at = datetime.now(timezone.utc)
    db.commit()
    return {"record_type": record_type, "record_id": int(record_id) if record_id else None}


def undo_reminder(db: Session, telegram_user_id: int, item_id: int, due_date: str | None) -> None:
    """Desmarca un recordatorio. Lo que generó un registro se deshace anulándolo en Historial."""
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
