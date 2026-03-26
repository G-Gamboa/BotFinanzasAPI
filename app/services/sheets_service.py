
from gspread import Spreadsheet

from app.integrations.gspread_client import build_gspread_client


def open_user_spreadsheet(sheet_id: str) -> Spreadsheet:
    client = build_gspread_client()
    return client.open_by_key(sheet_id)
