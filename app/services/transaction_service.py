from collections import defaultdict
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Account, Category, Movement, LoanPerson
from app.schemas.transactions import MovementCreateRequest


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
    accounts = db.scalars(select(Account).where(Account.user_id == user_id)).all()
    return {a.name.lower(): a for a in accounts}


def get_categories_by_name(db: Session, user_id: int, kind: str) -> dict[str, Category]:
    cats = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.kind == kind)
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

            balances = build_loan_balance_internal(db, user.id)
            disponible = balances.get(person.name, 0.0)
            if req.amount > disponible:
                raise ValueError(
                    f"No puedes cobrar {req.amount:.2f} a {person.name}. Disponible: {disponible:.2f}"
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