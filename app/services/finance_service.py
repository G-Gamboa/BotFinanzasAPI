
from app.services.sheets_service import open_user_spreadsheet


def get_resumen(user_id: int, sheet_id: str) -> dict:
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de conectar lógica real de resumen",
        "user_id": user_id,
    }


def get_networth(user_id: int, sheet_id: str) -> dict:
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de conectar lógica real de networth",
        "user_id": user_id,
    }


def get_saldos(user_id: int, sheet_id: str) -> dict:
    sh = open_user_spreadsheet(sheet_id)
    return {
        "spreadsheet_title": sh.title,
        "message": "Pendiente de conectar lógica real de saldos",
        "user_id": user_id,
    }
