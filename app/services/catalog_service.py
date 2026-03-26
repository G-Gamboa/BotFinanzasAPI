from app.core.catalogs import load_catalogos
from app.services.sheets_service import open_user_spreadsheet


def get_catalogos_for_user(sheet_id: str) -> dict:
    sh = open_user_spreadsheet(sheet_id)
    return load_catalogos(sh)
