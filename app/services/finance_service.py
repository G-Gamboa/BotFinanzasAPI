from collections import defaultdict
from datetime import datetime, timedelta

from app.config import (
    AHORRO_CUENTA,
    BOLSA_NORMAL,
    INV_CUENTAS_DEFAULT,
    PRESTAMOS_CUENTA,
    SHEET_CATEGORIAS,
    SHEET_DEUDAS,
    SHEET_EGRESOS,
    SHEET_INGRESOS,
    SHEET_MOVIMIENTOS,
    get_settings,
)
from app.core.catalogs import canon_cuenta, col_clean
from app.core.helpers import month_range, norm_key, parse_fecha, pick, to_float, week_range
from app.core.sheet_utils import build_header_map, cell, row_cell
from app.services.sheets_service import open_user_spreadsheet

BANK_TRANSFER_KEYS = {'transferencia'}


def _build_resumen(sheet_id: str, periodo: str) -> dict:
    settings = get_settings()
    sh = open_user_spreadsheet(sheet_id)
    ws_ing = sh.worksheet(SHEET_INGRESOS)
    ws_egr = sh.worksheet(SHEET_EGRESOS)

    today = datetime.now(settings.tz).date()
    start, end = month_range(today) if periodo == 'mes' else week_range(today)

    total_ing = 0.0
    total_egr = 0.0
    gastos_por_categoria = defaultdict(float)

    for row in ws_ing.get_all_records():
        fecha = parse_fecha(pick(row, 'FECHA', 'Fecha'))
        if fecha and start <= fecha < end:
            total_ing += to_float(pick(row, 'MONTO', 'Monto'))

    for row in ws_egr.get_all_records():
        fecha = parse_fecha(pick(row, 'FECHA', 'Fecha'))
        if fecha and start <= fecha < end:
            monto = to_float(pick(row, 'MONTO', 'Monto'))
            categoria = str(pick(row, 'CATEGORÍA', 'CATEGORIA', 'Categoría', 'Categoria') or '').strip() or 'Otros'
            total_egr += monto
            gastos_por_categoria[categoria] += monto

    top = sorted(gastos_por_categoria.items(), key=lambda x: x[1], reverse=True)[:6]
    return {
        'periodo': periodo,
        'fecha_inicio': start.isoformat(),
        'fecha_fin': (end - timedelta(days=1)).isoformat(),
        'ingresos': round(total_ing, 2),
        'egresos': round(total_egr, 2),
        'balance': round(total_ing - total_egr, 2),
        'gastos_por_categoria': {k: round(v, 2) for k, v in sorted(gastos_por_categoria.items())},
        'top_gastos': [{'categoria': k, 'monto': round(v, 2)} for k, v in top],
    }


def get_resumen_mes(sheet_id: str) -> dict:
    return _build_resumen(sheet_id, 'mes')


def get_resumen_semana(sheet_id: str) -> dict:
    return _build_resumen(sheet_id, 'semana')


def get_saldos(sheet_id: str) -> dict[str, float]:
    inv_cuentas = {norm_key(x) for x in INV_CUENTAS_DEFAULT}
    ahorro_n = norm_key(AHORRO_CUENTA)
    prestamos_n = norm_key(PRESTAMOS_CUENTA)

    sh = open_user_spreadsheet(sheet_id)
    ws_ing = sh.worksheet(SHEET_INGRESOS)
    ws_egr = sh.worksheet(SHEET_EGRESOS)
    ws_mov = sh.worksheet(SHEET_MOVIMIENTOS)
    ws_cat = sh.worksheet(SHEET_CATEGORIAS)

    cuentas_catalogo = col_clean(ws_cat.col_values(6))

    def is_excluded_account(acc: str) -> bool:
        key = norm_key(acc)
        return key in inv_cuentas or key == ahorro_n or key == prestamos_n

    saldos = defaultdict(float)

    ing_vals = ws_ing.get('A1:G')
    ing_h = build_header_map(ing_vals)
    for row in ing_vals[1:]:
        if not any((c or '').strip() for c in row):
            continue
        categoria = str(cell(row, ing_h, 'CATEGORÍA', 'CATEGORIA', 'Categoria') or '').strip().lower()
        if categoria in {'inversiones', 'prestamos', 'préstamos'}:
            continue
        metodo = str(cell(row, ing_h, 'MÉTODO', 'METODO', 'Metodo') or '').strip()
        banco = str(cell(row, ing_h, 'BANCO', 'Banco') or '').strip()
        cuenta = banco if norm_key(metodo) in BANK_TRANSFER_KEYS else metodo
        cuenta = canon_cuenta(cuenta, cuentas_catalogo)
        if cuenta and not is_excluded_account(cuenta):
            saldos[cuenta] += to_float(cell(row, ing_h, 'MONTO', 'Monto'))

    egr_vals = ws_egr.get('A1:F')
    egr_h = build_header_map(egr_vals)
    for row in egr_vals[1:]:
        if not any((c or '').strip() for c in row):
            continue
        metodo = str(cell(row, egr_h, 'MÉTODO', 'METODO', 'Metodo') or '').strip()
        banco = str(cell(row, egr_h, 'BANCO', 'Banco') or '').strip()
        cuenta = banco if norm_key(metodo) in BANK_TRANSFER_KEYS else metodo
        cuenta = canon_cuenta(cuenta, cuentas_catalogo)
        if cuenta and not is_excluded_account(cuenta):
            saldos[cuenta] -= to_float(cell(row, egr_h, 'MONTO', 'Monto'))

    mov_vals = ws_mov.get('A1:I')
    mov_h = build_header_map(mov_vals)
    for row in mov_vals[1:]:
        if not any((c or '').strip() for c in row):
            continue
        bolsa_rem = str(cell(row, mov_h, 'BOLSA_REMITENTE') or '').strip() or BOLSA_NORMAL
        remitente = canon_cuenta(str(cell(row, mov_h, 'REMITENTE') or '').strip(), cuentas_catalogo)
        bolsa_des = str(cell(row, mov_h, 'BOLSA_DESTINO') or '').strip() or BOLSA_NORMAL
        destino = canon_cuenta(str(cell(row, mov_h, 'DESTINO') or '').strip(), cuentas_catalogo)
        out_amt = to_float(cell(row, mov_h, 'MONTO', 'Monto'))
        md = to_float(cell(row, mov_h, 'MONTO_DESTINO', 'Monto_destino'))
        in_amt = md if abs(md) > 1e-9 else out_amt

        if norm_key(bolsa_rem) == norm_key(BOLSA_NORMAL) and remitente and not is_excluded_account(remitente):
            saldos[remitente] -= out_amt
        if norm_key(bolsa_des) == norm_key(BOLSA_NORMAL) and destino and not is_excluded_account(destino):
            saldos[destino] += in_amt

    for cuenta in cuentas_catalogo:
        canon = canon_cuenta(cuenta, cuentas_catalogo)
        if canon and not is_excluded_account(canon):
            saldos[canon] += 0.0

    return {k: round(v, 2) for k, v in sorted(saldos.items())}


def get_networth(sheet_id: str) -> dict:
    settings = get_settings()
    inv_set = {norm_key(x) for x in INV_CUENTAS_DEFAULT}
    ahorro_n = norm_key(AHORRO_CUENTA)
    prestamos_n = norm_key(PRESTAMOS_CUENTA)

    sh = open_user_spreadsheet(sheet_id)
    ws_ing = sh.worksheet(SHEET_INGRESOS)
    ws_mov = sh.worksheet(SHEET_MOVIMIENTOS)
    ws_cat = sh.worksheet(SHEET_CATEGORIAS)

    cuentas_catalogo = col_clean(ws_cat.col_values(6))
    liquido_map = get_saldos(sheet_id)

    ahorro_map = defaultdict(float)
    prestamos_map = defaultdict(float)
    inv_map = defaultdict(float)

    ing_vals = ws_ing.get('A1:G')
    ing_h = build_header_map(ing_vals)
    for row in ing_vals[1:]:
        if not any((c or '').strip() for c in row):
            continue

        categoria = str(cell(row, ing_h, 'CATEGORÍA', 'CATEGORIA', 'Categoria') or '').strip().lower()
        monto = to_float(cell(row, ing_h, 'MONTO', 'Monto'))
        metodo = canon_cuenta(str(cell(row, ing_h, 'MÉTODO', 'METODO', 'Metodo') or '').strip(), cuentas_catalogo)

        if categoria == 'inversiones' and norm_key(metodo) in inv_set:
            inv_map[metodo] += monto
        elif categoria in {'prestamos', 'préstamos'}:
            prestamos_map['General'] += monto

    mov_vals = ws_mov.get('A1:I')
    mov_h = build_header_map(mov_vals)
    for row in mov_vals[1:]:
        if not any((c or '').strip() for c in row):
            continue
        bolsa_rem = str(cell(row, mov_h, 'BOLSA_REMITENTE') or '').strip() or BOLSA_NORMAL
        remitente = canon_cuenta(str(cell(row, mov_h, 'REMITENTE') or '').strip(), cuentas_catalogo)
        bolsa_des = str(cell(row, mov_h, 'BOLSA_DESTINO') or '').strip() or BOLSA_NORMAL
        destino = canon_cuenta(str(cell(row, mov_h, 'DESTINO') or '').strip(), cuentas_catalogo)
        persona = str(cell(row, mov_h, 'PERSONA_PRESTAMO', 'PERSONAS_PRESTAMO', 'PERSONA PRESTAMO') or '').strip() or 'General'
        monto = to_float(cell(row, mov_h, 'MONTO', 'Monto'))
        monto_dest = to_float(cell(row, mov_h, 'MONTO_DESTINO', 'Monto_destino'))
        entrada = monto_dest if abs(monto_dest) > 1e-9 else monto

        br = norm_key(bolsa_rem)
        bd = norm_key(bolsa_des)

        if bd == ahorro_n:
            ahorro_map[destino or 'Sin cuenta'] += entrada
        if br == ahorro_n:
            ahorro_map[remitente or 'Sin cuenta'] -= monto

        if bd == prestamos_n:
            prestamos_map[persona] += entrada
        if br == prestamos_n:
            prestamos_map[persona] -= monto

        if bd == norm_key('Inversion'):
            inv_map[destino or 'Sin cuenta'] += entrada
        if br == norm_key('Inversion'):
            inv_map[remitente or 'Sin cuenta'] -= monto

    total_liquido = round(sum(liquido_map.values()), 2)
    total_ahorro = round(sum(ahorro_map.values()), 2)
    total_prestamos = round(sum(prestamos_map.values()), 2)
    total_inv_usd = round(sum(inv_map.values()), 2)
    total_inv_q = round(total_inv_usd * settings.usd_to_gtq, 2)
    networth_q = round(total_liquido + total_ahorro + total_prestamos + total_inv_q, 2)

    return {
        'liquido_q': {k: round(v, 2) for k, v in sorted(liquido_map.items())},
        'ahorro_q': {k: round(v, 2) for k, v in sorted(ahorro_map.items())},
        'prestamos_q': {k: round(v, 2) for k, v in sorted(prestamos_map.items())},
        'inversiones_usd': {k: round(v, 2) for k, v in sorted(inv_map.items())},
        'total_liquido_q': total_liquido,
        'total_ahorro_q': total_ahorro,
        'total_prestamos_q': total_prestamos,
        'total_inversiones_usd': total_inv_usd,
        'total_inversiones_q': total_inv_q,
        'networth_q': networth_q,
        'usd_to_gtq': settings.usd_to_gtq,
    }


def get_deudas(sheet_id: str) -> list[dict]:
    sh = open_user_spreadsheet(sheet_id)
    ws = sh.worksheet(SHEET_DEUDAS)

    vals = ws.get('A1:I')
    hmap = build_header_map(vals)
    items = []

    for row_num, row in enumerate(vals[1:], start=2):
        if not any((c or '').strip() for c in row):
            continue

        nombre = str(row_cell(row, hmap, 'NOMBRE') or '').strip()
        acreedor = str(row_cell(row, hmap, 'A QUIÉN LE DEBO', 'A QUIEN LE DEBO') or '').strip()
        fecha_pago = str(row_cell(row, hmap, 'FECHA DE PAGO') or '').strip()
        cuota = to_float(row_cell(row, hmap, 'CUOTA'))
        meses = int(to_float(row_cell(row, hmap, 'MESES')))
        pagados = int(to_float(row_cell(row, hmap, 'PAGADOS')))
        pendientes = int(to_float(row_cell(row, hmap, 'PENDIENTES')))
        saldo = to_float(row_cell(row, hmap, 'SALDO'))
        estado = str(row_cell(row, hmap, 'ESTADO') or '').strip()

        if pendientes <= 0 and meses > pagados:
            pendientes = max(meses - pagados, 0)
        if saldo <= 0 and cuota > 0 and pendientes > 0:
            saldo = cuota * pendientes
        if not estado:
            estado = 'Pagada' if pendientes <= 0 else 'Activa'

        items.append({
            'row': row_num,
            'nombre': nombre,
            'acreedor': acreedor,
            'fecha_pago': fecha_pago,
            'cuota': round(cuota, 2),
            'meses': meses,
            'pagados': pagados,
            'pendientes': pendientes,
            'saldo': round(saldo, 2),
            'estado': estado,
        })

    return items


def get_total_deudas(sheet_id: str) -> float:
    return round(sum(d['saldo'] for d in get_deudas(sheet_id) if d['estado'].lower() == 'activa'), 2)


def get_neto(sheet_id: str) -> dict:
    networth = get_networth(sheet_id)
    total_deudas = get_total_deudas(sheet_id)
    return {
        'networth_q': networth['networth_q'],
        'deudas_activas_q': total_deudas,
        'neto_q': round(networth['networth_q'] - total_deudas, 2),
    }
