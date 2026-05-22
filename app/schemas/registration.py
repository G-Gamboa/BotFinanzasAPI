from pydantic import BaseModel


class RegistrationStatusResponse(BaseModel):
    registered: bool
    telegram_user_id: int
    days_remaining: int | None = None   # None = sin vencimiento (legacy)
    expires_at: str | None = None       # "DD/MM/YYYY" o None


class InvoiceResponse(BaseModel):
    invoice_link: str
    stars_price: int


class WebhookSetupResponse(BaseModel):
    ok: bool
    description: str | None = None
