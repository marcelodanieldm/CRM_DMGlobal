import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqladmin import Admin

import admin as admin_feedback
from database import engine
from routers import (
    analytics,
    clientes,
    login,
    servicio_feedback,
    servicios,
    suscripciones,
    validacion,
    webhooks,
)
from tasks.renovacion import verificar_renovaciones_vencidas

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        verificar_renovaciones_vencidas,
        CronTrigger(hour=3, minute=0),       # 03:00 ART todos los días
        id="renovacion_diaria",
        replace_existing=True,
        misfire_grace_time=3600,             # tolera hasta 1 hora de downtime
    )
    scheduler.start()
    logger.info("APScheduler iniciado | renovación diaria a las 03:00 ART")
    yield
    scheduler.shutdown(wait=False)
    logger.info("APScheduler detenido")


app = FastAPI(
    title="CRM DMGlobal API",
    description="API interna para gestión de clientes, servicios y suscripciones.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics.router)
app.include_router(clientes.router)
app.include_router(servicios.router)
app.include_router(suscripciones.router)
app.include_router(webhooks.router)
app.include_router(validacion.router)
app.include_router(login.router)
app.include_router(servicio_feedback.router)

# Panel admin del Add-on "Servicio de Feedback" (sqladmin), montado en /admin.
admin = Admin(app, engine, authentication_backend=admin_feedback.crear_auth_backend())
admin_feedback.registrar(admin)


@app.get("/health", tags=["infra"])
def health_check():
    return {"status": "ok"}
