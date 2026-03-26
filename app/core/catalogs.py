from app.config import CUENTAS, INV_CUENTAS_DEFAULT, SHEET_CATEGORIAS
from app.core.helpers import norm_key


def col_clean(values):
    out = []
    for v in values[1:]:
        v = (v or '').strip()
        if v:
            out.append(v)
    return out


def sort_special(items: list[str], first: str | None = None, last: str | None = None) -> list[str]:
    clean = [(x or '').strip() for x in items if (x or '').strip()]
    seen = set()
    unique = []
    for x in clean:
        key = x.lower()
        if key not in seen:
            seen.add(key)
            unique.append(x)

    first_item = next((x for x in unique if first and x.lower() == first.lower()), None)
    last_item = next((x for x in unique if last and x.lower() == last.lower()), None)
    filtered = [x for x in unique if (not first or x.lower() != first.lower()) and (not last or x.lower() != last.lower())]
    filtered = sorted(filtered, key=lambda s: s.lower())

    out = []
    if first_item:
        out.append(first_item)
    out.extend(filtered)
    if last_item:
        out.append(last_item)
    return out


def load_catalogos(sh):
    ws = sh.worksheet(SHEET_CATEGORIAS)
    fuentes_ing = col_clean(ws.col_values(1))
    categ_ing = col_clean(ws.col_values(2))
    metodos = col_clean(ws.col_values(3))
    bancos = col_clean(ws.col_values(4))
    categ_egr = col_clean(ws.col_values(5))
    cuentas = col_clean(ws.col_values(6))
    personas = col_clean(ws.col_values(7))

    return {
        'FUENTES_ING': sort_special(fuentes_ing, last='Otros'),
        'CATEG_ING': sort_special(categ_ing, last='Otros'),
        'METODOS': sort_special(metodos, last='Otros'),
        'BANCOS': sort_special(bancos, last='Otros'),
        'CATEG_EGR': sort_special(categ_egr, last='Otros'),
        'CUENTAS': [x for x in sort_special(cuentas, first='Efectivo') if x.lower() != 'otros'],
        'PERSONAS_PRESTAMO': sort_special(personas, last='Otros'),
    }


def canon_cuenta(raw: str, cuentas_catalogo: list[str]) -> str:
    raw = (raw or '').strip()
    if not raw:
        return ''
    mapping = {norm_key(c): c for c in (cuentas_catalogo or []) if (c or '').strip()}
    return mapping.get(norm_key(raw), raw)


def get_accounts_by_role(cuentas: list[str] | None = None):
    cuentas = cuentas or CUENTAS
    inv_accounts = [c for c in cuentas if norm_key(c) in {norm_key(x) for x in INV_CUENTAS_DEFAULT}]
    patrimonial_accounts = [c for c in cuentas if norm_key(c) in {'ahorro', 'prestamos'}]
    liquid_accounts = [c for c in cuentas if c not in inv_accounts and c not in patrimonial_accounts]
    return liquid_accounts, patrimonial_accounts, inv_accounts
