from pydantic import BaseModel


class RegistrationStatusResponse(BaseModel):
    registered: bool
    telegram_user_id: int


class InvoiceResponse(BaseModel):
    invoice_link: str
    stars_price: int


class WebhookSetupResponse(BaseModel):
    ok: bool
    description: str | None = None
