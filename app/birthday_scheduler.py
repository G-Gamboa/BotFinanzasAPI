import json
import logging
import os
import random
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CHAT_ID = "5592032215"
_GT_OFFSET = timedelta(hours=-6)

_NOTIFICATIONS = [
    "🌙 Feliz cumpleaños mi vida... abre el app, tengo algo especial para ti hoy.",
    "💫 Son las madrugadas y no puedo dejar de pensar en ti. Abre esto, es para ti.",
    "✨ Las madrugadas siempre serán nuestras. Tienes un mensajito esperándote.",
    "🌟 Todo está en calma, pero mi corazón celebra tu día. Entra un momento.",
    "💖 Falta poco para que amanezca. Tienes algo esperándote aquí.",
    "🌅 Pronto amanecerá. Este mensajito es solo para ti, abre el app.",
    "☀️ Buenos días en tu cumpleaños, mi amor. Entra, tienes un mensaje.",
    "🌸 Esta mañana es especial porque tú cumples años. Algo aquí para ti.",
    "🎀 Espero que tu mañana vaya siendo bonita. Tienes un mensajito.",
    "💝 Tu día va a toda marcha. Entra un momento, tengo algo para ti.",
    "🎊 A media mañana de tu cumpleaños. ¿Ya viste tu mensaje de las 10?",
    "🌺 Casi es mediodía y yo sigo pensando en ti. Entra, hay uno más.",
    "🎂 Mediodía de tu cumpleaños. Tienes un mensaje esperándote aquí.",
    "💕 La tarde de tu cumpleaños apenas comienza. Entra un momento.",
    "🌈 ¿Estás disfrutando tu día? Tienes algo esperándote en el app.",
    "🦋 La tarde avanza con mensajitos para ti. Uno nuevo te espera.",
    "✨ Cuatro de la tarde en tu cumpleaños. Entra, hay algo para ti.",
    "💫 El día va a paso de fiesta. Un mensajito tuyo está esperando.",
    "🌆 Atardecer de tu cumpleaños. Tienes algo bonito aquí adentro.",
    "🌟 La noche se acerca y yo sigo celebrando que hoy naciste. Entra.",
    "🎉 La noche de tu cumpleaños. Entra, tienes un mensaje de las 8.",
    "💖 Ya casi es noche. Sigo pensando en ti. Tienes un mensajito.",
    "🌙 Las últimas horas de tu cumpleaños. Entra, hay uno más para ti.",
    "⭐ Las últimas horas de este día especial... Entra un momento, mi amor.",
]


def _gt_now() -> datetime:
    return datetime.now(timezone.utc) + _GT_OFFSET


def _is_birthday() -> bool:
    gt = _gt_now()
    return gt.month == 11 and gt.day == 12


def _send(token: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": _CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def _scheduler_loop() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("birthday_scheduler: TELEGRAM_BOT_TOKEN not set, skipping.")
        return

    # Wait until Nov 12 GT — check every 5 min if we're early
    while not _is_birthday():
        time.sleep(300)

    logger.info("birthday_scheduler: Nov 12 GT — building schedule.")

    # Build random send-times for each of 24 hours
    schedule = []
    for h, text in enumerate(_NOTIFICATIONS):
        minute = random.randint(2, 57)
        second = random.randint(5, 55)
        schedule.append((h, minute, second, text))

    for h, minute, second, text in schedule:
        # Skip hours already fully past when scheduler starts late
        if _gt_now().hour > h:
            logger.info("birthday_scheduler: skipping h=%d (already past)", h)
            continue

        # Wait until it's time for this hour's notification
        while True:
            if not _is_birthday():
                logger.info("birthday_scheduler: day ended, stopping.")
                return
            gt = _gt_now()
            if gt.hour == h and (gt.minute > minute or (gt.minute == minute and gt.second >= second)):
                break
            if gt.hour > h:
                break
            time.sleep(5)

        if not _is_birthday():
            return

        try:
            _send(token, text)
            logger.info("birthday_scheduler: sent notification for h=%d", h)
        except Exception:
            logger.exception("birthday_scheduler: failed to send for h=%d", h)

    logger.info("birthday_scheduler: all 24 notifications done.")


def start_birthday_scheduler() -> None:
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="birthday-scheduler")
    t.start()
    logger.info("birthday_scheduler: thread started.")
