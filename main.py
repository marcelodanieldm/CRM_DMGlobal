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
from virtual_receptionist.routers.whatsapp import (
    router as whatsapp_router,
    init_wa_client,
    close_wa_client,
)
from virtual_receptionist.services.crm_service import (
    init_http_client as init_crm_client,
    close_http_client as close_crm_client,
)
from virtual_receptionist.services.ai_service import (
    init_genai_client,
    limpiar_sesiones_expiradas,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Arranque ──────────────────────────────────────────────────────────────
    # CRM existente
    scheduler.add_job(
        verificar_renovaciones_vencidas,
        CronTrigger(hour=3, minute=0),
        id="renovacion_diaria",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Recepcionista Virtual — inicializar clientes HTTP y SDK de Gemini
    await init_crm_client()
    await init_wa_client()
    init_genai_client()

    # Limpieza de sesiones de conversación vencidas (cada hora)
    scheduler.add_job(
        limpiar_sesiones_expiradas,
        CronTrigger(minute=0),           # cada hora en punto
        id="limpiar_sesiones_recepcionista",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler iniciado | renovación diaria + limpieza de sesiones")
    logger.info("Recepcionista Virtual Nocturno: listo.")

    yield

    # ── Cierre ordenado ───────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    await close_wa_client()
    await close_crm_client()
    logger.info("APScheduler detenido | clientes HTTP cerrados.")


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
app.include_router(whatsapp_router)

# Panel admin del Add-on "Servicio de Feedback" (sqladmin), montado en /admin.
admin = Admin(app, engine, authentication_backend=admin_feedback.crear_auth_backend())
admin_feedback.registrar(admin)


@app.get("/health", tags=["infra"])
def health_check():
    return {"status": "ok"}
