# Bot Finanzas API

Base de API con FastAPI para el proyecto Bot Finanzas.

## Variables de entorno
Usa `.env.example` como referencia.

## Ejecución local
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoints base
- `GET /health`
- `GET /resumen/{user_id}`
- `GET /saldos/{user_id}`
- `GET /networth/{user_id}`
- `GET /deudas/{user_id}`
- `GET /deudas/activas/{user_id}`
- `POST /deudas`
- `POST /deudas/pagar`
- `POST /movimientos`

## Nota
Ya usa `USER_SHEETS` para resolver la hoja por usuario. La lógica real de cálculo/guardado se irá reemplazando poco a poco con la lógica de tu bot actual.
