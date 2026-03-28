from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_use_loans: Mapped[bool] = mapped_column(Boolean, default=False)
    theme_key: Mapped[str] = mapped_column(String, default="neutral")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)


class LoanPerson(Base):
    __tablename__ = "loan_people"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String, nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    destination_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(String)
    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    payment_method: Mapped[str | None] = mapped_column(String)
    transfer_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    loan_person_id: Mapped[int | None] = mapped_column(ForeignKey("loan_people.id"))


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    creditor: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


class UserSetting(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    preferred_currency: Mapped[str] = mapped_column(String, nullable=False)
    usd_to_gtq: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    hide_amounts_default: Mapped[bool] = mapped_column(Boolean, default=False)
