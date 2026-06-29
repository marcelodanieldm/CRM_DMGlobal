import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, field_validator

# ---------------------------------------------------------------------------
# Tipos literales alineados con los Enum de models.py
# ---------------------------------------------------------------------------

EstadoGeneral = Literal["activo", "inactivo"]
TipoEjecucion = Literal["mensual", "por_ejecucion", "anual"]
TipoServicio = Literal["automatizacion", "bot", "scraping", "servicio_comun"]

_CUIT_RE = re.compile(r"^\d{10,11}$")


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


class ClienteBase(BaseModel):
    razon_social: str
    cuit_cuil: str
    email_contacto: Optional[EmailStr] = None
    telefono: Optional[str] = None
    estado_general: EstadoGeneral = "activo"

    @field_validator("cuit_cuil")
    @classmethod
    def validar_cuit_cuil(cls, v: str) -> str:
        if not _CUIT_RE.match(v):
            raise ValueError("cuit_cuil debe contener solo dígitos (10 u 11 caracteres)")
        return v

    @field_validator("razon_social")
    @classmethod
    def validar_razon_social(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("razon_social no puede estar vacía")
        return v


class ClienteCreate(ClienteBase):
    pass


class ClienteUpdate(BaseModel):
    razon_social: Optional[str] = None
    cuit_cuil: Optional[str] = None
    email_contacto: Optional[EmailStr] = None
    telefono: Optional[str] = None
    estado_general: Optional[EstadoGeneral] = None

    @field_validator("cuit_cuil")
    @classmethod
    def validar_cuit_cuil(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _CUIT_RE.match(v):
            raise ValueError("cuit_cuil debe contener solo dígitos (10 u 11 caracteres)")
        return v

    @field_validator("razon_social")
    @classmethod
    def validar_razon_social(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("razon_social no puede estar vacía")
        return v


class ClienteRead(ClienteBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class ServicioBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio_base: float
    tipo_ejecucion: TipoEjecucion
    tipo_servicio: TipoServicio = "servicio_comun"
    activo: bool = True

    @field_validator("precio_base")
    @classmethod
    def validar_precio(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("precio_base debe ser mayor a cero")
        return v

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nombre no puede estar vacío")
        return v


class ServicioCreate(ServicioBase):
    pass


class ServicioUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    precio_base: Optional[float] = None
    tipo_ejecucion: Optional[TipoEjecucion] = None
    tipo_servicio: Optional[TipoServicio] = None
    activo: Optional[bool] = None

    @field_validator("precio_base")
    @classmethod
    def validar_precio(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("precio_base debe ser mayor a cero")
        return v

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("nombre no puede estar vacío")
        return v


class ServicioRead(ServicioBase):
    id: int

    model_config = {"from_attributes": True}
