
from pydantic import BaseModel


class NetworthResponse(BaseModel):
    user_id: int
    spreadsheet_id: str
    networth: dict
