
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Bot Finanzas API")
    app_env: str = os.getenv("APP_ENV", "development")
    tz: str = os.getenv("TZ", "America/Guatemala")
    google_service_account_json: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    google_sheets_base_folder: str = os.getenv("GOOGLE_SHEETS_BASE_FOLDER", "")
    allowed_telegram_user_ids: str = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")

    @property
    def allowed_user_ids(self) -> set[int]:
        ids = set()
        for item in self.allowed_telegram_user_ids.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                ids.add(int(item))
            except ValueError:
                pass
        return ids

settings = Settings()
