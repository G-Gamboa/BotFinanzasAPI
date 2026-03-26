
import json

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_settings


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def build_gspread_client() -> gspread.Client:
    settings = get_settings()
    if not settings.google_credentials_json:
        raise ValueError("Falta GOOGLE_CREDENTIALS_JSON")

    info = json.loads(settings.google_credentials_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)
