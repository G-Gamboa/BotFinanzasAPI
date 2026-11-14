"""Juego de datos amplio para probar los cálculos financieros de punta a punta."""
from datetime import datetime, timedelta, timezone

from app.db.models import (
    Account, Budget, Category, CreditCardInstallmentPlan, CreditCardPayment,
    Debt, DebtPayment, Loan, LoanPayment, LoanPerson, Movement, SavingsGoal,
)
from app.services.finance_db_service import _add_months, today_gt


def seed_finance_dataset(db, user) -> dict:
    today = today_gt()
    now = datetime.now(timezone.utc)
    close_day = today.day if today.day <= 28 else 28
    uid = user.id

    def acc(name, kind, currency="GTQ", order=0, **extra):
        a = Account(user_id=uid, name=name, account_type=kind, currency=currency,
                    is_active=True, is_system=False, sort_order=order, **extra)
        db.add(a)
        return a

    efectivo = acc("Efectivo", "cash", order=1)
    banco = acc("Banco BI", "bank", order=2)
    banrural = acc("Banrural", "bank", order=3)
    ahorro = acc("Ahorro", "savings", order=4)
    prestamos = acc("Prestamos", "loan_pool", order=5)
    binance = acc("Binance", "investment", "USD", order=6)
    inactiva = acc("Vieja", "bank", order=7)
    inactiva.is_active = False
    tc_q = acc("Visa Q", "credit_card", order=8, credit_limit=10000, visacuotas_limit=5000,
               billing_close_day=close_day, payment_due_day=7, tc_type="GTQ")
    tc_mx = acc("Visa Mixta", "credit_card", order=9, credit_limit=15000,
                billing_close_day=13, payment_due_day=7, tc_type="MIXTO", tc_exchange_rate=7.8)
    tc_usd = acc("Master USD", "credit_card", "USD", order=10, credit_limit=1000,
                 tc_type="USD", tc_exchange_rate=7.75)
    db.flush()

    def cat(name, kind):
        c = Category(user_id=uid, name=name, kind=kind, is_active=True, is_system=False,
                     sort_order=1, created_at=now, updated_at=now)
        db.add(c)
        return c

    salario = cat("Salario", "ING")
    otros_ing = cat("Otros", "ING")
    comida = cat("Alimentación", "EGR")
    servicios = cat("Servicios", "EGR")
    otros = cat("Otros", "EGR")

    ana = LoanPerson(user_id=uid, name="Ana", is_active=True)
    luis = LoanPerson(user_id=uid, name="Luis", is_active=True)
    db.add_all([ana, luis])

    goal = SavingsGoal(user_id=uid, name="Viaje", target_amount=5000, account_name="Banco BI", is_active=True)
    db.add(goal)
    db.flush()

    d = lambda n: today - timedelta(days=n)

    def mov(kind, date_, amount, **kw):
        m = Movement(user_id=uid, movement_type=kind, movement_date=date_, amount=amount, **kw)
        db.add(m)
        return m

    # Ingresos
    mov("ING", d(40), 8000, payment_method="transfer", transfer_account_id=banco.id, category_id=salario.id, note="Quincena")
    mov("ING", d(10), 3168.16, payment_method="transfer", transfer_account_id=banco.id, category_id=salario.id)
    mov("ING", d(0), 500, payment_method="cash", target_account_id=efectivo.id, category_id=otros_ing.id, note="Extra")
    mov("ING", d(3), 900, payment_method="transfer", transfer_account_id=banrural.id, category_id=otros_ing.id)
    # Egresos en efectivo y transferencia
    mov("EGR", d(0), 75.5, payment_method="cash", source_account_id=efectivo.id, category_id=comida.id, note="Almuerzo")
    mov("EGR", d(2), 160, payment_method="transfer", transfer_account_id=banco.id, category_id=servicios.id, note="Internet")
    mov("EGR", d(35), 618, payment_method="transfer", transfer_account_id=banco.id, category_id=servicios.id, note="Luz")
    mov("EGR", d(1), 40, payment_method="cash", source_account_id=efectivo.id, category_id=None, note="Sin categoría")
    anulado = mov("EGR", d(1), 999, payment_method="cash", source_account_id=efectivo.id, category_id=comida.id)
    anulado.is_void = True
    # Cargos a tarjeta
    mov("EGR", d(20), 1200, payment_method="credit_card", credit_card_account_id=tc_q.id, category_id=comida.id)
    mov("EGR", d(0), 300, payment_method="credit_card", credit_card_account_id=tc_q.id, category_id=otros.id)
    mov("EGR", d(5), 450, payment_method="credit_card", credit_card_account_id=tc_mx.id, category_id=comida.id)
    mov("EGR", d(4), 390, payment_method="credit_card", credit_card_account_id=tc_mx.id, category_id=servicios.id,
        amount_foreign=50, note="Meta")
    mov("EGR", d(6), 120, payment_method="credit_card", credit_card_account_id=tc_usd.id, category_id=otros.id)
    # Movimientos entre cuentas, ahorro e inversión
    mov("MOV", d(9), 1000, source_account_id=banco.id, target_account_id=efectivo.id)
    mov("MOV", d(8), 1500, source_account_id=banco.id, target_account_id=ahorro.id, savings_goal_id=goal.id)
    mov("MOV", d(7), 400, source_account_id=banco.id, target_account_id=ahorro.id)
    mov("MOV", d(6), 200, source_account_id=ahorro.id, target_account_id=banco.id)
    mov("MOV", d(6), 100, source_account_id=ahorro.id, target_account_id=banco.id, savings_goal_id=goal.id)
    mov("MOV", d(5), 780, source_account_id=banco.id, target_account_id=binance.id, destination_amount=100)
    mov("MOV", d(4), 20, source_account_id=binance.id, target_account_id=banco.id, destination_amount=154)
    mov("MOV", d(60), 50, source_account_id=efectivo.id, target_account_id=prestamos.id, loan_person_id=ana.id)
    # Préstamos
    loan_ana = Loan(user_id=uid, loan_person_id=ana.id, loan_type="lent", principal_amount=600,
                    loan_date=d(15), status="active", note="Carro", source_account_id=efectivo.id)
    loan_ana2 = Loan(user_id=uid, loan_person_id=ana.id, loan_type="lent", principal_amount=100,
                     loan_date=d(12), status="active", note=None, source_account_id=banco.id)
    mov("EGR", d(11), 800, payment_method="credit_card", credit_card_account_id=tc_q.id,
        note="Regalo", is_third_party=True)
    loan_luis = Loan(user_id=uid, loan_person_id=luis.id, loan_type="lent", principal_amount=800,
                     loan_date=d(11), status="active", note="Regalo", source_tc_account_id=tc_q.id)
    cancelado = Loan(user_id=uid, loan_person_id=luis.id, loan_type="lent", principal_amount=0,
                     loan_date=d(30), status="cancelled", note="Anulado", source_tc_account_id=tc_q.id)
    db.add_all([loan_ana, loan_ana2, loan_luis, cancelado])
    db.flush()
    db.add(LoanPayment(loan_id=loan_ana.id, user_id=uid, amount=250, payment_date=d(3), account_id=banco.id, note="Carro"))
    db.add(LoanPayment(loan_id=loan_luis.id, user_id=uid, amount=300, payment_date=d(2), account_id=tc_q.id, note="Regalo"))
    db.add(LoanPayment(loan_id=loan_ana.id, user_id=uid, amount=70, payment_date=d(1), account_id=banco.id, is_void=True))
    # Deudas
    deuda = Debt(user_id=uid, name="Moto", creditor="Banco", due_date=today + timedelta(days=9),
                 installment_amount=312.5, total_installments=6, paid_installments=2,
                 status="active", payment_frequency="monthly")
    deuda2 = Debt(user_id=uid, name="Laptop", creditor="Tienda", due_date=today + timedelta(days=3),
                  installment_amount=900, total_installments=3, paid_installments=1,
                  status="active", payment_frequency="biweekly")
    pagada = Debt(user_id=uid, name="Vieja", creditor="X", due_date=d(90), installment_amount=100,
                  total_installments=2, paid_installments=2, status="paid", payment_frequency="monthly")
    db.add_all([deuda, deuda2, pagada])
    db.flush()
    db.add(DebtPayment(debt_id=deuda.id, user_id=uid, amount=312.5, payment_date=d(21), account_id=banco.id))
    db.add(DebtPayment(debt_id=deuda2.id, user_id=uid, amount=900, payment_date=d(2), account_id=efectivo.id, note="Laptop 1"))
    db.add(DebtPayment(debt_id=deuda.id, user_id=uid, amount=312.5, payment_date=d(1), account_id=banco.id, is_void=True))
    # Abonos a tarjeta
    db.add(CreditCardPayment(credit_card_account_id=tc_q.id, user_id=uid, amount=500, payment_date=d(18), account_id=banco.id))
    db.add(CreditCardPayment(credit_card_account_id=tc_q.id, user_id=uid, amount=100, payment_date=d(0), account_id=efectivo.id))
    db.add(CreditCardPayment(credit_card_account_id=tc_mx.id, user_id=uid, amount=156, amount_usd=20, payment_date=d(1), account_id=banco.id))
    db.add(CreditCardPayment(credit_card_account_id=tc_usd.id, user_id=uid, amount=310, amount_usd=40, payment_date=d(1), account_id=banco.id))
    db.add(CreditCardPayment(credit_card_account_id=tc_q.id, user_id=uid, amount=77, payment_date=d(1), account_id=banco.id, is_void=True))
    # Visacuotas
    plan = CreditCardInstallmentPlan(user_id=uid, credit_card_account_id=tc_q.id, name="Tele",
                                     total_amount=2400, total_installments=6, monthly_amount=400,
                                     purchase_date=d(70), first_charge_date=_add_months(today, -1),
                                     status="active", is_active=True, created_at=now, category_id=otros.id)
    plan_loan = CreditCardInstallmentPlan(user_id=uid, credit_card_account_id=tc_q.id, name="Cel Luis",
                                          total_amount=1200, total_installments=4, monthly_amount=300,
                                          purchase_date=d(5), first_charge_date=today + timedelta(days=20),
                                          status="active", is_active=True, created_at=now,
                                          is_loan=True, loan_person_id=luis.id)
    db.add_all([plan, plan_loan])
    db.flush()
    mov("EGR", _add_months(today, -1), 400, payment_method="credit_card", credit_card_account_id=tc_q.id,
        category_id=otros.id, installment_plan_id=plan.id, note="Visacuota: Tele")
    mov("EGR", today, 400, payment_method="credit_card", credit_card_account_id=tc_q.id,
        category_id=otros.id, installment_plan_id=plan.id, note="Visacuota: Tele")
    db.add(Budget(user_id=uid, category_id=comida.id, monthly_amount=1500))
    db.commit()
    return {"tc_q": tc_q, "banco": banco, "efectivo": efectivo, "deuda": deuda, "ana": ana,
            "comida": comida, "servicios": servicios, "salario": salario, "plan": plan}
