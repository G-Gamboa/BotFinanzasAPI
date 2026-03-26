from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_settings


@lru_cache
def get_gspread_client():
    settings = get_settings()
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(settings.google_credentials, scopes=scopes)
    return gspread.authorize(creds)
