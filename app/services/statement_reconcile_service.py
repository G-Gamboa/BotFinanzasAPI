"""Compara un estado de cuenta del banco con lo registrado en la app para una tarjeta.

Nunca crea ni cambia registros: solo dice qué cuadra, qué está en el banco y no
en la app, qué está en la app y no en el banco, y qué entra en el próximo corte.

Emparejamiento, en este orden:
1. Uno a uno: mismo monto y fecha de consumo cercana.
2. Un registro tuyo contra varias líneas del banco del mismo día que suman lo mismo
   (por ejemplo, un pago por Pronet que el banco parte en monto y comisión).
3. Una línea del banco contra varios registros tuyos que suman lo mismo
   (por ejemplo, una visacuota que registraste partida en dos).
"""
from datetime import date, timedelta
from itertools import combinations

from sqlalchemy.orm import Session

from app.services.finance_context import FinanceContext
from app.services.finance_db_service import _add_months, build_cc_balances

ONE_TO_ONE_DAYS = 4
GROUP_DAYS = 2
PENDING_DAYS = 3        # cargos de los últimos días antes del corte que el banco aún no procesa
LOOKBACK_DAYS = 10      # cargos del ciclo anterior que el banco procesó tarde
MAX_GROUP = 3
MAX_CANDIDATES = 14


def _app_entries(ctx: FinanceContext, card, start: date, end: date) -> list[dict]:
    tc_type = card.tc_type or "GTQ"
    plans = {p.id: p for p in ctx.plans}
    entries = []
    for m in ctx.movements:
        if m.credit_card_account_id != card.id or not (start <= m.movement_date <= end):
            continue
        if m.movement_type != "EGR":
            continue
        if tc_type == "USD":
            currency, amount = "USD", float(m.amount)
        elif tc_type == "MIXTO" and m.amount_foreign is not None:
            currency, amount = "USD", float(m.amount_foreign)
        else:
            currency, amount = "GTQ", float(m.amount)
        plan = plans.get(m.installment_plan_id) if m.installment_plan_id else None
        entries.append({
            "id": f"m:{m.id}", "kind": "cuota" if plan else "cargo", "side": "debit",
            "currency": currency, "date": m.movement_date, "amount": round(amount, 2),
            "label": m.note or (f"Visacuota: {plan.name}" if plan else "Cargo"),
            "plan_id": plan.id if plan else None, "movement_id": m.id,
        })
    for p in ctx.cc_payments:
        if p.credit_card_account_id != card.id or not (start <= p.payment_date <= end):
            continue
        dollars = p.amount_usd is not None
        entries.append({
            "id": f"p:{p.id}", "kind": "abono", "side": "credit",
            "currency": "USD" if dollars else "GTQ", "date": p.payment_date,
            "amount": round(float(p.amount_usd if dollars else p.amount), 2),
            "label": p.note or "Abono a la tarjeta", "plan_id": None,
        })
    for lp in ctx.loan_payments:
        if lp.account_id != card.id or not (start <= lp.payment_date <= end):
            continue
        entries.append({
            "id": f"l:{lp.id}", "kind": "cobro", "side": "credit", "currency": "GTQ",
            "date": lp.payment_date, "amount": round(float(lp.amount), 2),
            "label": f"Cobro: {lp.note}" if lp.note else "Cobro de préstamo", "plan_id": None,
        })
    return entries


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 0.01


def _match(bank: list[dict], app: list[dict]) -> list[dict]:
    groups: list[dict] = []
    used_b: set[int] = set()
    used_a: set[str] = set()

    # 1. Uno a uno, primero los pares con fechas más cercanas
    pairs = []
    for bi, b in enumerate(bank):
        for a in app:
            if a["currency"] != b["currency"] or a["side"] != b["side"] or not _same(a["amount"], b["amount"]):
                continue
            days = abs((a["date"] - b["date"]).days)
            limit = ONE_TO_ONE_DAYS + (3 if b["section"] == "cuotas" else 0)
            if days <= limit:
                pairs.append((days, bi, a["id"]))
    app_by_id = {a["id"]: a for a in app}
    for days, bi, aid in sorted(pairs, key=lambda p: (p[0], p[1])):
        if bi in used_b or aid in used_a:
            continue
        used_b.add(bi)
        used_a.add(aid)
        groups.append({"bank": [bi], "app": [aid], "how": "exacto"})

    # 2. Un registro tuyo = varias líneas del banco
    for a in app:
        if a["id"] in used_a:
            continue
        cands = [bi for bi, b in enumerate(bank)
                 if bi not in used_b and b["currency"] == a["currency"] and b["side"] == a["side"]
                 and abs((b["date"] - a["date"]).days) <= GROUP_DAYS and b["amount"] < a["amount"] + 0.01]
        found = _combo(cands[:MAX_CANDIDATES], lambda i: bank[i]["amount"], a["amount"])
        if found:
            used_a.add(a["id"])
            used_b.update(found)
            groups.append({"bank": list(found), "app": [a["id"]], "how": "partido en el banco"})

    # 3. Una línea del banco = varios registros tuyos
    for bi, b in enumerate(bank):
        if bi in used_b:
            continue
        cands = [a["id"] for a in app
                 if a["id"] not in used_a and a["currency"] == b["currency"] and a["side"] == b["side"]
                 and abs((a["date"] - b["date"]).days) <= GROUP_DAYS + (3 if b["section"] == "cuotas" else 0)
                 and a["amount"] < b["amount"] + 0.01]
        found = _combo(cands[:MAX_CANDIDATES], lambda i: app_by_id[i]["amount"], b["amount"])
        if found:
            used_b.add(bi)
            used_a.update(found)
            groups.append({"bank": [bi], "app": list(found), "how": "partido en la app"})

    return groups, used_b, used_a


def _combo(cands: list, amount_of, target: float):
    for size in range(2, MAX_GROUP + 1):
        for combo in combinations(cands, size):
            if _same(sum(amount_of(c) for c in combo), target):
                return combo
    return None


def _bank_view(line: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in line.items()}


def _app_view(entry: dict) -> dict:
    return {
        "id": entry["id"], "kind": entry["kind"], "side": entry["side"], "currency": entry["currency"],
        "date": entry["date"].isoformat(), "amount": entry["amount"], "label": entry["label"],
    }


def reconcile(db: Session, telegram_user_id: int, card_id: int, statement: dict) -> dict:
    ctx = FinanceContext(db, telegram_user_id)
    card = ctx.account_by_id.get(card_id)
    if card is None or card.account_type != "credit_card":
        raise ValueError("Tarjeta no encontrada.")

    close = date.fromisoformat(statement["close_date"])
    prev_close = _add_months(close, -1)
    warnings = list(statement.get("problems") or [])
    if card.billing_close_day and card.billing_close_day != close.day:
        warnings.append(
            f"El estado de cuenta corta el día {close.day} y {card.name} tiene configurado el día {card.billing_close_day}."
        )
    tc_type = card.tc_type or "GTQ"
    if tc_type == "GTQ" and (statement["contado_usd"] or any(l["currency"] == "USD" for l in statement["lines"])):
        warnings.append(f"El estado de cuenta trae dólares y {card.name} está configurada solo en quetzales.")

    bank = []
    for line in statement["lines"]:
        bank.append({**line, "date": date.fromisoformat(line["date"]), "op_date": date.fromisoformat(line["op_date"])})
    app = _app_entries(ctx, card, prev_close - timedelta(days=LOOKBACK_DAYS), close)

    groups, used_b, used_a = _match(bank, app)
    app_by_id = {a["id"]: a for a in app}

    matched = [{
        "how": g["how"],
        "bank": [_bank_view(bank[i]) for i in g["bank"]],
        "app": [_app_view(app_by_id[i]) for i in g["app"]],
    } for g in groups]
    matched.sort(key=lambda g: (g["bank"][0]["date"], g["bank"][0]["description"]))

    bank_only = [_bank_view(b) for i, b in enumerate(bank) if i not in used_b]
    app_only, pending_next = [], []
    for a in app:
        if a["id"] in used_a or a["date"] <= prev_close:
            continue  # lo de antes del corte anterior ya era del estado de cuenta pasado
        if a["side"] == "debit" and a["date"] >= close - timedelta(days=PENDING_DAYS):
            pending_next.append(_app_view(a))
        else:
            app_only.append(_app_view(a))

    # Contador de visacuotas: la cuota que dice el banco contra la que lleva la app
    plans = {p.id: p for p in ctx.plans}
    installments = []
    for g in groups:
        lines = [bank[i] for i in g["bank"] if bank[i].get("installment")]
        entries = [app_by_id[i] for i in g["app"] if app_by_id[i]["plan_id"]]
        if not lines or not entries:
            continue
        line = lines[0]
        for entry in entries:
            plan = plans.get(entry["plan_id"])
            if not plan:
                continue
            number = sum(
                1 for m in ctx.movements
                if m.installment_plan_id == plan.id and (m.movement_date, m.id) <= (entry["date"], entry["movement_id"])
            )
            installments.append({
                "bank_description": line["description"],
                "bank_number": line["installment"]["number"], "bank_total": line["installment"]["total"],
                "plan_name": plan.name, "app_number": number, "app_total": plan.total_installments,
                "ok": number == line["installment"]["number"] and plan.total_installments == line["installment"]["total"],
            })

    # Contado: solo se compara si el estado de cuenta es del corte vigente de la tarjeta
    balance = next((b for b in build_cc_balances(db, telegram_user_id, ctx) if b["id"] == card.id), None)
    current_cycle = bool(balance and balance.get("last_close_date") == close.isoformat())
    contado = {
        "bank_q": statement["contado_q"], "bank_usd": statement["contado_usd"],
        "app_q": balance.get("statement_computed_q") if current_cycle else None,
        "app_usd": balance.get("statement_computed_usd") if current_cycle else None,
        "override_active": bool(balance and balance.get("statement_override")) if current_cycle else False,
        "current_cycle": current_cycle,
    }

    return {
        "card": {"id": card.id, "name": card.name, "tc_type": tc_type},
        "statement": {
            "close_date": statement["close_date"], "payment_date": statement["payment_date"],
            "card_last4": statement.get("card_last4"), "checks_ok": statement["checks_ok"],
            "lines": len(statement["lines"]),
        },
        "warnings": warnings,
        "contado": contado,
        "matched": matched,
        "bank_only": bank_only,
        "app_only": app_only,
        "pending_next": pending_next,
        "installments": installments,
    }
