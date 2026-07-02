"""
Servicios Premium — Router de configuración por cliente.

Expone endpoints para leer y guardar la configuración técnica de los dos
servicios add-on premium de DM Global vinculados a un cliente:

  1. Servicio de Feedback     → GET/PUT /api/v1/clientes/{id}/feedback-config
  2. Recepcionista Virtual    → GET/PUT /api/v1/clientes/{id}/recepcionista-config
  3. Config combinada         → GET     /api/v1/clientes/{id}/servicios-premium

Acceso:
    Lectura  → admin + soporte
    Escritura → solo admin
"""
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin, require_admin_o_soporte
from database import get_db
from models import Cliente, ConfigFeedbackCliente, ConfigRecepcionistaCliente

router = APIRouter(prefix="/api/v1/clientes", tags=["servicios-premium"])

DbDep       = Annotated[Session, Depends(get_db)]
SoporteAdmin = Annotated[None, Depends(require_admin_o_soporte)]
SoloAdmin   = Annotated[None, Depends(require_admin)]


# ─────────────────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ─────────────────────────────────────────────────────────────────────────────

TIPOS_NEGOCIO = ["HOTEL", "TOUR", "TRANSFER", "ALQUILER", "RESTO"]


class FeedbackConfigSchema(BaseModel):
    tipo_negocio:      str           = Field(default="HOTEL", description="Sector del comercio")
    google_review_link: Optional[str] = Field(default=None, description="URL del perfil de Google Reviews")
    google_sheet_url:  Optional[str] = Field(default=None, description="URL de la planilla de Google Sheets asignada")
    activo:            bool          = Field(default=True)

    model_config = {"from_attributes": True}


class FeedbackConfigRead(FeedbackConfigSchema):
    id:         int
    cliente_id: int
    created_at: datetime
    updated_at: datetime


class RecepcionistaConfigSchema(BaseModel):
    hotel_id:                  Optional[str] = Field(
        default=None,
        description="ID legible del hotel (ej: HOTEL-TERRAZAS-01). "
                    "Usado como ID de licencia en la planilla del cliente.",
    )
    whatsapp_phone_number_id:  Optional[str] = Field(
        default=None,
        description="ID del número de WhatsApp Business en la consola de Meta. "
                    "Meta for Developers → App → WhatsApp → API Setup → Phone Number ID.",
    )
    google_sheets_id:          Optional[str] = Field(
        default=None,
        description="ID del Spreadsheet de huéspedes. "
                    "Está en la URL: docs.google.com/spreadsheets/d/{ID}/edit",
    )
    google_drive_file_id:      Optional[str] = Field(
        default=None,
        description="ID del PDF de reglas del hotel en Drive. "
                    "Está en: drive.google.com/file/d/{ID}/view",
    )
    precheckin_form_url:       Optional[str] = Field(
        default=None,
        description="URL del formulario de pre-check-in donde el huésped sube su DNI.",
    )
    activo:                    bool          = Field(default=True)

    model_config = {"from_attributes": True}


class RecepcionistaConfigRead(RecepcionistaConfigSchema):
    id:         int
    cliente_id: int
    created_at: datetime
    updated_at: datetime


class ServiciosPremiumRead(BaseModel):
    cliente_id:     int
    feedback:       Optional[FeedbackConfigRead]       = None
    recepcionista:  Optional[RecepcionistaConfigRead]  = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────


def _get_cliente_or_404(cliente_id: int, db: Session) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    return cliente


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints — Config combinada
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{cliente_id}/servicios-premium",
    response_model=ServiciosPremiumRead,
    summary="Configuración completa de servicios premium del cliente",
)
def get_servicios_premium(cliente_id: int, db: DbDep, _: SoporteAdmin) -> ServiciosPremiumRead:
    """Retorna la configuración de Feedback y Recepcionista Virtual del cliente."""
    _get_cliente_or_404(cliente_id, db)
    feedback = db.scalars(
        select(ConfigFeedbackCliente).where(ConfigFeedbackCliente.cliente_id == cliente_id)
    ).first()
    recepcionista = db.scalars(
        select(ConfigRecepcionistaCliente).where(ConfigRecepcionistaCliente.cliente_id == cliente_id)
    ).first()
    return ServiciosPremiumRead(
        cliente_id    = cliente_id,
        feedback      = FeedbackConfigRead.model_validate(feedback)      if feedback      else None,
        recepcionista = RecepcionistaConfigRead.model_validate(recepcionista) if recepcionista else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints — Feedback
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{cliente_id}/feedback-config",
    response_model=FeedbackConfigRead,
    summary="Configuración del Servicio de Feedback",
)
def get_feedback_config(cliente_id: int, db: DbDep, _: SoporteAdmin):
    _get_cliente_or_404(cliente_id, db)
    cfg = db.scalars(
        select(ConfigFeedbackCliente).where(ConfigFeedbackCliente.cliente_id == cliente_id)
    ).first()
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuración de Feedback no encontrada")
    return cfg


@router.put(
    "/{cliente_id}/feedback-config",
    response_model=FeedbackConfigRead,
    summary="Crear o actualizar configuración del Servicio de Feedback",
)
def upsert_feedback_config(
    cliente_id: int,
    payload:    FeedbackConfigSchema,
    db:         DbDep,
    _:          SoloAdmin,
):
    """Crea la configuración si no existe; la actualiza si ya existe (upsert)."""
    _get_cliente_or_404(cliente_id, db)

    if payload.tipo_negocio not in TIPOS_NEGOCIO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo_negocio debe ser uno de: {TIPOS_NEGOCIO}",
        )

    cfg = db.scalars(
        select(ConfigFeedbackCliente).where(ConfigFeedbackCliente.cliente_id == cliente_id)
    ).first()

    if cfg is None:
        cfg = ConfigFeedbackCliente(cliente_id=cliente_id)
        db.add(cfg)

    for campo, valor in payload.model_dump().items():
        setattr(cfg, campo, valor)
    cfg.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete(
    "/{cliente_id}/feedback-config",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar configuración del Servicio de Feedback",
)
def delete_feedback_config(cliente_id: int, db: DbDep, _: SoloAdmin):
    cfg = db.scalars(
        select(ConfigFeedbackCliente).where(ConfigFeedbackCliente.cliente_id == cliente_id)
    ).first()
    if cfg:
        db.delete(cfg)
        db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints — Recepcionista Virtual
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{cliente_id}/recepcionista-config",
    response_model=RecepcionistaConfigRead,
    summary="Configuración del Recepcionista Virtual Nocturno",
)
def get_recepcionista_config(cliente_id: int, db: DbDep, _: SoporteAdmin):
    _get_cliente_or_404(cliente_id, db)
    cfg = db.scalars(
        select(ConfigRecepcionistaCliente).where(ConfigRecepcionistaCliente.cliente_id == cliente_id)
    ).first()
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuración de Recepcionista no encontrada")
    return cfg


@router.put(
    "/{cliente_id}/recepcionista-config",
    response_model=RecepcionistaConfigRead,
    summary="Crear o actualizar configuración del Recepcionista Virtual",
)
def upsert_recepcionista_config(
    cliente_id: int,
    payload:    RecepcionistaConfigSchema,
    db:         DbDep,
    _:          SoloAdmin,
):
    """Crea la configuración si no existe; la actualiza si ya existe (upsert)."""
    _get_cliente_or_404(cliente_id, db)

    cfg = db.scalars(
        select(ConfigRecepcionistaCliente).where(ConfigRecepcionistaCliente.cliente_id == cliente_id)
    ).first()

    if cfg is None:
        cfg = ConfigRecepcionistaCliente(cliente_id=cliente_id)
        db.add(cfg)

    for campo, valor in payload.model_dump().items():
        setattr(cfg, campo, valor)
    cfg.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete(
    "/{cliente_id}/recepcionista-config",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar configuración del Recepcionista Virtual",
)
def delete_recepcionista_config(cliente_id: int, db: DbDep, _: SoloAdmin):
    cfg = db.scalars(
        select(ConfigRecepcionistaCliente).where(ConfigRecepcionistaCliente.cliente_id == cliente_id)
    ).first()
    if cfg:
        db.delete(cfg)
        db.commit()
