from app.integrations.gspread_client import get_gspread_client


def open_user_spreadsheet(sheet_id: str):
    gc = get_gspread_client()
    return gc.open_by_key(sheet_id)
