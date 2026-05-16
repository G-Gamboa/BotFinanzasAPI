-- ============================================================
-- Migración: índices de rendimiento
-- Ejecutar UNA sola vez contra la base de datos PostgreSQL.
-- Todos usan IF NOT EXISTS — es seguro re-ejecutar.
-- ============================================================

-- ── movements (tabla más consultada) ────────────────────────
-- Filtro base de casi todas las queries
CREATE INDEX IF NOT EXISTS idx_movements_user_void
    ON movements (user_id, is_void);

-- Filtros de fecha (build_period_summary)
CREATE INDEX IF NOT EXISTS idx_movements_user_date
    ON movements (user_id, movement_date)
    WHERE is_void = FALSE;

-- Cargos a TC (build_cc_balances)
CREATE INDEX IF NOT EXISTS idx_movements_cc_account
    ON movements (credit_card_account_id, is_void)
    WHERE credit_card_account_id IS NOT NULL;

-- Planes de visacuotas — COUNT agrupado (build_cc_balances, build_neto)
CREATE INDEX IF NOT EXISTS idx_movements_installment_plan
    ON movements (installment_plan_id, is_void)
    WHERE installment_plan_id IS NOT NULL;

-- Metas de ahorro (build_savings_goals)
CREATE INDEX IF NOT EXISTS idx_movements_savings_goal
    ON movements (savings_goal_id, is_void)
    WHERE savings_goal_id IS NOT NULL;

-- ── accounts ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_accounts_user_id
    ON accounts (user_id);

CREATE INDEX IF NOT EXISTS idx_accounts_user_type_active
    ON accounts (user_id, account_type, is_active);

-- ── debts ────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_debts_user_status
    ON debts (user_id, status);

-- ── debt_payments ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_debt_payments_user_void
    ON debt_payments (user_id, is_void);

CREATE INDEX IF NOT EXISTS idx_debt_payments_user_date
    ON debt_payments (user_id, payment_date)
    WHERE is_void = FALSE;

-- ── loans ────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_loans_user_type
    ON loans (user_id, loan_type);

-- ── loan_payments ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_loan_payments_user_void
    ON loan_payments (user_id, is_void);

CREATE INDEX IF NOT EXISTS idx_loan_payments_loan_id
    ON loan_payments (loan_id);

-- ── credit_card_payments ──────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cc_payments_user_void
    ON credit_card_payments (user_id, is_void);

CREATE INDEX IF NOT EXISTS idx_cc_payments_cc_account
    ON credit_card_payments (credit_card_account_id, is_void);

-- ── cc_installment_plans ──────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cc_plans_user_status
    ON cc_installment_plans (user_id, status, is_active);

CREATE INDEX IF NOT EXISTS idx_cc_plans_cc_account
    ON cc_installment_plans (credit_card_account_id);

-- ── users ────────────────────────────────────────────────────
-- telegram_user_id ya tiene UNIQUE (implica índice), pero lo confirmamos
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_user_id
    ON users (telegram_user_id);

-- ── user_settings ─────────────────────────────────────────────
-- user_id ya tiene UNIQUE constraint
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_settings_user_id
    ON user_settings (user_id);
