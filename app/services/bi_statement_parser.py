"""Lectura del estado de cuenta de tarjeta de crédito de Banco Industrial (PDF).

Se lee con reglas fijas, sin servicios externos: el PDF de BI trae texto
seleccionable y siempre el mismo formato. Nada se guarda; el archivo se lee en
memoria y se descarta.

Cada línea se toma en el orden de la página (para saber su sección y moneda) y
la columna débito/crédito se decide por la posición del monto. Al final se
valida contra los totales que trae el propio estado de cuenta: si no cuadran,
el resultado lo dice en vez de inventar.
"""
import io
import re
from collections import defaultdict
from datetime import date

AMOUNT = r"-?[\d,]*\.\d{2}"
TX_ROW = re.compile(rf"^(\d{{2}}/\d{{2}}/\d{{2}}) (\d{{2}}/\d{{2}}/\d{{2}}) (.+?) ({AMOUNT})$")
TOTAL_ROW = re.compile(rf"^TOTAL (QUETZALES|DOLARES) ({AMOUNT}) ({AMOUNT})$")
INSTALLMENT = re.compile(r"^(.*?)\s+\d{2} \((\d{2})/(\d{2})\)$")
LAYOUT_TX = re.compile(rf"(\d{{2}}/\d{{2}}/\d{{2}})\s+(\d{{2}}/\d{{2}}/\d{{2}})\s+(.+?)\s{{2,}}({AMOUNT})")
CREDIT_WORDS = re.compile(r"PAGO|CREDITO|CRÉDITO|DEVOLUC|REVERS|ABONO|BONIFIC|REEMBOLSO", re.I)

SECTIONS = {
    "CUOTAS": "cuotas",
    "OTROS CARGOS": "otros_cargos",
    "PAGOS REALIZADOS": "pagos",
    "BALANCE DE INTERESES": "intereses",
}
SUMMARY = {
    "anterior": r"Saldo anterior:",
    "compras": r"Compras y retiros:",
    "cuotas": r"Cuotas Extraf/Cuotas:",
    "intereses": r"\(\+\) Intereses:",
    "moratorios": r"Cargos moratorios:",
    "otros_cargos": r"\(\+\) Otros cargos:",
    "pagos": r"\(-\) Pagos:",
    "otros_creditos": r"Otros cr.ditos:",
    "contado": r"Pago de contado\):",
}


class StatementError(ValueError):
    pass


def _num(text: str) -> float:
    return round(float(text.replace(",", "")), 2)


def _date(text: str) -> date:
    d, m, y = text.split("/")
    return date(2000 + int(y), int(m), int(d))


def _visitor_rows(page) -> list[str]:
    """Texto de la página agrupado por renglón, de arriba hacia abajo."""
    parts: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, font, size):
        if text and text.strip():
            parts.append((tm[5] * cm[3] + cm[5], tm[4] * cm[0] + cm[4], text))

    page.extract_text(visitor_text=visit)
    rows: dict[int, list] = defaultdict(list)
    for y, x, text in parts:
        rows[round(y / 3)].append((x, text))
    out = []
    for key in sorted(rows, reverse=True):
        for _, text in sorted(rows[key]):
            for line in text.splitlines():
                line = " ".join(line.split())
                if line:
                    out.append(line)
    return out


def _column_sides(layout_texts: list[str]) -> dict:
    """Débito o crédito de cada línea según dónde termina el monto en el texto con columnas."""
    found = []
    for text in layout_texts:
        for line in text.splitlines():
            for m in LAYOUT_TX.finditer(line):
                desc = " ".join(m.group(3).split())
                found.append(((m.group(1), m.group(2), desc, _num(m.group(4))), m.end(4) - m.start(1)))
    ends = sorted({end for _, end in found})
    sides: dict = {}
    if len(ends) < 2:
        return sides
    # La brecha más grande entre posiciones separa la columna de débitos de la de créditos
    gaps = [(ends[i + 1] - ends[i], i) for i in range(len(ends) - 1)]
    gap, i = max(gaps)
    if gap < 8:
        return sides
    threshold = (ends[i] + ends[i + 1]) / 2
    for key, end in found:
        sides.setdefault(key, []).append("credit" if end > threshold else "debit")
    return sides


def parse_bi_statement(pdf_bytes: bytes) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = list(reader.pages)
    except Exception as exc:  # PDF dañado o protegido
        raise StatementError("No pude abrir el PDF. Sube el estado de cuenta tal como lo envía el banco.") from exc
    if not pages:
        raise StatementError("El PDF no tiene páginas.")

    layout = [p.extract_text(extraction_mode="layout") or "" for p in pages]
    head = layout[0]
    if "Pago de contado" not in head or "Fecha de corte" not in (pages[0].extract_text() or ""):
        raise StatementError("No parece un estado de cuenta de tarjeta de Banco Industrial.")

    # ── Resumen de la primera página ──
    summary = {}
    for key, label in SUMMARY.items():
        m = re.search(label + rf"\s+({AMOUNT})\s+({AMOUNT})", head)
        if m:
            summary[key] = {"q": _num(m.group(1)), "usd": _num(m.group(2))}
    if "contado" not in summary:
        raise StatementError("No encontré el pago de contado en el estado de cuenta.")
    dates = re.findall(r"\b(\d{2})\s+(\d{2})\s+(20\d{2})\b", head)
    if len(dates) < 2:
        raise StatementError("No encontré las fechas de corte y de pago.")
    close_date = date(int(dates[0][2]), int(dates[0][1]), int(dates[0][0]))
    payment_date = date(int(dates[1][2]), int(dates[1][1]), int(dates[1][0]))
    last4 = re.search(r"XXXX XXXX XXXX (\d{4})", head)

    # ── Líneas de movimientos ──
    sides = _column_sides(layout)
    used_side: dict = defaultdict(int)
    lines: list[dict] = []
    totals: dict = {}
    section = "compras"
    currency = "GTQ"
    for page in pages[1:] if len(pages) > 1 else pages:
        for row in _visitor_rows(page):
            upper = row.upper()
            if upper in SECTIONS:
                section = SECTIONS[upper]
                continue
            if upper.startswith("MOVIMIENTOS EN QUETZALES"):
                currency = "GTQ"
                continue
            if upper.startswith("MOVIMIENTOS EN DOLARES"):
                currency = "USD"
                continue
            t = TOTAL_ROW.match(row)
            if t:
                totals[(section, "GTQ" if t.group(1) == "QUETZALES" else "USD")] = {
                    "debit": _num(t.group(2)), "credit": _num(t.group(3)),
                }
                continue
            m = TX_ROW.match(row)
            if not m or section in ("pagos", "intereses"):
                continue
            desc, amount = m.group(3).strip(), _num(m.group(4))
            key = (m.group(1), m.group(2), desc, amount)
            options = sides.get(key)
            if options:
                side = options[min(used_side[key], len(options) - 1)]
                used_side[key] += 1
            else:
                side = "credit" if CREDIT_WORDS.search(desc) else "debit"
            installment = None
            inst = INSTALLMENT.match(desc) if section == "cuotas" else None
            if inst:
                installment = {"number": int(inst.group(2)), "total": int(inst.group(3))}
                desc = inst.group(1).strip()
            lines.append({
                "section": section, "currency": currency, "side": side,
                "op_date": _date(m.group(1)).isoformat(), "date": _date(m.group(2)).isoformat(),
                "description": desc, "amount": amount, "installment": installment,
            })

    # ── Validaciones contra los totales del propio estado de cuenta ──
    problems = []
    for (sec, cur), tot in totals.items():
        if sec in ("pagos", "intereses"):
            continue
        got_d = round(sum(l["amount"] for l in lines if l["section"] == sec and l["currency"] == cur and l["side"] == "debit"), 2)
        got_c = round(sum(l["amount"] for l in lines if l["section"] == sec and l["currency"] == cur and l["side"] == "credit"), 2)
        if abs(got_d - tot["debit"]) > 0.01 or abs(got_c - tot["credit"]) > 0.01:
            problems.append(f"Las líneas de {sec} en {cur} no suman lo que dice el banco.")
    s = summary
    for cur in ("q", "usd"):
        expected = round(
            s.get("anterior", {}).get(cur, 0) + s.get("compras", {}).get(cur, 0) + s.get("cuotas", {}).get(cur, 0)
            + s.get("intereses", {}).get(cur, 0) + s.get("moratorios", {}).get(cur, 0)
            + s.get("otros_cargos", {}).get(cur, 0) - s.get("pagos", {}).get(cur, 0)
            - s.get("otros_creditos", {}).get(cur, 0), 2)
        if abs(expected - s["contado"][cur]) > 0.01:
            problems.append("El resumen del estado de cuenta no cuadra con su pago de contado.")
            break

    return {
        "bank": "BI",
        "card_last4": last4.group(1) if last4 else None,
        "close_date": close_date.isoformat(),
        "payment_date": payment_date.isoformat(),
        "contado_q": s["contado"]["q"],
        "contado_usd": s["contado"]["usd"],
        "summary": summary,
        "lines": lines,
        "checks_ok": not problems,
        "problems": problems,
    }
