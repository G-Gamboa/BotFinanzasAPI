# Bot Finanzas API

API FastAPI para Bot Finanzas con soporte multiusuario vía `USER_SHEETS`.

## Levantar local

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoints

- `GET /health`
- `GET /catalogos/{user_id}`
- `GET /resumen/{user_id}`
- `GET /resumen/semana/{user_id}`
- `GET /saldos/{user_id}`
- `GET /networth/{user_id}`
- `GET /neto/{user_id}`
- `GET /deudas/{user_id}`
- `GET /deudas/activas/{user_id}`
- `POST /movimientos`
- `POST /deudas`
- `POST /deudas/pagar`
