from app.config import BOLSA_NORMAL, SHEET_EGRESOS, SHEET_INGRESOS, SHEET_MOVIMIENTOS
from app.core.validators import validate_flow_data
from app.services.sheets_service import open_user_spreadsheet


def create_movimiento(data: dict, sheet_id: str) -> dict:
    validate_flow_data(data)
    sh = open_user_spreadsheet(sheet_id)

    if data['tipo'] == 'ING':
        sh.worksheet(SHEET_INGRESOS).append_row([
            data['fecha'],
            data.get('fuente', ''),
            data.get('categoria', ''),
            data['monto'],
            data.get('metodo', ''),
            data.get('banco', ''),
            data.get('nota', ''),
        ], value_input_option='USER_ENTERED')
    elif data['tipo'] == 'EGR':
        sh.worksheet(SHEET_EGRESOS).append_row([
            data['fecha'],
            data.get('categoria', ''),
            data['monto'],
            data.get('metodo', ''),
            data.get('banco', ''),
            data.get('nota', ''),
        ], value_input_option='USER_ENTERED')
    else:
        sh.worksheet(SHEET_MOVIMIENTOS).append_row([
            data['fecha'],
            data.get('bolsa_remitente', BOLSA_NORMAL),
            data.get('remitente', ''),
            data.get('bolsa_destino', BOLSA_NORMAL),
            data.get('destino', ''),
            data.get('persona_prestamo', ''),
            data['monto'],
            data.get('monto_destino', 0),
            data.get('nota', ''),
        ], value_input_option='USER_ENTERED')

    return {'saved': True, 'tipo': data['tipo']}
