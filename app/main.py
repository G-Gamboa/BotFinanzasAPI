
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, resumen, networth, deudas, movimientos

def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(resumen.router, prefix="/api/v1", tags=["resumen"])
    app.include_router(networth.router, prefix="/api/v1", tags=["networth"])
    app.include_router(deudas.router, prefix="/api/v1", tags=["deudas"])
    app.include_router(movimientos.router, prefix="/api/v1", tags=["movimientos"])
    return app

app = create_app()
