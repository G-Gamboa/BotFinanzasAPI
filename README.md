# Bot Finanzas API Base

Base limpia para la API DB-first con FastAPI + Supabase/Postgres.

## Endpoints incluidos
- GET /health
- GET /saldos/{telegram_user_id}
- GET /networth/{telegram_user_id}
- GET /neto/{telegram_user_id}

## Deploy en Railway
Usa el Procfile incluido o define el start command:

uvicorn app.main:app --host 0.0.0.0 --port $PORT
