"""
Configuración del módulo Recepcionista Virtual Nocturno.

Carga y valida todas las variables de entorno requeridas usando
pydantic-settings, que lee desde el archivo .env automáticamente.

Uso:
    from virtual_receptionist.config import settings

    settings.gemini_api_key          # str
    settings.whatsapp_access_token   # str
    settings.crm_api_url             # str
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables de entorno del Recepcionista Virtual.

    Cada campo mapea directamente a una variable en .env.
    Los campos con ``default`` son opcionales en el entorno;
    los que no tienen ``default`` son obligatorios para arrancar.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",          # ignora vars de .env no declaradas aquí
        case_sensitive=False,
    )

    # ── Integración con CRM Django (dm_global) ────────────────────────────
    crm_api_url: str = Field(
        default="http://localhost:8001",
        alias="CRM_DM_GLOBAL_API_URL",
        description="URL base del CRM Django para consultas de contexto.",
    )
    crm_api_key: str = Field(
        default="",
        alias="CRM_DM_GLOBAL_API_KEY",
        description="API Key estática para endpoints protegidos del CRM.",
    )
    crm_hotel_id: str = Field(
        default="",
        alias="CRM_HOTEL_ID",
        description=(
            "ID del hotel/comercio en el CRM DM Global "
            "(ej: HOTEL-TERRAZAS-01). Usado para verificar la suscripción "
            "al Recepcionista Virtual antes de procesar cada mensaje."
        ),
    )

    # ── Google Gemini Flash ───────────────────────────────────────────────
    gemini_api_key: str = Field(
        alias="GEMINI_API_KEY",
        description="Clave de Google AI Studio para Gemini Flash.",
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Modelo de Gemini a usar. gemini-2.0-flash es el más rápido y económico.",
    )
    gemini_temperature: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Temperatura de generación. Más bajo = más predecible.",
    )
    gemini_max_tokens: int = Field(
        default=512,
        description="Máximo de tokens en cada respuesta del Recepcionista.",
    )

    # ── Google Drive ──────────────────────────────────────────────────────
    google_drive_folder_id: str = Field(
        default="",
        alias="GOOGLE_DRIVE_FOLDER_ID",
        description="ID de la carpeta de Drive con PDFs de contexto del hotel.",
    )
    google_drive_file_id: str = Field(
        default="",
        alias="GOOGLE_DRIVE_FILE_ID",
        description=(
            "ID del PDF principal de reglas del hotel en Google Drive. "
            "Obtener desde la URL del archivo: "
            "https://drive.google.com/file/d/{FILE_ID}/view"
        ),
    )
    google_service_account_file: str = Field(
        default="google-credentials.json",
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
        description="Ruta al JSON de la cuenta de servicio de Google Cloud.",
    )
    # ── Google Sheets — registro de huéspedes ─────────────────────────────
    google_sheets_id: str = Field(
        default="",
        alias="GOOGLE_SHEETS_ID",
        description=(
            "ID del Google Sheets principal de gestión de huéspedes. "
            "Obtener desde la URL: https://docs.google.com/spreadsheets/d/{SHEETS_ID}/edit"
        ),
    )
    google_sheets_tab: str = Field(
        default="Huéspedes",
        alias="GOOGLE_SHEETS_TAB",
        description="Nombre de la pestaña/hoja dentro del Spreadsheet.",
    )

    # ── WhatsApp Business Cloud API (Meta) ────────────────────────────────
    whatsapp_verify_token: str = Field(
        alias="WHATSAPP_VERIFY_TOKEN",
        description="Token secreto para verificar el webhook de Meta.",
    )
    whatsapp_access_token: str = Field(
        alias="WHATSAPP_ACCESS_TOKEN",
        description="Token de acceso permanente de la app de Meta.",
    )
    whatsapp_phone_number_id: str = Field(
        default="",
        alias="WHATSAPP_PHONE_NUMBER_ID",
        description="ID del número de teléfono de WhatsApp Business en Meta.",
    )
    whatsapp_api_version: str = Field(
        default="v21.0",
        description="Versión de la Graph API de Meta.",
    )

    # ── Pre-Check-In ──────────────────────────────────────────────────────
    precheckin_form_url: str = Field(
        default="",
        alias="PRECHECKIN_FORM_URL",
        description=(
            "URL del formulario Django donde el huésped sube su DNI/Pasaporte. "
            "Ej: https://tu-crm.com/precheckin/ "
            "Si está vacía el bot no puede enviar el link al formulario."
        ),
    )

    # ── Comportamiento del Recepcionista ──────────────────────────────────
    receptionist_business_name: str = Field(
        default="Hotel DM Global",
        alias="RECEPTIONIST_BUSINESS_NAME",
        description="Nombre del hotel/comercio que el Recepcionista representa.",
    )
    receptionist_default_lang: str = Field(
        default="es",
        alias="RECEPTIONIST_DEFAULT_LANG",
        description="Idioma por defecto para respuestas (es|en|pt|fr|de).",
    )
    receptionist_max_history: int = Field(
        default=10,
        alias="RECEPTIONIST_MAX_HISTORY",
        description="Turnos de conversación máximos recordados por sesión.",
    )
    receptionist_session_ttl_minutes: int = Field(
        default=60,
        alias="RECEPTIONIST_SESSION_TTL_MINUTES",
        description="Minutos de inactividad antes de resetear la sesión.",
    )

    # ── Propiedades derivadas ─────────────────────────────────────────────

    @property
    def whatsapp_messages_url(self) -> str:
        """URL del endpoint de envío de mensajes de WhatsApp."""
        return (
            f"https://graph.facebook.com/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )

    @property
    def drive_enabled(self) -> bool:
        """True si Google Drive está configurado."""
        return bool(self.google_drive_folder_id and self.google_service_account_file)

    @field_validator("receptionist_default_lang")
    @classmethod
    def validate_lang(cls, v: str) -> str:
        allowed = {"es", "en", "pt", "fr", "de"}
        if v not in allowed:
            raise ValueError(f"RECEPTIONIST_DEFAULT_LANG debe ser uno de {allowed}")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configuración — se instancia una sola vez al arrancar."""
    return Settings()


# Instancia global para importación directa
settings: Settings = get_settings()
