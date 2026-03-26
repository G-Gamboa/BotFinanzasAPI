from datetime import datetime

from app.config import BANCOS, SHEET_DEUDAS, SHEET_EGRESOS, get_settings
from app.core.validators import validate_flow_data
from app.services.finance_service import get_deudas
from app.services.sheets_service import open_user_spreadsheet

BANK_SET = {x.strip().lower() for x in BANCOS}


def create_deuda(data: dict, sheet_id: str) -> dict:
    payload = dict(data)
    payload['tipo'] = 'DEUDA'
    validate_flow_data(payload)

    open_user_spreadsheet(sheet_id).worksheet(SHEET_DEUDAS).append_row([
        payload['deuda_nombre'],
        payload['deuda_acreedor'],
        payload['deuda_fecha_pago'],
        payload['deuda_cuota'],
        payload['deuda_meses'],
        payload.get('deuda_pagados', 0),
        payload['deuda_pendientes'],
        payload['deuda_saldo'],
        payload['deuda_estado'],
    ], value_input_option='USER_ENTERED')

    return {'saved': True, 'deuda_nombre': payload['deuda_nombre'], 'deuda_estado': payload['deuda_estado']}


def _sumar_un_pago_deuda(sh, row_num: int):
    ws = sh.worksheet(SHEET_DEUDAS)
    current = int(float(ws.cell(row_num, 6).value or '0'))
    ws.update_cell(row_num, 6, current + 1)


def _registrar_egreso_deuda(sh, fecha: str, cuenta_pago: str, monto: float, nombre_deuda: str):
    if cuenta_pago.strip().lower() in BANK_SET:
        metodo = 'Transferencia'
        banco = cuenta_pago
    else:
        metodo = cuenta_pago
        banco = ''

    sh.worksheet(SHEET_EGRESOS).append_row([
        fecha,
        'Deuda',
        monto,
        metodo,
        banco,
        f'Pago de deuda: {nombre_deuda}',
    ], value_input_option='USER_ENTERED')


def pagar_deuda(deuda_row: int, cuenta_pago: str, sheet_id: str) -> dict:
    settings = get_settings()
    sh = open_user_spreadsheet(sheet_id)
    fecha = datetime.now(settings.tz).strftime('%Y-%m-%d')

    deuda_actual = next((d for d in get_deudas(sheet_id) if d['row'] == deuda_row), None)
    if not deuda_actual:
        raise ValueError('No encontré la deuda seleccionada.')
    if deuda_actual['estado'].lower() != 'activa' or deuda_actual['pendientes'] <= 0:
        raise ValueError('Esa deuda ya está pagada.')

    _sumar_un_pago_deuda(sh, deuda_row)
    _registrar_egreso_deuda(sh, fecha, cuenta_pago, deuda_actual['cuota'], deuda_actual['nombre'])

    return {
        'saved': True,
        'deuda_row': deuda_row,
        'deuda_nombre': deuda_actual['nombre'],
        'cuenta_pago': cuenta_pago,
        'cuota': deuda_actual['cuota'],
    }
