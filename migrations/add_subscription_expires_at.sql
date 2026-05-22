-- Suscripción mensual: fecha de vencimiento por usuario
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ;

-- Usuarios ya activos que existían antes de esta migración
-- se quedan sin fecha (NULL = acceso permanente heredado; ajusta si quieres fijar una fecha)
-- UPDATE users SET subscription_expires_at = NOW() + INTERVAL '30 days' WHERE is_active = true;
