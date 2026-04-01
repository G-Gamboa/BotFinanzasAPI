from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base




class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    movement_type: Mapped[str] = mapped_column(String, nullable=False)  # ING / EGR / MOV
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    destination_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    transfer_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    loan_person_id: Mapped[int | None] = mapped_column(ForeignKey("loan_people.id"), nullable=True)

    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)

    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

class LoanPerson(Base):
    __tablename__ = "loan_people"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
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
    usd_to_gtq: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=7.7000)

    show_amounts_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_tab: Mapped[str] = mapped_column(String, nullable=False, default="movimientos")
    theme_key: Mapped[str | None] = mapped_column(String, nullable=True)
