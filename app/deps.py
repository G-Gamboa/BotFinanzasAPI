
from functools import lru_cache
from app.integrations.gspread_client import build_gspread_client

@lru_cache(maxsize=1)
def get_gspread_client():
    return build_gspread_client()
