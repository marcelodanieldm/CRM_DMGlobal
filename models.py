from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

EstadoGeneral = Enum("activo", "inactivo", name="estado_general")
TipoEjecucion = Enum("mensual", "por_ejecucion", "anual", name="tipo_ejecucion")
TipoServicio = Enum("automatizacion", "bot", "scraping", "servicio_comun", name="tipo_servicio")
EstadoSuscripcion = Enum("activa", "pausada", "desactivada", name="estado_suscripcion")
PasarelaPago = Enum("mercadopago", "stripe", "manual", name="pasarela_pago")
RolUsuario = Enum("admin", "soporte", name="rol_usuario")


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    razon_social: Mapped[str] = mapped_column(String(255), nullable=False)
    cuit_cuil: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    email_contacto: Mapped[Optional[str]] = mapped_column(String(254))
    telefono: Mapped[Optional[str]] = mapped_column(String(50))
    estado_general: Mapped[str] = mapped_column(
        EstadoGeneral, nullable=False, default="activo"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    suscripciones: Mapped[list["Suscripcion"]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan"
    )
    config_feedback: Mapped[Optional["ConfigFeedbackCliente"]] = relationship(
        "ConfigFeedbackCliente", back_populates="cliente",
        cascade="all, delete-orphan", uselist=False,
    )
    config_recepcionista: Mapped[Optional["ConfigRecepcionistaCliente"]] = relationship(
        "ConfigRecepcionistaCliente", back_populates="cliente",
        cascade="all, delete-orphan", uselist=False,
    )

    __table_args__ = (Index("ix_clientes_cuit_cuil", "cuit_cuil"),)

    def __repr__(self) -> str:
        return f"<Cliente id={self.id} razon_social={self.razon_social!r}>"


# ---------------------------------------------------------------------------
# Configuración de Servicios Premium vinculados al cliente
# ---------------------------------------------------------------------------

TipoNegocioFeedback = Enum(
    "HOTEL", "TOUR", "TRANSFER", "ALQUILER", "RESTO",
    name="tipo_negocio_feedback"
)


class ConfigFeedbackCliente(Base):
    """Configuración del Servicio de Feedback para un cliente específico.

    Se completa cuando el operador activa el add-on de Feedback para el cliente.
    El ``google_review_link`` es el único dato obligatorio para operar;
    el resto son opcionales para enriquecer la experiencia.
    """
    __tablename__ = "config_feedback_clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tipo_negocio: Mapped[str] = mapped_column(
        TipoNegocioFeedback,
        nullable=False,
        default="HOTEL",
        comment="Sector del comercio (HOTEL, TOUR, TRANSFER, ALQUILER, RESTO)",
    )
    google_review_link: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="URL directa al perfil de reseñas de Google Maps del cliente",
    )
    google_sheet_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="URL de la planilla Google Sheets asignada al cliente",
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="config_feedback")

    def __repr__(self) -> str:
        return f"<ConfigFeedback cliente_id={self.cliente_id} tipo={self.tipo_negocio}>"


class ConfigRecepcionistaCliente(Base):
    """Configuración del Recepcionista Virtual Nocturno para un cliente.

    Almacena todos los identificadores externos que el módulo ``virtual_receptionist``
    necesita para operar de forma autónoma en la planilla y WhatsApp de ese cliente.
    """
    __tablename__ = "config_recepcionista_clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    hotel_id: Mapped[Optional[str]] = mapped_column(
        String(60),
        comment="ID legible del hotel en el CRM (ej: HOTEL-TERRAZAS-01). "
                "Usado en check_subscription y como ID de licencia en la planilla.",
    )
    whatsapp_phone_number_id: Mapped[Optional[str]] = mapped_column(
        String(80),
        comment="ID del número de WhatsApp Business en Meta for Developers. "
                "Aparece en: App → WhatsApp → API Setup → Phone Number ID.",
    )
    google_sheets_id: Mapped[Optional[str]] = mapped_column(
        String(200),
        comment="ID del Spreadsheet de huéspedes en Google Sheets. "
                "Está en la URL: docs.google.com/spreadsheets/d/{ID}/edit",
    )
    google_drive_file_id: Mapped[Optional[str]] = mapped_column(
        String(200),
        comment="ID del PDF de reglas del hotel en Google Drive. "
                "Está en la URL: drive.google.com/file/d/{ID}/view",
    )
    precheckin_form_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="URL del formulario web donde el huésped sube su DNI/Pasaporte.",
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="config_recepcionista")

    def __repr__(self) -> str:
        return f"<ConfigRecepcionista cliente_id={self.cliente_id} hotel={self.hotel_id!r}>"


class Servicio(Base):
    __tablename__ = "servicios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    precio_base: Mapped[float] = mapped_column(Float, nullable=False)
    tipo_ejecucion: Mapped[str] = mapped_column(TipoEjecucion, nullable=False)
    tipo_servicio: Mapped[str] = mapped_column(
        TipoServicio, nullable=False, default="servicio_comun", server_default="servicio_comun"
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    suscripciones: Mapped[list["Suscripcion"]] = relationship(
        back_populates="servicio"
    )

    def __repr__(self) -> str:
        return f"<Servicio id={self.id} nombre={self.nombre!r}>"


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False
    )
    servicio_id: Mapped[int] = mapped_column(
        ForeignKey("servicios.id", ondelete="RESTRICT"), nullable=False
    )
    precio_acordado: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estado_suscripcion: Mapped[str] = mapped_column(
        EstadoSuscripcion, nullable=False, default="activa"
    )
    pasarela_pago: Mapped[str] = mapped_column(PasarelaPago, nullable=False)
    externa_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fecha_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    fecha_proxima_renovacion: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fecha_ultima_pausa: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cliente: Mapped["Cliente"] = relationship(back_populates="suscripciones")
    servicio: Mapped["Servicio"] = relationship(back_populates="suscripciones")
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="suscripcion", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Suscripcion id={self.id} cliente_id={self.cliente_id}"
            f" servicio_id={self.servicio_id} estado={self.estado_suscripcion!r}>"
        )


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(RolUsuario, nullable=False, default="soporte")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Usuario id={self.id} username={self.username!r} rol={self.rol!r}>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suscripcion_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suscripciones.id", ondelete="SET NULL"), nullable=True
    )
    usuario_interno: Mapped[str] = mapped_column(String(255), nullable=False)
    accion: Mapped[str] = mapped_column(String(100), nullable=False)
    detalles: Mapped[Optional[str]] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    suscripcion: Mapped[Optional["Suscripcion"]] = relationship(
        back_populates="audit_logs"
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} accion={self.accion!r}"
            f" usuario={self.usuario_interno!r}>"
        )


# ---------------------------------------------------------------------------
# Event: hereda precio_base si precio_acordado viene vacío
# ---------------------------------------------------------------------------


@event.listens_for(Suscripcion, "before_insert")
def _heredar_precio_base(mapper, connection, target: Suscripcion) -> None:
    """
    Si precio_acordado no fue proporcionado, lo toma del precio_base del Servicio.
    Requiere que target.servicio ya esté cargado en la sesión (eager load o
    asignación explícita del objeto antes del flush).
    """
    if target.precio_acordado is None and target.servicio is not None:
        target.precio_acordado = target.servicio.precio_base
