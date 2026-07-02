"""
Sheets Service — Recepcionista Virtual.

Gestiona la máquina de estados del ciclo de vida del huésped a través de
Google Sheets como backend de datos operativo.

Estructura de columnas del Spreadsheet:
    A  Nombre Turista
    B  Teléfono          ← clave de búsqueda (número WhatsApp internacional)
    C  Email
    D  Habitación / Número de reserva
    E  Fecha Check-in    (YYYY-MM-DD)
    F  Fecha Check-out   (YYYY-MM-DD)
    G  Pre-CheckIn Completo     SÍ | NO
    H  ID Carpeta Drive         ID de la carpeta con instrucciones de habitación
    I  Idioma                   es | en | pt
    J  Estado de Estadía        RESERVADO | CHECKED_IN | CHECKED_OUT
    K  Variable Temporal        NORMAL | AWAITING_LANGUAGE | AWAITING_DNI | AWAITING_TICKET
    L  PIN Acceso               Código numérico de la cerradura/puerta de la habitación

Máquina de estados:

    EstadoEstadia:
        RESERVADO → CHECKED_IN → CHECKED_OUT
        (transición lineal; nunca retrocede)

    ContextoChat:
        NORMAL  ←→  AWAITING_LANGUAGE
        NORMAL  ←→  AWAITING_DNI
        NORMAL  ←→  AWAITING_TICKET
        (transición bi-direccional; vuelve a NORMAL tras cada respuesta)

Patrón async:
    Toda operación de google-api-python-client (síncrona) se ejecuta en un
    ThreadPoolExecutor via asyncio.run_in_executor para no bloquear el event loop
    de FastAPI mientras el Recepcionista espera respuesta del servidor de Google.

Variables de entorno requeridas:
    GOOGLE_SHEETS_ID            ID del Spreadsheet
    GOOGLE_SHEETS_TAB           Nombre de la pestaña (default: Huéspedes)
    GOOGLE_SERVICE_ACCOUNT_FILE Ruta al JSON de la cuenta de servicio
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from virtual_receptionist.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Máquina de estados — Enumeraciones
# ─────────────────────────────────────────────────────────────────────────────


class EstadoEstadia(str, Enum):
    """Ciclo de vida de la estadía del huésped.

    Transición lineal: RESERVADO → CHECKED_IN → CHECKED_OUT.
    Se almacena en la columna J del Spreadsheet.
    """
    RESERVADO   = "RESERVADO"
    CHECKED_IN  = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class ContextoChat(str, Enum):
    """Estado temporal del flujo de conversación.

    Se almacena en la columna K del Spreadsheet y se resetea a NORMAL
    tras procesar cada respuesta del huésped.

    NORMAL                        → Conversación libre; el Recepcionista responde preguntas.
    AWAITING_LANGUAGE             → Se le preguntó el idioma; esperando respuesta.
    AWAITING_DNI                  → Se solicitó el número de documento para el pre-checkin.
    AWAITING_TICKET               → Se solicitó el código/número de ticket de reserva.
    AWAITING_LATE_CHECKOUT_CONFIRM → Se informó el costo del late check-out; esperando sí/no.
    """
    NORMAL                       = "NORMAL"
    AWAITING_LANGUAGE            = "AWAITING_LANGUAGE"
    AWAITING_DNI                 = "AWAITING_DNI"
    AWAITING_TICKET              = "AWAITING_TICKET"
    AWAITING_LATE_CHECKOUT_CONFIRM = "AWAITING_LATE_CHECKOUT_CONFIRM"


# Valores válidos de idioma (col I)
IDIOMAS_VALIDOS: frozenset[str] = frozenset({"es", "en", "pt", "fr", "de"})

# ─────────────────────────────────────────────────────────────────────────────
# Mapeo de columnas (índices 0-based para listas de Python)
# ─────────────────────────────────────────────────────────────────────────────

class Col:
    """Índices de columna en la hoja (0-based en listas, 1-based en la API)."""
    NOMBRE         = 0   # A
    TELEFONO       = 1   # B ← clave de búsqueda
    EMAIL          = 2   # C
    HABITACION     = 3   # D
    FECHA_CHECKIN  = 4   # E
    FECHA_CHECKOUT = 5   # F
    PRE_CHECKIN    = 6   # G → "SÍ" / "NO"
    CARPETA_DRIVE  = 7   # H → ID de la carpeta Drive con instrucciones de habitación
    IDIOMA         = 8   # I → "es" / "en" / "pt"
    ESTADO_ESTADIA = 9   # J → EstadoEstadia
    CONTEXTO_CHAT  = 10  # K → ContextoChat
    PIN_ACCESO     = 11  # L → Código PIN de la cerradura/puerta
    TOTAL_COLS     = 12  # cuántas columnas leer por fila (A:L)

    # Letras para la Sheets API
    LETRA_IDIOMA   = "I"
    LETRA_ESTADO   = "J"
    LETRA_CONTEXTO = "K"

    # Letras de columna para la API de Sheets (actualizar J y K)
    LETRA_ESTADO   = "J"
    LETRA_CONTEXTO = "K"


# ─────────────────────────────────────────────────────────────────────────────
# Modelo de datos del huésped
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EstadoHuesped:
    """Estado completo del huésped extraído del Spreadsheet.

    Returned by get_guest_state().
    """
    # Datos de identidad
    numero_telefono:       str
    nombre:                str              = ""
    email:                 str              = ""
    habitacion:            str              = ""

    # Fechas de estadía
    fecha_checkin:         str              = ""    # "YYYY-MM-DD"
    fecha_checkout:        str              = ""    # "YYYY-MM-DD"

    # Campos de la máquina de estados (col G-K)
    pre_checkin_completo:  bool             = False
    id_carpeta_drive:      str              = ""
    idioma:                str              = "es"
    estado_estadia:        EstadoEstadia    = EstadoEstadia.RESERVADO
    contexto_chat:         ContextoChat     = ContextoChat.NORMAL

    # Col L — PIN de acceso a la habitación
    pin_acceso:            str              = ""

    # Metadato interno (fila en el Spreadsheet, necesario para updates)
    _fila:                 int              = field(default=0, repr=False)

    def to_dict(self) -> dict:
        """Retorna todos los campos como diccionario serializable (sin _fila)."""
        return {
            "numero_telefono":      self.numero_telefono,
            "nombre":               self.nombre,
            "email":                self.email,
            "habitacion":           self.habitacion,
            "fecha_checkin":        self.fecha_checkin,
            "fecha_checkout":       self.fecha_checkout,
            "pre_checkin_completo": self.pre_checkin_completo,
            "id_carpeta_drive":     self.id_carpeta_drive,
            "idioma":               self.idioma,
            "estado_estadia":       self.estado_estadia.value,
            "contexto_chat":        self.contexto_chat.value,
            "pin_acceso":           self.pin_acceso,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Credenciales y scopes de Google Sheets
# ─────────────────────────────────────────────────────────────────────────────

_SCOPES: list[str] = ["https://www.googleapis.com/auth/spreadsheets"]


def _build_sheets_service():
    """Crea el cliente autenticado de la Sheets API v4.

    Usa la misma cuenta de servicio que drive_service para unificar credenciales.

    Returns:
        googleapiclient.discovery.Resource  (cliente de Sheets API v4)

    Raises:
        FileNotFoundError: Si google-credentials.json no existe.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_path = Path(settings.google_service_account_file)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Sheets Service: credenciales no encontradas en '{creds_path.resolve()}'. "
            "Configurar GOOGLE_SERVICE_ACCOUNT_FILE en .env."
        )

    credenciales = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=_SCOPES
    )
    return build("sheets", "v4", credentials=credenciales, cache_discovery=False)


def _sheets_range(tab: str, col_from: str = "A", col_to: str = "L") -> str:
    """Construye un rango de Sheets API (ej: 'Huéspedes!A:L')."""
    tab_safe = tab.replace("'", "\\'")
    return f"'{tab_safe}'!{col_from}:{col_to}"


# ─────────────────────────────────────────────────────────────────────────────
# Funciones síncronas internas (se ejecutan en ThreadPoolExecutor)
# ─────────────────────────────────────────────────────────────────────────────


def _leer_todas_las_filas_sync(spreadsheet_id: str, tab: str) -> list[list[str]]:
    """Lee todas las filas de la hoja (columnas A:L).

    Corre en executor (síncrono). La fila 1 son los encabezados y se omite.
    """
    service     = _build_sheets_service()
    rango       = _sheets_range(tab)
    resultado   = (
        service.spreadsheets().values()
        .get(spreadsheetId=spreadsheet_id, range=rango)
        .execute()
    )
    filas = resultado.get("values", [])
    return filas[1:] if filas else []   # omitir fila de encabezados


def _actualizar_celda_sync(
    spreadsheet_id: str,
    tab:            str,
    fila:           int,      # 1-based (real row number in sheet, including header)
    columna_letra:  str,      # "J" o "K"
    valor:          str,
) -> None:
    """Actualiza una celda específica en el Spreadsheet.

    Args:
        fila:          Número de fila real (1-based, 1 = encabezado).
        columna_letra: Letra de la columna ("J" para Estado, "K" para Contexto).
        valor:         Valor a escribir.
    """
    service = _build_sheets_service()
    rango   = f"'{tab}'!{columna_letra}{fila}"

    service.spreadsheets().values().update(
        spreadsheetId = spreadsheet_id,
        range         = rango,
        valueInputOption = "RAW",
        body = {"values": [[valor]]},
    ).execute()

    logger.debug(
        "Sheets: celda actualizada | %s = %r | fila=%d", rango, valor, fila
    )


# ─────────────────────────────────────────────────────────────────────────────
# Parseo de una fila a EstadoHuesped
# ─────────────────────────────────────────────────────────────────────────────


def _fila_a_estado_huesped(fila: list[str], numero_fila_real: int) -> EstadoHuesped:
    """Convierte una lista de celdas en un objeto EstadoHuesped.

    Maneja filas cortas (columnas faltantes) con valores por defecto.
    Normaliza y valida cada campo para una máquina de estados segura.

    Args:
        fila:            Lista de strings, 0-based, columnas A-K.
        numero_fila_real: Número de fila real en el Sheet (1-based, incl. header).
    """

    def cel(idx: int, default: str = "") -> str:
        """Celda segura: retorna default si la columna no existe."""
        return fila[idx].strip() if len(fila) > idx else default

    # ── Datos básicos ──────────────────────────────────────────────────────
    nombre    = cel(Col.NOMBRE)
    telefono  = cel(Col.TELEFONO)
    email     = cel(Col.EMAIL)
    habitacion = cel(Col.HABITACION)
    f_ci      = cel(Col.FECHA_CHECKIN)
    f_co      = cel(Col.FECHA_CHECKOUT)

    # ── Col G: Pre-CheckIn Completo ────────────────────────────────────────
    pre_ci_raw = cel(Col.PRE_CHECKIN, "NO").upper()
    pre_checkin = pre_ci_raw in {"SÍ", "SI", "YES", "S", "TRUE", "1"}

    # ── Col H: ID Carpeta Drive ────────────────────────────────────────────
    carpeta_drive = cel(Col.CARPETA_DRIVE)

    # ── Col I: Idioma ──────────────────────────────────────────────────────
    idioma_raw = cel(Col.IDIOMA, settings.receptionist_default_lang).lower().strip()
    idioma     = idioma_raw if idioma_raw in IDIOMAS_VALIDOS else settings.receptionist_default_lang

    # ── Col J: Estado de Estadía ───────────────────────────────────────────
    estado_raw = cel(Col.ESTADO_ESTADIA, EstadoEstadia.RESERVADO.value).upper().strip()
    try:
        estado_estadia = EstadoEstadia(estado_raw)
    except ValueError:
        logger.warning(
            "Sheets: estado_estadia inválido %r para tel=%r — usando RESERVADO.",
            estado_raw, telefono,
        )
        estado_estadia = EstadoEstadia.RESERVADO

    # ── Col K: Variable Temporal de Contexto ──────────────────────────────
    ctx_raw = cel(Col.CONTEXTO_CHAT, ContextoChat.NORMAL.value).upper().strip()
    try:
        contexto_chat = ContextoChat(ctx_raw)
    except ValueError:
        logger.warning(
            "Sheets: contexto_chat inválido %r para tel=%r — usando NORMAL.",
            ctx_raw, telefono,
        )
        contexto_chat = ContextoChat.NORMAL

    # ── Col L: PIN de Acceso ────────────────────────────────────────────────
    pin_acceso = cel(Col.PIN_ACCESO)

    estado = EstadoHuesped(
        numero_telefono      = telefono,
        nombre               = nombre,
        email                = email,
        habitacion           = habitacion,
        fecha_checkin        = f_ci,
        fecha_checkout       = f_co,
        pre_checkin_completo = pre_checkin,
        id_carpeta_drive     = carpeta_drive,
        idioma               = idioma,
        estado_estadia       = estado_estadia,
        contexto_chat        = contexto_chat,
        pin_acceso           = pin_acceso,
        _fila                = numero_fila_real,
    )
    return estado


# ─────────────────────────────────────────────────────────────────────────────
# API pública asíncrona
# ─────────────────────────────────────────────────────────────────────────────


async def get_guest_state(phone_number: str) -> dict | None:
    """Busca al huésped por número de teléfono y retorna su estado completo.

    Lee todas las filas del Spreadsheet (columnas A:K), busca la fila
    cuya columna B coincida con ``phone_number`` y parsea los campos de la
    máquina de estados.

    El número de teléfono se normaliza (se eliminan espacios y '+') para
    hacer la búsqueda robusta ante distintos formatos de entrada de WhatsApp.

    Args:
        phone_number: Número de teléfono del huésped en formato internacional
                      (ej: "5491187654321" o "+54 9 11 8765-4321").

    Returns:
        Diccionario con los datos del huésped (ver ``EstadoHuesped.to_dict()``),
        o ``None`` si el huésped no fue encontrado en el Spreadsheet.

    Example::

        estado = await get_guest_state("5491187654321")
        if estado is None:
            return "Huésped no encontrado."
        if estado["estado_estadia"] == "CHECKED_IN":
            ...
        idioma = estado["idioma"]   # "es" | "en" | "pt"
    """
    spreadsheet_id = settings.google_sheets_id
    tab            = settings.google_sheets_tab

    if not spreadsheet_id:
        logger.warning("Sheets: GOOGLE_SHEETS_ID no configurado.")
        return None

    # Normalizar el número para comparación insensible a formato
    numero_normalizado = _normalizar_telefono(phone_number)

    loop = asyncio.get_event_loop()
    try:
        filas = await loop.run_in_executor(
            None,
            _leer_todas_las_filas_sync,
            spreadsheet_id,
            tab,
        )
    except FileNotFoundError as exc:
        logger.error("Sheets get_guest_state: %s", exc)
        return None
    except Exception as exc:
        logger.error(
            "Sheets get_guest_state: error leyendo Spreadsheet | %s: %s",
            type(exc).__name__, exc,
        )
        return None

    # La fila 1 del Sheet es el encabezado; los datos empiezan en fila 2.
    # _leer_todas_las_filas_sync ya omite la fila 1,
    # así que aquí el índice 0 corresponde a la fila real 2.
    for idx, fila in enumerate(filas):
        numero_fila_real = idx + 2   # +1 header + 1 por 1-indexed

        if len(fila) <= Col.TELEFONO:
            continue   # fila sin teléfono — probablemente vacía

        telefono_celda = _normalizar_telefono(fila[Col.TELEFONO])
        if telefono_celda != numero_normalizado:
            continue

        # ¡Encontrado!
        estado = _fila_a_estado_huesped(fila, numero_fila_real)
        logger.info(
            "Sheets: huésped encontrado | tel=%s | fila=%d | estado=%s | ctx=%s",
            phone_number, numero_fila_real,
            estado.estado_estadia.value, estado.contexto_chat.value,
        )
        return estado.to_dict()

    logger.info("Sheets: huésped no encontrado | tel=%s", phone_number)
    return None


async def update_guest_idioma(phone_number: str, idioma: str) -> bool:
    """Registra el idioma seleccionado por el huésped en la columna I.

    Se llama en el Filtro 0 cuando el huésped presiona un botón de idioma
    (lang_es / lang_en / lang_pt) por primera vez.

    Args:
        phone_number: Número WhatsApp del huésped.
        idioma:       Código de idioma ("es" | "en" | "pt").

    Returns:
        True si la actualización fue exitosa, False en caso contrario.
    """
    if idioma not in IDIOMAS_VALIDOS:
        logger.warning(
            "Sheets update_guest_idioma: idioma inválido %r para tel=%s.",
            idioma, phone_number,
        )
        return False

    fila = await _buscar_fila_huesped(phone_number)
    if fila is None:
        logger.warning("Sheets update_guest_idioma: huésped no encontrado | tel=%s", phone_number)
        return False

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _actualizar_celda_sync,
            settings.google_sheets_id,
            settings.google_sheets_tab,
            fila,
            Col.LETRA_IDIOMA,
            idioma,
        )
        logger.info("Sheets: idioma registrado | tel=%s | idioma=%s | fila=%d", phone_number, idioma, fila)
        return True
    except Exception as exc:
        logger.error("Sheets update_guest_idioma: error | tel=%s | %s: %s", phone_number, type(exc).__name__, exc)
        return False


async def update_stay_status(
    phone_number: str,
    status:       EstadoEstadia,
) -> bool:
    """Actualiza el Estado de Estadía del huésped en la columna J.

    Máquina de estados — transiciones válidas:
        RESERVADO  → CHECKED_IN
        CHECKED_IN → CHECKED_OUT

    (No valida la transición aquí; el caller es responsable.)

    Args:
        phone_number: Número del huésped (se busca en col B).
        status:       Nuevo estado (``EstadoEstadia.CHECKED_IN``, etc.).

    Returns:
        True si la actualización fue exitosa.
        False si el huésped no fue encontrado o hubo un error.
    """
    fila = await _buscar_fila_huesped(phone_number)
    if fila is None:
        logger.warning(
            "Sheets update_stay_status: huésped no encontrado | tel=%s", phone_number
        )
        return False

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _actualizar_celda_sync,
            settings.google_sheets_id,
            settings.google_sheets_tab,
            fila,
            Col.LETRA_ESTADO,
            status.value,
        )
        logger.info(
            "Sheets: estado_estadia actualizado | tel=%s | fila=%d | nuevo=%s",
            phone_number, fila, status.value,
        )
        return True

    except Exception as exc:
        logger.error(
            "Sheets update_stay_status: error | tel=%s | %s: %s",
            phone_number, type(exc).__name__, exc,
        )
        return False


async def update_chat_context(
    phone_number: str,
    context:      ContextoChat,
) -> bool:
    """Actualiza la Variable Temporal de Contexto del huésped en la columna K.

    Se llama antes de enviar un mensaje que espera una respuesta específica,
    y se resetea a ``ContextoChat.NORMAL`` tras procesar esa respuesta.

    Ejemplo de uso en el router:
        await update_chat_context(numero, ContextoChat.AWAITING_DNI)
        await _enviar_respuesta(phone_id, numero, "¿Me podés dar tu DNI?")
        # ... en el siguiente mensaje:
        dni = mensaje_usuario   # el huésped respondió con su DNI
        await update_chat_context(numero, ContextoChat.NORMAL)

    Args:
        phone_number: Número del huésped (se busca en col B).
        context:      Nuevo contexto (``ContextoChat.AWAITING_DNI``, etc.).

    Returns:
        True si la actualización fue exitosa, False en caso contrario.
    """
    fila = await _buscar_fila_huesped(phone_number)
    if fila is None:
        logger.warning(
            "Sheets update_chat_context: huésped no encontrado | tel=%s", phone_number
        )
        return False

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _actualizar_celda_sync,
            settings.google_sheets_id,
            settings.google_sheets_tab,
            fila,
            Col.LETRA_CONTEXTO,
            context.value,
        )
        logger.info(
            "Sheets: contexto_chat actualizado | tel=%s | fila=%d | nuevo=%s",
            phone_number, fila, context.value,
        )
        return True

    except Exception as exc:
        logger.error(
            "Sheets update_chat_context: error | tel=%s | %s: %s",
            phone_number, type(exc).__name__, exc,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────


async def _buscar_fila_huesped(phone_number: str) -> int | None:
    """Retorna el número de fila real (1-based) del huésped, o None si no existe.

    Reutiliza la lectura completa de la hoja para encontrar la fila
    por número de teléfono. En producción se puede optimizar con una
    caché TTL corta si hay muchas actualizaciones concurrentes.
    """
    spreadsheet_id = settings.google_sheets_id
    if not spreadsheet_id:
        return None

    numero_norm = _normalizar_telefono(phone_number)
    loop = asyncio.get_event_loop()

    try:
        filas = await loop.run_in_executor(
            None,
            _leer_todas_las_filas_sync,
            spreadsheet_id,
            settings.google_sheets_tab,
        )
    except Exception as exc:
        logger.error("Sheets _buscar_fila_huesped: %s: %s", type(exc).__name__, exc)
        return None

    for idx, fila in enumerate(filas):
        if len(fila) <= Col.TELEFONO:
            continue
        if _normalizar_telefono(fila[Col.TELEFONO]) == numero_norm:
            return idx + 2   # +1 encabezado + 1 por 1-indexed

    return None



# ─────────────────────────────────────────────────────────────────────────────
# Sistema de tickets — pestaña Tickets_Soporte
# ─────────────────────────────────────────────────────────────────────────────

_TAB_TICKETS     = "Tickets_Soporte"
_ENCABEZADOS_TICKETS = ["Fecha", "Hora", "Habitación", "Teléfono", "Detalle", "Tipo", "Estado"]
_ESTADO_TICKET_INICIAL = "PENDIENTE"


def _append_fila_sync(spreadsheet_id: str, tab: str, valores: list[str]) -> None:
    """Agrega una fila al final de la pestaña indicada.

    Crea la pestaña y los encabezados si no existen aún.  Corre en executor
    (síncrono); llamar siempre desde run_in_executor.
    """
    service = _build_sheets_service()
    rango   = f"'{tab}'!A:G"

    # Verificar si la pestaña existe; si no, crearla con encabezados
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    nombres_pestanas = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

    if tab not in nombres_pestanas:
        # Crear la pestaña nueva
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        ).execute()
        # Escribir encabezados
        service.spreadsheets().values().update(
            spreadsheetId    = spreadsheet_id,
            range            = f"'{tab}'!A1",
            valueInputOption = "RAW",
            body             = {"values": [_ENCABEZADOS_TICKETS]},
        ).execute()
        logger.info("Sheets: pestaña '%s' creada con encabezados.", tab)

    # Agregar la fila de datos
    service.spreadsheets().values().append(
        spreadsheetId    = spreadsheet_id,
        range            = rango,
        valueInputOption = "USER_ENTERED",
        insertDataOption = "INSERT_ROWS",
        body             = {"values": [valores]},
    ).execute()


async def registrar_ticket(
    numero_huesped: str,
    habitacion:     str,
    detalle:        str,
    tipo:           str = "NORMAL",
) -> bool:
    """Registra un ticket de soporte en la pestaña 'Tickets_Soporte'.

    Estructura de la fila guardada (columnas A-G):
        A  Fecha         YYYY-MM-DD
        B  Hora          HH:MM (zona horaria del servidor)
        C  Habitación    ej. "205"
        D  Teléfono      número del huésped
        E  Detalle       descripción del problema/requerimiento
        F  Tipo          "NORMAL" | "EMERGENCIA"
        G  Estado        "PENDIENTE"

    Args:
        numero_huesped: Número WhatsApp del huésped (columna D).
        habitacion:     Número de habitación (columna C).
        detalle:        Descripción del problema o requerimiento.
        tipo:           "NORMAL" o "EMERGENCIA" (columna F).

    Returns:
        True si el ticket fue guardado exitosamente, False si hubo error.
    """
    from datetime import datetime, timezone

    spreadsheet_id = settings.google_sheets_id
    if not spreadsheet_id:
        logger.warning("Sheets registrar_ticket: GOOGLE_SHEETS_ID no configurado.")
        return False

    ahora  = datetime.now(timezone.utc)
    fecha  = ahora.strftime("%Y-%m-%d")
    hora   = ahora.strftime("%H:%M")

    valores = [fecha, hora, habitacion, numero_huesped, detalle, tipo, _ESTADO_TICKET_INICIAL]

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _append_fila_sync,
            spreadsheet_id,
            _TAB_TICKETS,
            valores,
        )
        logger.info(
            "Sheets: ticket registrado | hab=%s | tipo=%s | detalle=%r",
            habitacion, tipo, detalle[:60],
        )
        return True
    except Exception as exc:
        logger.error(
            "Sheets registrar_ticket: error | %s: %s",
            type(exc).__name__, exc,
        )
        return False


def _normalizar_telefono(numero: str) -> str:
    """Elimina espacios, guiones y '+' del número para comparación robusta.

    "5491187654321" == "+54 9 11 8765-4321" → True después de normalizar.
    """
    return "".join(c for c in numero if c.isdigit())
