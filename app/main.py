from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.catalogos import router as catalogos_router
from app.routers.deudas import router as deudas_router
from app.routers.health import router as health_router
from app.routers.movimientos import router as movimientos_router
from app.routers.networth import router as networth_router
from app.routers.resumen import router as resumen_router


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title='Bot Finanzas API',
        version='1.0.0',
        description='API de finanzas multiusuario basada en Google Sheets.',
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    app.include_router(health_router)
    app.include_router(catalogos_router)
    app.include_router(resumen_router)
    app.include_router(networth_router)
    app.include_router(deudas_router)
    app.include_router(movimientos_router)

    return app


app = create_app()
