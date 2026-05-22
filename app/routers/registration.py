"""Registration router — Telegram Stars payment flow + webhook handler."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.registration import InvoiceResponse, RegistrationStatusResponse, WebhookSetupResponse
from app.security.telegram_auth import get_current_telegram_auth
from app.services.telegram_bot import (
    answer_pre_checkout_query,
    create_invoice_link,
    delete_webhook,
    send_message,
    set_my_commands,
    set_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["registration"])


# ──────────────────────────────────────────────────────────────
# GET  /registro/estado
# Checks whether the authenticated TG user is registered.
# Works for any TG user (not just those in the DB).
# ──────────────────────────────────────────────────────────────
@router.get("/registro/estado", response_model=RegistrationStatusResponse)
def get_registration_status(
    auth=Depends(get_current_telegram_auth),
    db: Session = Depends(get_db),
):
    telegram_user_id: int = auth["user"]["id"]
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    registered = user is not None and user.is_active
    return {"registered": registered, "telegram_user_id": telegram_user_id}


# ──────────────────────────────────────────────────────────────
# POST /registro/invoice
# Creates a Telegram Stars invoice link for registration.
# Accessible by any TG user (not just registered ones).
# ──────────────────────────────────────────────────────────────
@router.post("/registro/invoice", response_model=InvoiceResponse)
def create_registration_invoice(
    auth=Depends(get_current_telegram_auth),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    telegram_user_id: int = auth["user"]["id"]

    # Idempotency: if already registered, no need to pay again
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user and user.is_active:
        raise HTTPException(status_code=400, detail="Este usuario ya tiene una cuenta activa.")

    try:
        link = create_invoice_link(
            bot_token=settings.telegram_bot_token,
            title="Acceso Bot Finanzas",
            description="Acceso completo al gestor de finanzas personales.",
            payload=f"register:{telegram_user_id}",
            stars_amount=settings.registration_stars_price,
        )
    except RuntimeError as exc:
        logger.error("Failed to create invoice for tg_user_id=%s: %s", telegram_user_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el pago. Intenta de nuevo.") from exc

    return {"invoice_link": link, "stars_price": settings.registration_stars_price}


# ──────────────────────────────────────────────────────────────
# POST /telegram/webhook
# Receives all Bot API updates. No Telegram auth (Telegram calls
# this directly); protected by a shared secret in the header.
# ──────────────────────────────────────────────────────────────
@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()

    # Verify the shared secret configured when registering the webhook
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            logger.warning("Webhook call with invalid secret token.")
            raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    update_id = body.get("update_id", "?")
    logger.debug("Webhook update_id=%s keys=%s", update_id, list(body.keys()))

    # ── pre_checkout_query ────────────────────────────────────
    # Telegram requires an answer within 10 seconds
    pcq = body.get("pre_checkout_query")
    if pcq:
        query_id = pcq.get("id")
        invoice_payload = pcq.get("invoice_payload", "")
        if invoice_payload.startswith("register:"):
            answer_pre_checkout_query(settings.telegram_bot_token, query_id, ok=True)
        else:
            answer_pre_checkout_query(
                settings.telegram_bot_token, query_id, ok=False,
                error_message="Pago no reconocido.",
            )
        return {"ok": True}

    # ── message ───────────────────────────────────────────────
    message = body.get("message") or {}
    tg_user_data: dict = message.get("from", {})
    telegram_user_id: int | None = tg_user_data.get("id")

    # /whoami — devuelve el ID y datos del usuario
    text: str = (message.get("text") or "").strip().lower().split("@")[0]
    if text in ("/whoami", "/start"):
        if telegram_user_id:
            _reply_whoami(settings.telegram_bot_token, telegram_user_id, tg_user_data, db)
        return {"ok": True}

    # successful_payment
    payment = message.get("successful_payment")
    if payment:
        invoice_payload: str = payment.get("invoice_payload", "")
        if invoice_payload.startswith("register:") and telegram_user_id:
            _activate_user(db, telegram_user_id, tg_user_data, settings)
        return {"ok": True}

    return {"ok": True}


# ──────────────────────────────────────────────────────────────
# POST /registro/webhook/setup   (admin — call once after deploy)
# Registers this server's URL as the Telegram Bot webhook.
# ──────────────────────────────────────────────────────────────
@router.post("/registro/webhook/setup", response_model=WebhookSetupResponse)
def setup_webhook(
    webhook_url: str,
    admin_secret: str = Header(default="", alias="X-Admin-Secret"),
):
    settings = get_settings()
    if settings.admin_secret and admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Acceso denegado.")

    result = set_webhook(
        bot_token=settings.telegram_bot_token,
        webhook_url=webhook_url,
        secret_token=settings.telegram_webhook_secret or "",
    )

    # Registrar comandos en el menú de Telegram
    set_my_commands(
        bot_token=settings.telegram_bot_token,
        commands=[
            {"command": "whoami",      "description": "Ver mi ID y estado de cuenta"},
            {"command": "start",       "description": "Bienvenida e información"},
        ],
    )

    return {"ok": bool(result.get("ok")), "description": result.get("description")}


@router.delete("/registro/webhook/setup", response_model=WebhookSetupResponse)
def remove_webhook(
    admin_secret: str = Header(default="", alias="X-Admin-Secret"),
):
    settings = get_settings()
    if settings.admin_secret and admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Acceso denegado.")

    result = delete_webhook(settings.telegram_bot_token)
    return {"ok": bool(result.get("ok")), "description": result.get("description")}


# ──────────────────────────────────────────────────────────────
# Internal helper
# ──────────────────────────────────────────────────────────────
def _reply_whoami(bot_token: str, telegram_user_id: int, tg_user_data: dict, db: Session) -> None:
    first   = tg_user_data.get("first_name") or ""
    last    = tg_user_data.get("last_name") or ""
    uname   = tg_user_data.get("username") or ""
    name    = f"{first} {last}".strip() or "Sin nombre"

    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user and user.is_active:
        status_line = "✅ Tienes acceso completo al gestor."
    elif user and not user.is_active:
        status_line = "⚠️ Tu cuenta está inactiva."
    else:
        status_line = "🔒 Aún no tienes cuenta. Usa el Mini App para registrarte."

    lines = [
        f"👤 <b>{name}</b>",
        f"🆔 <code>{telegram_user_id}</code>",
    ]
    if uname:
        lines.append(f"📎 @{uname}")
    lines.append("")
    lines.append(status_line)

    send_message(bot_token, telegram_user_id, "\n".join(lines))


def _activate_user(db: Session, telegram_user_id: int, tg_user_data: dict, settings) -> None:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))

    if not user:
        user = User(
            telegram_user_id=telegram_user_id,
            first_name=tg_user_data.get("first_name"),
            last_name=tg_user_data.get("last_name"),
            username=tg_user_data.get("username"),
            is_active=True,
            can_use_loans=False,
        )
        db.add(user)
        logger.info("New user registered via Stars payment: telegram_user_id=%s", telegram_user_id)
    else:
        user.is_active = True
        logger.info("User reactivated via Stars payment: telegram_user_id=%s", telegram_user_id)

    db.commit()

    try:
        name = tg_user_data.get("first_name") or "amigo/a"
        send_message(
            settings.telegram_bot_token,
            telegram_user_id,
            (
                f"✅ <b>¡Bienvenido/a, {name}!</b>\n\n"
                "Tu cuenta está activada. Vuelve a abrir el Mini App para empezar a usar el gestor de finanzas."
            ),
        )
    except Exception as exc:
        logger.error("Could not send confirmation message to %s: %s", telegram_user_id, exc)
