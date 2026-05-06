import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Account, Category, Movement, LoanPerson
from app.schemas.transactions import MovementCreateRequest
from app.services.loans_view_service import (
    get_loan_concepts_balance,
    normalize_loan_concept,
)

logger = logging.getLogger(__name__)


LIQUID_TYPES = {"cash", "bank"}
INVESTMENT_TYPES = {"investment"}


def parse_iso_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("movement_date debe usar formato YYYY-MM-DD.")


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def get_accounts_by_name(db: Session, user_id: int) -> dict[str, Account]:
    accounts = db.scalars(
        select(Account).where(Account.user_id == user_id, Account.is_active == True)
    ).all()
    return {a.name.lower(): a for a in accounts}


def get_categories_by_name(db: Session, user_id: int, kind: str) -> dict[str, Category]:
    cats = db.scalars(
        select(Category).where(
            Category.user_id == user_id,
            Category.kind == kind,
            Category.is_active == True,
        )
    ).all()
    return {c.name.lower(): c for c in cats}


def get_loan_people_by_name(db: Session, user_id: int) -> dict[str, LoanPerson]:
    people = db.scalars(select(LoanPerson).where(LoanPerson.user_id == user_id)).all()
    return {p.name.lower(): p for p in people}


def get_account_or_raise(accounts_by_name: dict[str, Account], name: str, label: str) -> Account:
    acc = accounts_by_name.get((name or "").strip().lower())
    if not acc:
        raise ValueError(f"{label} no existe: {name}")
    return acc


def require_liquid_account(account: Account, label: str):
    if account.account_type not in LIQUID_TYPES:
        raise ValueError(f"{label} debe ser una cuenta líquida.")


def require_investment_account(account: Account, label: str):
    if account.account_type not in INVESTMENT_TYPES:
        raise ValueError(f"{label} debe ser una cuenta de inversión.")


def require_named_account(account: Account, expected_name: str, label: str):
    if account.name.lower() != expected_name.lower():
        raise ValueError(f"{label} debe ser {expected_name}.")


def build_ahorro_breakdown_internal(db: Session, user_id: int) -> dict[str, float]:
    accounts = db.scalars(select(Account).where(Account.user_id == user_id)).all()
    account_by_id = {a.id: a for a in accounts}

    ahorro_por_cuenta = defaultdict(float)

    movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user_id,
            Movement.movement_type == "MOV",
            Movement.is_void == False,
        )
    ).all()

    for m in movements:
        source_name = account_by_id[m.source_account_id].name if m.source_account_id in account_by_id else None
        target_name = account_by_id[m.target_account_id].name if m.target_account_id in account_by_id else None

        if target_name == "Ahorro" and source_name and source_name != "Ahorro":
            ahorro_por_cuenta[source_name] += float(m.amount)
        elif source_name == "Ahorro" and target_name and target_name != "Ahorro":
            outgoing = float(m.destination_amount) if m.destination_amount is not None else float(m.amount)
            ahorro_por_cuenta[target_name] -= outgoing

    return {k: round(v, 2) for k, v in ahorro_por_cuenta.items()}


def build_loan_balance_internal(db: Session, user_id: int) -> dict[str, float]:
    accounts = db.scalars(select(Account).where(Account.user_id == user_id)).all()
    account_by_id = {a.id: a for a in accounts}

    people = db.scalars(select(LoanPerson).where(LoanPerson.user_id == user_id)).all()
    people_by_id = {p.id: p.name for p in people}

    balances = defaultdict(float)

    movements = db.scalars(
        select(Movement).where(
            Movement.user_id == user_id,
            Movement.movement_type == "MOV",
            Movement.is_void == False,
        )
    ).all()

    for m in movements:
        if not m.loan_person_id:
            continue

        source_name = account_by_id[m.source_account_id].name if m.source_account_id in account_by_id else None
        target_name = account_by_id[m.target_account_id].name if m.target_account_id in account_by_id else None
        person = people_by_id.get(m.loan_person_id)

        if not person:
            continue

        if target_name == "Prestamos":
            balances[person] += float(m.amount)
        elif source_name == "Prestamos":
            outgoing = float(m.destination_amount) if m.destination_amount is not None else float(m.amount)
            balances[person] -= outgoing

    return {k: round(v, 2) for k, v in balances.items()}


def validate_loan_collection_amount(
    db: Session,
    telegram_user_id: int,
    loan_person_name: str,
    note: str | None,
    amount: float,
) -> None:
    concept = normalize_loan_concept(note)
    concepts_balance = get_loan_concepts_balance(db, telegram_user_id, loan_person_name)

    available = float(concepts_balance.get(concept, 0.0))

    if available <= 0:
        raise ValueError(f"No existe saldo disponible en '{concept}' para {loan_person_name}.")

    if float(amount) > available:
        raise ValueError(
            f"El monto excede el saldo disponible en '{concept}' para {loan_person_name}. Disponible: Q {available:.2f}"
        )


def create_ingreso(db: Session, req: MovementCreateRequest) -> Movement:
    user = get_user_or_raise(db, req.telegram_user_id)
    accounts = get_accounts_by_name(db, user.id)
    categories = get_categories_by_name(db, user.id, "ING")

    account = get_account_or_raise(accounts, req.account_name, "account_name")
    require_liquid_account(account, "account_name")

    category = categories.get(req.category_name.strip().lower())
    if not category:
        raise ValueError(f"Categoría ING no existe: {req.category_name}")

    payment_method = req.payment_method
    if payment_method not in {"Efectivo", "Transferencia"}:
        raise ValueError("payment_method inválido.")

    movement = Movement(
        user_id=user.id,
        movement_type="ING",
        movement_date=parse_iso_date(req.movement_date),
        amount=req.amount,
        destination_amount=None,
        note=req.note,
        source_account_id=None,
        target_account_id=account.id if payment_method == "Efectivo" else None,
        category_id=category.id,
        payment_method=payment_method,
        transfer_account_id=account.id if payment_method == "Transferencia" else None,
        loan_person_id=None,
    )
    db.add(movement)
    db.flush()
    return movement


def create_egreso(db: Session, req: MovementCreateRequest) -> Movement:
    user = get_user_or_raise(db, req.telegram_user_id)
    accounts = get_accounts_by_name(db, user.id)
    categories = get_categories_by_name(db, user.id, "EGR")

    account = get_account_or_raise(accounts, req.account_name, "account_name")
    require_liquid_account(account, "account_name")

    category = categories.get(req.category_name.strip().lower())
    if not category:
        raise ValueError(f"Categoría EGR no existe: {req.category_name}")

    payment_method = req.payment_method
    if payment_method not in {"Efectivo", "Transferencia"}:
        raise ValueError("payment_method inválido.")

    movement = Movement(
        user_id=user.id,
        movement_type="EGR",
        movement_date=parse_iso_date(req.movement_date),
        amount=req.amount,
        destination_amount=None,
        note=req.note,
        source_account_id=account.id if payment_method == "Efectivo" else None,
        target_account_id=None,
        category_id=category.id,
        payment_method=payment_method,
        transfer_account_id=account.id if payment_method == "Transferencia" else None,
        loan_person_id=None,
    )
    db.add(movement)
    db.flush()
    return movement


def create_movimiento(db: Session, req: MovementCreateRequest) -> Movement:
    user = get_user_or_raise(db, req.telegram_user_id)
    accounts = get_accounts_by_name(db, user.id)
    people = get_loan_people_by_name(db, user.id)

    mov_date = parse_iso_date(req.movement_date)
    note = req.note
    destination_amount = req.destination_amount if req.destination_amount not in (None, 0) else None

    subtype = req.mov_subtype
    direction = req.mov_direction

    if subtype == "NORMAL":
        source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
        target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
        require_liquid_account(source, "source_account_name")
        require_liquid_account(target, "target_account_name")

        if source.id == target.id:
            raise ValueError("source_account_name y target_account_name no pueden ser iguales.")

        movement = Movement(
            user_id=user.id,
            movement_type="MOV",
            movement_date=mov_date,
            amount=req.amount,
            destination_amount=destination_amount,
            note=note,
            source_account_id=source.id,
            target_account_id=target.id,
            category_id=None,
            payment_method=None,
            transfer_account_id=None,
            loan_person_id=None,
        )
        db.add(movement)
        db.flush()
        return movement

    if subtype == "AHORRO":
        ahorro = get_account_or_raise(accounts, "Ahorro", "Cuenta ahorro")

        if direction == "GUARDAR":
            source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
            require_liquid_account(source, "source_account_name")

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=None,
                note=note,
                source_account_id=source.id,
                target_account_id=ahorro.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=None,
            )
            db.add(movement)
            db.flush()
            return movement

        if direction == "RETIRAR":
            target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
            require_liquid_account(target, "target_account_name")

            ahorro_breakdown = build_ahorro_breakdown_internal(db, user.id)
            disponible = ahorro_breakdown.get(target.name, 0.0)
            if req.amount > disponible:
                raise ValueError(
                    f"No puedes retirar {req.amount:.2f} desde ahorro hacia {target.name}. "
                    f"Disponible: {disponible:.2f}"
                )

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=None,
                note=note,
                source_account_id=ahorro.id,
                target_account_id=target.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=None,
            )
            db.add(movement)
            db.flush()
            return movement

        raise ValueError("mov_direction inválido para AHORRO.")

    if subtype == "INVERSION":
        if direction == "INVERTIR":
            source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
            target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
            require_liquid_account(source, "source_account_name")
            require_investment_account(target, "target_account_name")

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=destination_amount,
                note=note,
                source_account_id=source.id,
                target_account_id=target.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=None,
            )
            db.add(movement)
            db.flush()
            return movement

        if direction == "RETIRAR_INV":
            source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
            target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
            require_investment_account(source, "source_account_name")
            require_liquid_account(target, "target_account_name")

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=destination_amount,
                note=note,
                source_account_id=source.id,
                target_account_id=target.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=None,
            )
            db.add(movement)
            db.flush()
            return movement

        if direction == "MOVER_INV":
            source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
            target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
            require_investment_account(source, "source_account_name")
            require_investment_account(target, "target_account_name")

            if source.id == target.id:
                raise ValueError("source_account_name y target_account_name no pueden ser iguales.")

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=destination_amount,
                note=note,
                source_account_id=source.id,
                target_account_id=target.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=None,
            )
            db.add(movement)
            db.flush()
            return movement

        raise ValueError("mov_direction inválido para INVERSION.")

    if subtype == "PRESTAMO":
        if not user.can_use_loans:
            raise ValueError("Este usuario no tiene permiso para usar préstamos.")

        prest = get_account_or_raise(accounts, "Prestamos", "Cuenta préstamos")

        person = people.get((req.loan_person_name or "").strip().lower())
        if not person:
            raise ValueError(f"loan_person_name no existe: {req.loan_person_name}")

        if direction == "DAR":
            source = get_account_or_raise(accounts, req.source_account_name, "source_account_name")
            require_liquid_account(source, "source_account_name")

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=None,
                note=note,
                source_account_id=source.id,
                target_account_id=prest.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=person.id,
            )
            db.add(movement)
            db.flush()
            return movement

        if direction == "COBRAR":
            target = get_account_or_raise(accounts, req.target_account_name, "target_account_name")
            require_liquid_account(target, "target_account_name")

            validate_loan_collection_amount(
                db=db,
                telegram_user_id=req.telegram_user_id,
                loan_person_name=person.name,
                note=req.note,
                amount=float(req.amount),
            )

            balances = build_loan_balance_internal(db, user.id)
            disponible = balances.get(person.name, 0.0)
            if req.amount > disponible:
                raise ValueError(
                    f"No puedes cobrar {req.amount:.2f} a {person.name}. Disponible total: {disponible:.2f}"
                )

            movement = Movement(
                user_id=user.id,
                movement_type="MOV",
                movement_date=mov_date,
                amount=req.amount,
                destination_amount=None,
                note=note,
                source_account_id=prest.id,
                target_account_id=target.id,
                category_id=None,
                payment_method=None,
                transfer_account_id=None,
                loan_person_id=person.id,
            )
            db.add(movement)
            db.flush()
            return movement

        raise ValueError("mov_direction inválido para PRESTAMO.")

    raise ValueError("mov_subtype inválido.")


def create_movement(db: Session, req: MovementCreateRequest) -> Movement:
    # Lock the user row to serialize concurrent balance-check + insert operations,
    # preventing TOCTOU race conditions on savings and loan balances.
    locked_user = db.scalar(
        select(User).where(User.telegram_user_id == req.telegram_user_id).with_for_update()
    )
    if not locked_user:
        raise ValueError("Usuario no encontrado.")

    if req.movement_type == "ING":
        movement = create_ingreso(db, req)
    elif req.movement_type == "EGR":
        movement = create_egreso(db, req)
    elif req.movement_type == "MOV":
        movement = create_movimiento(db, req)
    else:
        raise ValueError("movement_type inválido.")

    db.commit()
    db.refresh(movement)
    return movement


def void_movement(
    db: Session,
    telegram_user_id: int,
    movement_id: int,
    reason: str | None = None,
) -> Movement:
    user = get_user_or_raise(db, telegram_user_id)

    movement = db.get(Movement, movement_id)
    if not movement:
        raise ValueError("Movimiento no encontrado.")

    if movement.user_id != user.id:
        logger.warning("Intento de anular movimiento ajeno: movement_id=%s usuario=%s", movement_id, telegram_user_id)
        raise ValueError("No tienes permiso para anular este movimiento.")

    if movement.is_void:
        raise ValueError("El movimiento ya está anulado.")

    movement.is_void = True
    movement.void_reason = (reason or "").strip() or None
    movement.voided_at = datetime.now(timezone.utc)

    db.add(movement)
    db.commit()
    db.refresh(movement)

    return movement