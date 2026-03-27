from app.config import BOLSA_NORMAL, SHEET_EGRESOS, SHEET_INGRESOS, SHEET_MOVIMIENTOS
from app.core.validators import validate_flow_data
from app.services.sheets_service import open_user_spreadsheet


def validar_metodo_egreso(data: dict):
    if data.get("tipo") == "EGR":
        metodo = (data.get("metodo") or "").strip()
        permitidos = {"Efectivo", "Transferencia"}
        if metodo not in permitidos:
            raise ValueError("Para egresos solo se permite Efectivo o Transferencia.")


def create_movimiento(data: dict, sheet_id: str) -> dict:
    validate_flow_data(data)
    validar_metodo_egreso(data)

    sh = open_user_spreadsheet(sheet_id)

    if data["tipo"] == "ING":
        sh.worksheet(SHEET_INGRESOS).append_row([
            data["fecha"],
            data.get("fuente", ""),
            data.get("categoria", ""),
            data["monto"],
            data.get("metodo", ""),
            data.get("banco", ""),
            data.get("nota", ""),
        ], value_input_option="USER_ENTERED")

    elif data["tipo"] == "EGR":
        sh.worksheet(SHEET_EGRESOS).append_row([
            data["fecha"],
            data.get("categoria", ""),
            data["monto"],
            data.get("metodo", ""),
            data.get("banco", ""),
            data.get("nota", ""),
        ], value_input_option="USER_ENTERED")

    elif data["tipo"] == "MOV":
        sh.worksheet(SHEET_MOVIMIENTOS).append_row([
            data["fecha"],
            data.get("bolsa_remitente", BOLSA_NORMAL),
            data.get("remitente", ""),
            data.get("bolsa_destino", BOLSA_NORMAL),
            data.get("destino", ""),
            data["monto"],
            data.get("monto_destino", 0),
            data.get("nota", ""),
            data.get("persona_prestamo", ""),
        ], value_input_option="USER_ENTERED")

    else:
        raise ValueError("Tipo de movimiento no válido.")

    return {"saved": True, "tipo": data["tipo"]}