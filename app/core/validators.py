
def validate_positive_amount(value: float) -> None:
    if value <= 0:
        raise ValueError("El monto debe ser mayor a 0")
