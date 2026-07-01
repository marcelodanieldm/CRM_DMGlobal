"""
Modelos del Add-on "Servicio de Feedback".

Módulo premium, multi-tenant, que se integra al CRM DM Global. Comparte el
`Base` declarativo de models.py para que sus tablas se creen con el mismo
engine/metadata que el resto del sistema (ver setup_dev.py).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

EstadoSuscripcionFeedback = Enum(
    "ACTIVO", "INACTIVO", "DEMO", name="estado_suscripcion_feedback"
)
TipoNegocio = Enum("HOTEL", "RESTO", "TOUR", "TRANSFER", name="tipo_negocio")


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


class Organizacion(Base):
    """Tenant base del Add-on: cada organización puede tener una configuración de feedback."""

    __tablename__ = "feedback_organizaciones"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    feedback_config: Mapped[Optional["ServicioFeedbackConfig"]] = relationship(
        back_populates="organizacion",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<Organizacion id={self.id} nombre={self.nombre!r}>"

    def __str__(self) -> str:
        return self.nombre


class ServicioFeedbackConfig(Base):
    """Configuración 1:1 del Add-on de Feedback para una Organizacion."""

    __tablename__ = "feedback_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_organizaciones.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # unique=True sobre la FK es lo que vuelve la relación 1:1
    )
    estado_suscripcion: Mapped[str] = mapped_column(
        EstadoSuscripcionFeedback, nullable=False, default="DEMO"
    )
    tipo_negocio: Mapped[str] = mapped_column(TipoNegocio, nullable=False)
    google_sheet_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    google_review_link: Mapped[str] = mapped_column(String(500), nullable=False)
    # Autogenerado en el insert; no debe incluirse en ningún schema de entrada
    # de la API (Pydantic) para que quede de solo lectura a nivel aplicación.
    api_token: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Null hasta la primera sincronización real. Ningún endpoint la actualiza
    # todavía (pendiente: setearla, por ejemplo, en cada consulta exitosa de
    # /api/v1/servicio-feedback/validar/).
    ultima_sincronizacion: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="feedback_config")

    def __repr__(self) -> str:
        return (
            f"<ServicioFeedbackConfig id={self.id} organizacion_id={self.organizacion_id}"
            f" estado={self.estado_suscripcion!r} tipo_negocio={self.tipo_negocio!r}>"
        )

    def __str__(self) -> str:
        nombre_org = self.organizacion.nombre if self.organizacion else self.organizacion_id
        return f"Feedback Config — {nombre_org}"
