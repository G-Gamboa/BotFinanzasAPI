-- ============================================================
-- Migración: orden de pestañas por usuario
-- Ejecutar UNA sola vez. Seguro re-ejecutar (IF NOT EXISTS).
-- ============================================================

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS tab_order TEXT;   -- JSON array: ["movimientos","historial",...]
