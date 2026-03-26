
from app.core.validators import validate_nueva_deuda
from app.services.sheets_service import open_user_spreadsheet


def list_deudas(user_id: int, sheet_id: str) -> list[dict]:
    sh = open_user_spreadsheet(sheet_id)
    return [
        {
            "spreadsheet_title": sh.title,
            "message": "Pendiente de conectar lógica real de deudas",
            "user_id": user_id,
        }
    ]


def list_deudas_activas(user_id: int, sheet_id: str) -> list[dict]:
    return list_deudas(user_id, sheet_id)


def create_deuda(payload: dict, sheet_id: str) -> dict:
    validate_nueva_deuda(payload)
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de guardar nueva deuda en Sheets",
        "payload": payload,
    }


def pagar_deuda(payload: dict, sheet_id: str) -> dict:
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de ejecutar pago de deuda en Sheets",
        "payload": payload,
    }
