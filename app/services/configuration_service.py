from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import User, Account, Category, LoanPerson


SYSTEM_ACCOUNT_NAMES = {"ahorro", "prestamos", "efectivo"}
VALID_ACCOUNT_TYPES = {"cash", "bank", "investment", "asset", "savings", "loan_pool", "credit_card"}
VALID_CURRENCIES = {"GTQ", "USD"}
VALID_CATEGORY_KINDS = {"ING", "EGR"}


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def list_accounts(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    items = db.scalars(
        select(Account)
        .where(Account.user_id == user.id)
        .order_by(Account.sort_order, Account.name)
    ).all()

    return {
        "items": [
            {
                "id": int(a.id),
                "name": a.name,
                "account_type": a.account_type,
                "currency": a.currency,
                "is_active": bool(a.is_active),
                "is_system": bool(a.is_system),
                "sort_order": int(a.sort_order),
                "credit_limit": float(a.credit_limit) if a.credit_limit is not None else None,
                "billing_close_day": a.billing_close_day,
                "payment_due_day": a.payment_due_day,
            }
            for a in items
        ]
    }


def create_account(
    db: Session,
    telegram_user_id: int,
    name: str,
    account_type: str,
    currency: str,
    sort_order: int,
    credit_limit: float | None = None,
    billing_close_day: int | None = None,
    payment_due_day: int | None = None,
) -> Account:
    user = get_user_or_raise(db, telegram_user_id)

    name = name.strip()
    if not name:
        raise ValueError("El nombre de la cuenta es obligatorio.")

    if account_type not in VALID_ACCOUNT_TYPES:
        raise ValueError("Tipo de cuenta inválido.")

    if currency not in VALID_CURRENCIES:
        raise ValueError("Moneda inválida.")

    exists = db.scalar(
        select(Account).where(
            Account.user_id == user.id,
            func.lower(Account.name) == name.lower(),
        )
    )
    if exists:
        raise ValueError("Ya existe una cuenta con ese nombre.")

    account = Account(
        user_id=user.id,
        name=name,
        account_type=account_type,
        currency=currency,
        is_active=True,
        is_system=False,
        sort_order=sort_order,
        credit_limit=credit_limit if account_type == "credit_card" else None,
        billing_close_day=billing_close_day if account_type == "credit_card" else None,
        payment_due_day=payment_due_day if account_type == "credit_card" else None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def update_account(
    db: Session,
    account_id: int,
    telegram_user_id: int,
    name: str,
    account_type: str,
    currency: str,
    sort_order: int,
    credit_limit: float | None = None,
    billing_close_day: int | None = None,
    payment_due_day: int | None = None,
) -> Account:
    user = get_user_or_raise(db, telegram_user_id)

    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user.id)
    )
    if not account:
        raise ValueError("Cuenta no encontrada.")

    name = name.strip()
    if not name:
        raise ValueError("El nombre de la cuenta es obligatorio.")

    if account_type not in VALID_ACCOUNT_TYPES:
        raise ValueError("Tipo de cuenta inválido.")

    if currency not in VALID_CURRENCIES:
        raise ValueError("Moneda inválida.")

    duplicated = db.scalar(
        select(Account).where(
            Account.user_id == user.id,
            Account.id != account.id,
            func.lower(Account.name) == name.lower(),
        )
    )
    if duplicated:
        raise ValueError("Ya existe otra cuenta con ese nombre.")

    if account.is_system and account.name.lower() in SYSTEM_ACCOUNT_NAMES:
        if name.lower() != account.name.lower():
            raise ValueError("No puedes renombrar una cuenta del sistema.")
        if account_type != account.account_type:
            raise ValueError("No puedes cambiar el tipo de una cuenta del sistema.")
        if currency != account.currency:
            raise ValueError("No puedes cambiar la moneda de una cuenta del sistema.")

    account.name = name
    account.account_type = account_type
    account.currency = currency
    account.sort_order = sort_order
    # Only touch CC fields when the account is (or becomes) a credit card
    if account_type == "credit_card":
        account.credit_limit = credit_limit
        account.billing_close_day = billing_close_day
        account.payment_due_day = payment_due_day
    else:
        account.credit_limit = None
        account.billing_close_day = None
        account.payment_due_day = None

    db.commit()
    db.refresh(account)
    return account


def set_account_active(
    db: Session,
    account_id: int,
    telegram_user_id: int,
    is_active: bool,
) -> Account:
    user = get_user_or_raise(db, telegram_user_id)

    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user.id)
    )
    if not account:
        raise ValueError("Cuenta no encontrada.")

    if account.is_system and not is_active:
        raise ValueError("No puedes desactivar una cuenta del sistema.")

    account.is_active = is_active
    db.commit()
    db.refresh(account)
    return account


def list_categories(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    items = db.scalars(
        select(Category)
        .where(Category.user_id == user.id)
        .order_by(Category.kind, Category.sort_order, Category.name)
    ).all()

    return {
        "items": [
            {
                "id": int(c.id),
                "name": c.name,
                "kind": c.kind,
                "is_active": bool(c.is_active),
                "is_system": bool(c.is_system),
                "sort_order": int(c.sort_order),
            }
            for c in items
        ]
    }


def create_category(
    db: Session,
    telegram_user_id: int,
    name: str,
    kind: str,
    sort_order: int,
) -> Category:
    user = get_user_or_raise(db, telegram_user_id)

    name = name.strip()
    if not name:
        raise ValueError("El nombre de la categoría es obligatorio.")

    if kind not in VALID_CATEGORY_KINDS:
        raise ValueError("Tipo de categoría inválido.")

    exists = db.scalar(
        select(Category).where(
            Category.user_id == user.id,
            Category.kind == kind,
            func.lower(Category.name) == name.lower(),
        )
    )
    if exists:
        raise ValueError("Ya existe una categoría con ese nombre en ese tipo.")

    category = Category(
        user_id=user.id,
        name=name,
        kind=kind,
        is_active=True,
        is_system=False,
        sort_order=sort_order,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(
    db: Session,
    category_id: int,
    telegram_user_id: int,
    name: str,
    kind: str,
    sort_order: int,
) -> Category:
    user = get_user_or_raise(db, telegram_user_id)

    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if not category:
        raise ValueError("Categoría no encontrada.")

    name = name.strip()
    if not name:
        raise ValueError("El nombre de la categoría es obligatorio.")

    if kind not in VALID_CATEGORY_KINDS:
        raise ValueError("Tipo de categoría inválido.")

    duplicated = db.scalar(
        select(Category).where(
            Category.user_id == user.id,
            Category.id != category.id,
            Category.kind == kind,
            func.lower(Category.name) == name.lower(),
        )
    )
    if duplicated:
        raise ValueError("Ya existe otra categoría con ese nombre en ese tipo.")

    if category.is_system:
        if kind != category.kind:
            raise ValueError("No puedes cambiar el tipo de una categoría del sistema.")
        if name.lower() != category.name.lower():
            raise ValueError("No puedes renombrar una categoría del sistema.")

    category.name = name
    category.kind = kind
    category.sort_order = sort_order

    db.commit()
    db.refresh(category)
    return category


def set_category_active(
    db: Session,
    category_id: int,
    telegram_user_id: int,
    is_active: bool,
) -> Category:
    user = get_user_or_raise(db, telegram_user_id)

    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if not category:
        raise ValueError("Categoría no encontrada.")

    if category.is_system and not is_active:
        raise ValueError("No puedes desactivar una categoría del sistema.")

    category.is_active = is_active
    db.commit()
    db.refresh(category)
    return category


def list_loan_people(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)
    items = db.scalars(
        select(LoanPerson)
        .where(LoanPerson.user_id == user.id)
        .order_by(LoanPerson.name)
    ).all()
    return {
        "items": [
            {"id": int(p.id), "name": p.name, "is_active": bool(p.is_active)}
            for p in items
        ]
    }


def create_loan_person(db: Session, telegram_user_id: int, name: str) -> LoanPerson:
    user = get_user_or_raise(db, telegram_user_id)

    name = name.strip()
    if not name:
        raise ValueError("El nombre es obligatorio.")

    exists = db.scalar(
        select(LoanPerson).where(
            LoanPerson.user_id == user.id,
            func.lower(LoanPerson.name) == name.lower(),
        )
    )
    if exists:
        raise ValueError("Ya existe una persona con ese nombre.")

    person = LoanPerson(user_id=user.id, name=name, is_active=True)
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def update_loan_person(
    db: Session,
    loan_person_id: int,
    telegram_user_id: int,
    name: str,
) -> LoanPerson:
    user = get_user_or_raise(db, telegram_user_id)

    person = db.scalar(
        select(LoanPerson).where(LoanPerson.id == loan_person_id, LoanPerson.user_id == user.id)
    )
    if not person:
        raise ValueError("Persona no encontrada.")

    name = name.strip()
    if not name:
        raise ValueError("El nombre es obligatorio.")

    duplicated = db.scalar(
        select(LoanPerson).where(
            LoanPerson.user_id == user.id,
            LoanPerson.id != person.id,
            func.lower(LoanPerson.name) == name.lower(),
        )
    )
    if duplicated:
        raise ValueError("Ya existe otra persona con ese nombre.")

    person.name = name
    db.commit()
    db.refresh(person)
    return person


def set_loan_person_active(
    db: Session,
    loan_person_id: int,
    telegram_user_id: int,
    is_active: bool,
) -> LoanPerson:
    user = get_user_or_raise(db, telegram_user_id)

    person = db.scalar(
        select(LoanPerson).where(LoanPerson.id == loan_person_id, LoanPerson.user_id == user.id)
    )
    if not person:
        raise ValueError("Persona no encontrada.")

    person.is_active = is_active
    db.commit()
    db.refresh(person)
    return person