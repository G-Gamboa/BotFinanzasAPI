from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import User, Movement, Account, Category, LoanPerson


VALID_MOVEMENT_TYPES = {"ING", "EGR", "MOV"}


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def parse_optional_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Las fechas deben usar formato YYYY-MM-DD.")


def detect_subtype(
    movement: Movement,
    source_name: str | None,
    target_name: str | None,
    category_name: str | None,
    loan_person_name: str | None,
) -> str:
    if movement.movement_type == "ING":
        return "INGRESO"

    if movement.movement_type == "EGR":
        return "EGRESO"

    if movement.movement_type != "MOV":
        return "OTRO"

    if source_name == "Ahorro" or target_name == "Ahorro":
        return "AHORRO"

    if loan_person_name or source_name == "Prestamos" or target_name == "Prestamos":
        return "PRESTAMO"

    source_type_hint = (source_name or "").lower()
    target_type_hint = (target_name or "").lower()

    investment_names = {"binance", "hapi", "ugly", "osmo"}
    if source_type_hint in investment_names or target_type_hint in investment_names:
        return "INVERSION"

    return "NORMAL"


def build_history(
    db: Session,
    telegram_user_id: int,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    note: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    parsed_date_from = parse_optional_date(date_from)
    parsed_date_to = parse_optional_date(date_to)

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        raise ValueError("date_from no puede ser mayor que date_to.")

    if movement_type and movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("movement_type debe ser ING, EGR o MOV.")

    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    categories = db.scalars(select(Category).where(Category.user_id == user.id)).all()
    loan_people = db.scalars(select(LoanPerson).where(LoanPerson.user_id == user.id)).all()

    account_by_id = {a.id: a.name for a in accounts}
    category_by_id = {c.id: c.name for c in categories}
    loan_person_by_id = {p.id: p.name for p in loan_people}

    base_filters = [
        Movement.user_id == user.id,
        Movement.is_void == False,
    ]

    if parsed_date_from:
        base_filters.append(Movement.movement_date >= parsed_date_from)
    if parsed_date_to:
        base_filters.append(Movement.movement_date <= parsed_date_to)
    if movement_type:
        base_filters.append(Movement.movement_type == movement_type)
    if note and note.strip():
        base_filters.append(Movement.note.ilike(f"%{note.strip()}%"))

    total_count = db.scalar(
        select(func.count()).select_from(Movement).where(*base_filters)
    ) or 0

    stmt = (
        select(Movement)
        .where(*base_filters)
        .order_by(Movement.movement_date.desc(), Movement.id.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(stmt).all()

    items = []
    for m in rows:
        source_name = account_by_id.get(m.source_account_id)
        target_name = account_by_id.get(m.target_account_id)
        transfer_name = account_by_id.get(m.transfer_account_id)
        category_name = category_by_id.get(m.category_id)
        loan_person_name = loan_person_by_id.get(m.loan_person_id)

        subtype = detect_subtype(
            movement=m,
            source_name=source_name,
            target_name=target_name,
            category_name=category_name,
            loan_person_name=loan_person_name,
        )

        items.append({
            "id": int(m.id),
            "movement_date": m.movement_date.isoformat(),
            "movement_type": m.movement_type,
            "subtype": subtype,
            "amount": round(float(m.amount), 2),
            "destination_amount": round(float(m.destination_amount), 2) if m.destination_amount is not None else None,
            "source_account": source_name,
            "target_account": target_name,
            "transfer_account": transfer_name,
            "category_name": category_name,
            "loan_person_name": loan_person_name,
            "payment_method": m.payment_method,
            "note": m.note,
            "is_void": bool(m.is_void),
        })

    return {
        "items": items,
        "total": len(items),
        "total_count": total_count,
    }