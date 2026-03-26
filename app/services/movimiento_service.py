
from app.core.validators import validate_movimiento
from app.services.sheets_service import open_user_spreadsheet


def create_movimiento(payload: dict, sheet_id: str) -> dict:
    validate_movimiento(payload)
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de guardar movimiento en Sheets",
        "payload": payload,
    }
