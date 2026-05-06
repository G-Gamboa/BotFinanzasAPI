from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Loan, LoanPayment, LoanPerson


def get_user_or_raise(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def normalize_loan_concept(note: str | None) -> str:
    if note is None:
        return "General"

    normalized = " ".join(note.strip().split())
    return normalized if normalized else "General"


def build_loans_view(db: Session, telegram_user_id: int) -> dict:
    user = get_user_or_raise(db, telegram_user_id)

    loan_people = db.scalars(
        select(LoanPerson).where(LoanPerson.user_id == user.id)
    ).all()
    loan_person_by_id = {lp.id: lp.name for lp in loan_people}

    loans = db.scalars(
        select(Loan)
        .where(Loan.user_id == user.id, Loan.loan_type == "lent")
        .order_by(Loan.id.asc())
    ).all()

    loan_payments = db.scalars(
        select(LoanPayment)
        .where(LoanPayment.user_id == user.id)
        .order_by(LoanPayment.id.asc())
    ).all()

    person_concepts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for loan in loans:
        person_name = loan_person_by_id.get(loan.loan_person_id)
        if not person_name:
            continue
        concept = normalize_loan_concept(loan.note)
        person_concepts[person_name][concept] += float(loan.amount)

    for payment in loan_payments:
        person_name = loan_person_by_id.get(payment.loan_person_id)
        if not person_name:
            continue
        concept = normalize_loan_concept(payment.note)
        person_concepts[person_name][concept] -= float(payment.amount)

    items: list[dict] = []

    for person_name in sorted(person_concepts.keys()):
        concepts_raw = person_concepts[person_name]

        concepts = []
        total_balance = 0.0

        for concept_name, balance in sorted(concepts_raw.items(), key=lambda x: x[0].lower()):
            rounded_balance = round(balance, 2)
            if rounded_balance <= 0:
                continue

            concepts.append({
                "concept": concept_name,
                "balance": rounded_balance,
            })
            total_balance += rounded_balance

        if total_balance <= 0:
            continue

        concepts.sort(key=lambda x: (x["concept"] != "General", x["concept"].lower()))

        items.append({
            "person": person_name,
            "total_balance": round(total_balance, 2),
            "concepts": concepts,
        })

    return {
        "items": items,
        "total_people": len(items),
    }


def get_loan_concepts_balance(
    db: Session,
    telegram_user_id: int,
    loan_person_name: str,
) -> dict[str, float]:
    data = build_loans_view(db, telegram_user_id)

    for item in data["items"]:
        if item["person"] == loan_person_name:
            return {c["concept"]: float(c["balance"]) for c in item["concepts"]}

    return {}
