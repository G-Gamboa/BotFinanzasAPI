
"""Base para conectar la lógica real con Google Sheets."""
from app.integrations.gspread_client import build_gspread_client

def get_client():
    return build_gspread_client()
