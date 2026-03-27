from app.services.catalog_service import get_catalogos_for_user
from app.services.finance_service import (
    get_deudas,
    get_neto,
    get_networth,
    get_saldos,
    get_resumen_mes,
    get_resumen_semana,
)


def get_dashboard(sheet_id: str, user_id: int) -> dict:
    resumen_mes = get_resumen_mes(sheet_id)
    resumen_semana = get_resumen_semana(sheet_id)
    saldos = get_saldos(sheet_id)
    networth = get_networth(sheet_id)
    deudas = get_deudas(sheet_id)

    deudas_activas = [d for d in deudas if str(d.get("estado", "")).lower() == "activa"]
    total_deudas = round(sum(float(d.get("saldo", 0) or 0) for d in deudas_activas), 2)

    neto = {
        "networth_q": networth["networth_q"],
        "deudas_activas_q": total_deudas,
        "neto_q": round(networth["networth_q"] - total_deudas, 2),
    }

    catalogos = get_catalogos_for_user(sheet_id)

    return {
        "user_id": user_id,
        "resumen_mes": resumen_mes,
        "resumen_semana": resumen_semana,
        "saldos": saldos,
        "networth": networth,
        "neto": neto,
        "deudas": deudas,
        "deudas_activas": deudas_activas,
        "total_deudas": total_deudas,
        "catalogos": catalogos,
    }