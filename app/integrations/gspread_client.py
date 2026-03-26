
import json
import gspread
from google.oauth2.service_account import Credentials
from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def build_gspread_client():
    if not settings.google_service_account_json:
        return None
    info = json.loads(settings.google_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)
