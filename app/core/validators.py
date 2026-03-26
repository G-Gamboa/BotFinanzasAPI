
from app.core.helpers import parse_iso_date


def validate_nueva_deuda(payload: dict) -> None:
    parse_iso_date(payload["deuda_fecha_pago"])
    if payload["deuda_pagados"] > payload["deuda_meses"]:
        raise ValueError("deuda_pagados no puede ser mayor que deuda_meses")


def validate_movimiento(payload: dict) -> None:
    parse_iso_date(payload["fecha"])
    if payload["monto"] <= 0:
        raise ValueError("El monto debe ser mayor a 0")
    if payload.get("remitente") and payload.get("destino") and payload["remitente"] == payload["destino"]:
        raise ValueError("Remitente y destino no pueden ser iguales")
    if payload.get("monto_destino") is not None and payload["monto_destino"] < 0:
        raise ValueError("monto_destino no puede ser negativo")
