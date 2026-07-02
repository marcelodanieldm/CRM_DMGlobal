"""
Drive Service — Recepcionista Virtual Nocturno.

Descarga el PDF de reglas/contexto del hotel desde Google Drive y extrae
su texto para inyectarlo en el system prompt de Gemini Flash.

Tecnología (sin servicios de pago):
    - google-api-python-client  →  cliente oficial de la Drive API v3
    - google-auth               →  autenticación con cuenta de servicio
    - pypdf                     →  extracción de texto local, sin OCR ni API

Caché en memoria:
    El texto extraído se guarda en un diccionario global Python por 1 hora
    (TTL configurable via _CACHE_TTL_HOURS).  Esto evita consultar Drive con
    cada mensaje de WhatsApp, que ralentizaría el bot y consumiría cuota de API.

    Clave de caché: file_id del PDF.
    Timestamp:      datetime.utcnow() (naive UTC, sin zona horaria).

Credenciales:
    Archivo JSON de cuenta de servicio en la raíz del proyecto: google-credentials.json
    Configurar la ruta alternativa con la variable GOOGLE_CREDENTIALS_PATH en .env.

Degradación graceful:
    Si Drive no está disponible o el archivo no existe, retorna "".
    El Recepcionista sigue funcionando sin contexto de PDF (modo básico).
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pypdf

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

# Ruta al JSON de la cuenta de servicio de Google Cloud.
# Por defecto busca google-credentials.json en la raíz del proyecto.
_CREDENTIALS_PATH: Path = Path(
    os.environ.get("GOOGLE_CREDENTIALS_PATH", "google-credentials.json")
)

# Alcances de acceso a Drive (solo lectura; principio de mínimo privilegio).
_SCOPES: list[str] = ["https://www.googleapis.com/auth/drive.readonly"]

# Tiempo de vida del caché: 1 hora.
_CACHE_TTL_HOURS: int = 1

# Límite de caracteres de contexto que se pasan al prompt de Gemini.
# PDFs muy largos ralentizan la inferencia y aumentan el costo de tokens.
_MAX_CHARS: int = 30_000

# ─────────────────────────────────────────────────────────────────────────────
# Caché en memoria
# ─────────────────────────────────────────────────────────────────────────────

# Estructura: { file_id: (texto_extraído, timestamp_utc) }
# Usando datetime.utcnow() para el timestamp (naive UTC, sin zona horaria).
_cache: dict[str, tuple[str, datetime]] = {}


def _esta_en_cache(file_id: str) -> bool:
    """Retorna True si el file_id tiene entrada válida (no expirada) en el caché."""
    if file_id not in _cache:
        return False
    _, timestamp = _cache[file_id]
    edad = datetime.utcnow() - timestamp
    return edad < timedelta(hours=_CACHE_TTL_HOURS)


def _leer_cache(file_id: str) -> str:
    """Retorna el texto cacheado. Asumir que _esta_en_cache fue verificado antes."""
    texto, _ = _cache[file_id]
    return texto


def _escribir_cache(file_id: str, texto: str) -> None:
    """Guarda el texto en el caché con el timestamp actual (UTC)."""
    _cache[file_id] = (texto, datetime.utcnow())


async def get_hotel_rules() -> str:
    """Alias semántico de ``get_pdf_text`` para uso en el router de WhatsApp.

    Lee el ``file_id`` del PDF de reglas del hotel desde la variable de entorno
    ``GOOGLE_DRIVE_FILE_ID`` (vía ``settings.google_drive_file_id``) y delega
    en ``get_pdf_text`` para la descarga y el caché.

    Returns:
        Texto extraído del PDF, o "" si no está configurado o falla la descarga.
    """
    from virtual_receptionist.config import settings

    file_id = settings.google_drive_file_id
    if not file_id:
        logger.warning(
            "Drive Service: GOOGLE_DRIVE_FILE_ID no configurado — "
            "el Recepcionista operará sin contexto de reglas del hotel."
        )
        return ""
    return await get_pdf_text(file_id)


def limpiar_cache(file_id: Optional[str] = None) -> None:
    """Invalida el caché.

    Args:
        file_id: Si se provee, invalida solo ese archivo.
                 Si es None, invalida todo el caché.
    """
    if file_id is not None:
        _cache.pop(file_id, None)
        logger.info("Drive Service: caché invalidado para file_id=%r.", file_id)
    else:
        _cache.clear()
        logger.info("Drive Service: caché completo invalidado.")


# ─────────────────────────────────────────────────────────────────────────────
# Función principal (asíncrona) — interfaz pública del módulo
# ─────────────────────────────────────────────────────────────────────────────


async def get_pdf_text(file_id: str) -> str:
    """Obtiene el texto de un PDF alojado en Google Drive.

    Flujo:
        1. Si el texto está en caché y no expiró → retorna inmediatamente.
        2. Si no → descarga el PDF y extrae su texto.
        3. Guarda el resultado en el caché con datetime.utcnow() como timestamp.
        4. Retorna el texto truncado a _MAX_CHARS.

    Las operaciones síncronas de google-api-python-client y pypdf se ejecutan
    en un ThreadPoolExecutor para no bloquear el event loop de FastAPI.

    Args:
        file_id: ID del archivo PDF en Google Drive.
                 Se obtiene de la URL del archivo:
                 https://drive.google.com/file/d/{FILE_ID}/view

    Returns:
        Texto extraído del PDF (máx. _MAX_CHARS caracteres), o "" si falla.
    """
    if not file_id:
        logger.warning("Drive Service: file_id vacío, retornando ''.")
        return ""

    # ── Caché hit ─────────────────────────────────────────────────────────
    if _esta_en_cache(file_id):
        texto = _leer_cache(file_id)
        _, ts = _cache[file_id]
        edad_min = int((datetime.utcnow() - ts).total_seconds() / 60)
        logger.debug(
            "Drive Service: caché hit | file_id=%r | edad=%dmin | chars=%d",
            file_id, edad_min, len(texto),
        )
        return texto

    # ── Caché miss → descargar y procesar ─────────────────────────────────
    logger.info("Drive Service: caché miss | descargando file_id=%r ...", file_id)

    loop = asyncio.get_event_loop()
    try:
        # Todo el trabajo con google-api-python-client y pypdf es síncrono.
        # Lo ejecutamos en el executor para no bloquear el event loop.
        texto = await loop.run_in_executor(
            None,
            _descargar_y_extraer_sync,  # función síncrona
            file_id,
        )

        _escribir_cache(file_id, texto)
        logger.info(
            "Drive Service: PDF procesado y cacheado | file_id=%r | chars=%d",
            file_id, len(texto),
        )
        return texto

    except FileNotFoundError as exc:
        # Credenciales no configuradas → error de setup, no de runtime
        logger.error("Drive Service: %s", exc)
        return ""

    except Exception as exc:
        logger.error(
            "Drive Service: error procesando file_id=%r | %s: %s",
            file_id, type(exc).__name__, exc,
        )
        # Si hay caché expirado, úsalo como fallback antes de retornar ""
        if file_id in _cache:
            texto_expirado, _ = _cache[file_id]
            logger.warning(
                "Drive Service: usando caché expirado como fallback | chars=%d",
                len(texto_expirado),
            )
            return texto_expirado
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Funciones síncronas internas (ejecutadas en ThreadPoolExecutor)
# ─────────────────────────────────────────────────────────────────────────────


def _descargar_y_extraer_sync(file_id: str) -> str:
    """Descarga el PDF de Drive y extrae su texto. Completamente síncrono.

    Separa la descarga y la extracción para que cada paso sea fácil de
    testear y de depurar de forma independiente.

    Args:
        file_id: ID del archivo PDF en Google Drive.

    Returns:
        Texto extraído, truncado a _MAX_CHARS.

    Raises:
        FileNotFoundError: Si google-credentials.json no existe.
        googleapiclient.errors.HttpError: Si Drive retorna un error HTTP.
        pypdf.errors.PdfReadError: Si el archivo no es un PDF válido.
    """
    service      = _build_drive_service()
    pdf_bytes    = _download_pdf_bytes(service, file_id)
    texto        = _extract_text_from_pdf(pdf_bytes)
    return texto[:_MAX_CHARS]


def _build_drive_service():
    """Construye el cliente de la Drive API v3 usando la cuenta de servicio.

    Lee las credenciales desde google-credentials.json (o la ruta configurada
    en GOOGLE_CREDENTIALS_PATH) y retorna un objeto de servicio autenticado.

    Returns:
        googleapiclient.discovery.Resource  (el cliente de Drive API v3)

    Raises:
        FileNotFoundError: Si el archivo de credenciales no existe.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if not _CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Drive Service: archivo de credenciales no encontrado en "
            f"'{_CREDENTIALS_PATH.resolve()}'. "
            "Descargarlo desde Google Cloud Console → IAM → Cuentas de servicio "
            "y guardarlo como google-credentials.json en la raíz del proyecto."
        )

    credenciales = service_account.Credentials.from_service_account_file(
        str(_CREDENTIALS_PATH),
        scopes=_SCOPES,
    )

    # cache_discovery=False evita escribir archivos de disco en producción
    service = build("drive", "v3", credentials=credenciales, cache_discovery=False)
    logger.debug("Drive Service: cliente Drive API v3 construido.")
    return service


def _download_pdf_bytes(service, file_id: str) -> bytes:
    """Descarga el contenido binario de un archivo PDF desde Google Drive.

    Usa MediaIoBaseDownload para manejar correctamente archivos grandes
    sin cargarlos completamente en memoria antes de procesarlos.

    Args:
        service: Cliente autenticado de Drive API v3.
        file_id: ID del archivo en Drive.

    Returns:
        Contenido del PDF como bytes.

    Raises:
        googleapiclient.errors.HttpError: Si Drive retorna 403 (sin acceso),
            404 (no encontrado) u otro error HTTP.
    """
    import io as _io
    from googleapiclient.http import MediaIoBaseDownload

    buffer   = _io.BytesIO()
    request  = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request, chunksize=4 * 1024 * 1024)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            logger.debug(
                "Drive Service: descargando... %d%%",
                int(status.progress() * 100),
            )

    pdf_bytes = buffer.getvalue()
    logger.debug(
        "Drive Service: descarga completa | file_id=%r | bytes=%d",
        file_id, len(pdf_bytes),
    )
    return pdf_bytes


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrae el texto de un PDF usando pypdf (sin servicios de pago ni OCR).

    pypdf opera localmente sobre el stream de bytes, sin enviar datos
    a ningún servicio externo. Funciona bien con PDFs digitales (texto
    incrustado). No hace OCR; los PDFs escaneados devolverán texto vacío.

    Args:
        pdf_bytes: Contenido del PDF como bytes.

    Returns:
        Texto extraído página a página, unido con saltos de línea.
        Cadena vacía si el PDF no contiene texto extraíble.

    Raises:
        pypdf.errors.PdfReadError: Si los bytes no corresponden a un PDF válido.
    """
    reader  = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    paginas = []

    for num, pagina in enumerate(reader.pages, start=1):
        texto_pagina = pagina.extract_text() or ""
        texto_pagina = texto_pagina.strip()
        if texto_pagina:
            paginas.append(texto_pagina)
            logger.debug("Drive Service: página %d extraída | chars=%d", num, len(texto_pagina))
        else:
            logger.debug("Drive Service: página %d sin texto (escaneado?).", num)

    texto_total = "\n\n".join(paginas)
    logger.info(
        "Drive Service: extracción completada | páginas=%d | chars_total=%d",
        len(reader.pages), len(texto_total),
    )
    return texto_total
