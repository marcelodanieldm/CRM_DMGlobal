# Recepcionista Virtual Nocturno — DM Global

Módulo asíncrono integrado al CRM FastAPI de DM Global que convierte WhatsApp Business en un **agente de atención 24/7** para hoteles, agencias de excursiones, servicios de traslado y alquiler de vehículos.

Opera de forma completamente autónoma durante la noche gestionando el ciclo de vida completo del huésped: desde el pre-check-in hasta el check-out, pasando por soporte, tickets e informes semanales.

---

## Índice

- [Arquitectura](#arquitectura)
- [Stack tecnológico](#stack-tecnológico)
- [Instalación](#instalación)
- [Variables de entorno](#variables-de-entorno)
- [Estructura de archivos](#estructura-de-archivos)
- [Árbol de decisión del webhook](#árbol-de-decisión-del-webhook)
- [Máquina de estados del huésped](#máquina-de-estados-del-huésped)
- [Google Sheets — Layout de columnas](#google-sheets--layout-de-columnas)
- [API Endpoints](#api-endpoints)
- [Google Apps Scripts](#google-apps-scripts)
- [Seguridad](#seguridad)

---

## Arquitectura

```
Huésped
  │  WhatsApp
  ▼
Meta Cloud API ──► POST /api/v1/recepcionista/whatsapp/webhook
                          │
                    BackgroundTask
                          │
              ┌─────────────────────────┐
              │   _procesar_mensaje()   │ ← pipeline unificado
              │                         │
              │  Filtro 0: Idioma       │─► Google Sheets (col I)
              │  Filtro 1: Suscripción  │─► CRM DM Global API
              │  Filtro 2: Contexto     │─► Google Sheets (col K)
              │  Filtro 3: Fase estadía │─► Gemini Flash + Drive PDF
              └─────────────────────────┘
                          │
                    WhatsApp Cloud API
                          │
                        Huésped
```

**Servicios externos consumidos:**
| Servicio | Propósito | Autenticación |
|---|---|---|
| Meta WhatsApp Cloud API | Recibir y enviar mensajes | `WHATSAPP_ACCESS_TOKEN` |
| Google Gemini Flash | Generar respuestas IA | `GEMINI_API_KEY` |
| Google Sheets API v4 | Estado del huésped | Service Account JSON |
| Google Drive API v3 | PDF de reglas del hotel | Service Account JSON |
| CRM DM Global (FastAPI interno) | Validar suscripción | `CRM_DM_GLOBAL_API_KEY` |

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Framework | FastAPI (async), Python 3.11+ |
| IA | Google Gemini Flash (`google-genai>=1.0.0`) |
| PDF | `pypdf>=4.0.0` (local, sin costo) |
| HTTP | `httpx` async (Meta API, CRM) |
| Config | `pydantic-settings>=2.0.0` |
| Autenticación Google | `google-auth>=2.0.0` (service account) |

---

## Instalación

```bash
# Dentro del proyecto CRM DMGlobal FastAPI
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con las claves reales

# Copiar credenciales de Google Cloud
cp /ruta/a/tu/service-account.json google-credentials.json
```

El módulo se monta automáticamente al arrancar FastAPI vía `main.py`:
```python
from virtual_receptionist.routers.whatsapp import router as whatsapp_router
app.include_router(whatsapp_router)
```

---

## Variables de entorno

Todas se definen en `.env` (ver `.env.example` para el template completo):

```env
# CRM interno
CRM_DM_GLOBAL_API_URL=http://localhost:8001
CRM_DM_GLOBAL_API_KEY=
CRM_HOTEL_ID=HOTEL-NOMBRE-01

# Gemini Flash
GEMINI_API_KEY=

# Google Drive (PDF de reglas del hotel)
GOOGLE_DRIVE_FILE_ID=         # ID del PDF principal
GOOGLE_SERVICE_ACCOUNT_FILE=google-credentials.json

# Google Sheets (estado de huéspedes)
GOOGLE_SHEETS_ID=
GOOGLE_SHEETS_TAB=Huéspedes

# WhatsApp Business (Meta)
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=

# Pre-check-in
PRECHECKIN_FORM_URL=https://tu-crm.com/precheckin/

# Comportamiento
RECEPTIONIST_BUSINESS_NAME=Hotel DM Global
RECEPTIONIST_DEFAULT_LANG=es
RECEPTIONIST_MAX_HISTORY=10
RECEPTIONIST_SESSION_TTL_MINUTES=60
```

---

## Estructura de archivos

```
virtual_receptionist/
│
├── config.py                   ← Settings (pydantic-settings, .env)
│
├── routers/
│   └── whatsapp.py             ← Endpoints GET/POST /webhook + pipeline unificado
│
└── services/
    ├── ai_service.py           ← Gemini Flash: generate_response, clasificar_ticket
    ├── crm_service.py          ← CRM DM Global: check_subscription, obtener_contexto
    ├── drive_service.py        ← Google Drive: get_hotel_rules (PDF → texto, caché 1h)
    ├── sheets_service.py       ← Google Sheets: get/update estado del huésped
    └── whatsapp_service.py     ← Constructores de mensajes y envíos a Meta API
```

---

## Árbol de decisión del webhook

El endpoint `POST /webhook` siempre retorna **HTTP 200 inmediatamente** a Meta, y el procesamiento real corre en `BackgroundTask`:

```
_procesar_mensaje(numero_wa, texto, phone_number_id, button_id)
│
├─ get_guest_state(numero_wa)          → Google Sheets
│    └─ None → _flujo_ia_general()
│
├─ FILTRO 0: Idioma
│    ├─ idioma vacío → enviar_menu_idioma()         ← lista interactiva es/en/pt
│    └─ botón lang_es/en/pt → update_guest_idioma() + bienvenida
│
├─ FILTRO 1: Suscripción
│    └─ check_subscription(hotel_id)   → CRM DM Global
│         └─ False → return silencioso
│
├─ FILTRO 2: Contexto temporal (col K del Sheets)
│    ├─ AWAITING_DNI      → reiterar link formulario pre-check-in
│    ├─ AWAITING_TICKET   → clasificar_ticket() → Sheets + confirmación
│    └─ AWAITING_LATE_CHECKOUT_CONFIRM → sí/no → registrar o cancelar
│
└─ FILTRO 3: Fase de estadía (col J del Sheets)
     ├─ RESERVADO
     │    ├─ pre_ci=False → AWAITING_DNI + link formulario
     │    ├─ intención llegada → PIN + Drive link → CHECKED_IN
     │    └─ otra consulta → IA genérica
     │
     ├─ CHECKED_IN
     │    ├─ botón menú → WiFi | Amenities | Incidente | Consulta IA
     │    └─ texto libre
     │         ├─ checkout detectado → instrucciones PDF + CHECKED_OUT
     │         ├─ late checkout → política PDF + AWAITING_LATE_CHECKOUT_CONFIRM
     │         └─ consulta general → Gemini Flash (PDF + datos huésped)
     │                                └─ [EMERGENCIA] → logging.warning ALERTA
     │
     └─ CHECKED_OUT → "Tu estadía ha finalizado. Esperamos verte pronto."
```

---

## Máquina de estados del huésped

### Estado de Estadía — columna J

```
RESERVADO ──(llegada detectada)──► CHECKED_IN ──(checkout)──► CHECKED_OUT
```

### Contexto de Chat — columna K

```
NORMAL ◄──────────────────────────────────────────────┐
  │                                                    │ (reset tras respuesta)
  ├──► AWAITING_DNI              (esperando formulario)│
  ├──► AWAITING_TICKET           (esperando descripción del problema)
  └──► AWAITING_LATE_CHECKOUT_CONFIRM  (esperando sí/no)
```

---

## Google Sheets — Layout de columnas

La pestaña principal (default: **`Huéspedes`**) tiene la siguiente estructura:

| Col | Letra | Campo | Valores posibles |
|-----|-------|-------|-----------------|
| 1 | A | Nombre Turista | Texto libre |
| 2 | B | Teléfono | Número WhatsApp internacional (clave de búsqueda) |
| 3 | C | Email | |
| 4 | D | Habitación | |
| 5 | E | Fecha Check-in | `YYYY-MM-DD` |
| 6 | F | Fecha Check-out | `YYYY-MM-DD` |
| 7 | G | Pre-CheckIn Completo | `SÍ` / `NO` |
| 8 | H | ID Carpeta Drive | ID de la carpeta con instrucciones de habitación |
| 9 | I | Idioma | `es` / `en` / `pt` |
| 10 | J | **Estado de Estadía** | `RESERVADO` / `CHECKED_IN` / `CHECKED_OUT` |
| 11 | K | **Contexto Chat** | `NORMAL` / `AWAITING_DNI` / `AWAITING_TICKET` / `AWAITING_LATE_CHECKOUT_CONFIRM` |
| 12 | L | PIN Acceso | Código de la cerradura |

### Pestaña `Tickets_Soporte` (creada automáticamente)

Se crea la primera vez que se registra un ticket:

| Col | Campo | Descripción |
|-----|-------|-------------|
| A | Fecha | `YYYY-MM-DD` |
| B | Hora | `HH:MM` UTC |
| C | Habitación | |
| D | Teléfono | Número del huésped |
| E | Detalle | Descripción del problema/requerimiento |
| F | Tipo | `NORMAL` / `EMERGENCIA` / `LATE_CHECKOUT` |
| G | Estado | `PENDIENTE` |

---

## API Endpoints

### `GET /api/v1/recepcionista/whatsapp/webhook`

Verificación del webhook al configurar en Meta for Developers.

**Query params:**
- `hub.mode` — debe ser `subscribe`
- `hub.verify_token` — comparado con `WHATSAPP_VERIFY_TOKEN`
- `hub.challenge` — retornado como entero si el token coincide

### `POST /api/v1/recepcionista/whatsapp/webhook`

Recepción de mensajes entrantes de WhatsApp.

- Retorna **HTTP 200 siempre e inmediatamente** (Meta timeout = 15s)
- El procesamiento real corre en `BackgroundTask`
- Valida la firma `X-Hub-Signature-256` si se envía en el header

**Payload de Meta (simplificado):**
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "value": {
        "metadata": { "phone_number_id": "PHONE_ID_DEL_HOTEL" },
        "messages": [{
          "id": "wamid.xxx",
          "from": "5491187654321",
          "type": "text",
          "text": { "body": "ya llegué al hotel" }
        }]
      }
    }]
  }]
}
```

**Mensajes interactivos (selección de lista/botones):**
```json
{
  "type": "interactive",
  "interactive": {
    "type": "list_reply",
    "list_reply": { "id": "MENU_WIFI", "title": "Wi-Fi / Clave" }
  }
}
```

---

## Google Apps Scripts

> Los scripts de automatización asociados al Servicio de Feedback (planilla de
> clientes, aprobación de borrador, informes semanales, etc.) se documentan en
> el proyecto Django **`dm_global`**. Este módulo los consume a través de los
> endpoints del CRM.

---

## Seguridad

| Mecanismo | Implementación |
|---|---|
| Verificación de webhook | `hmac.compare_digest` en tiempo constante (anti timing-attack) |
| Firma de payload | Validación `X-Hub-Signature-256` HMAC-SHA256 (opcional, recomendada en prod) |
| API Key CRM | Header `Authorization: Bearer` + `X-API-Key` en todas las llamadas |
| Suscripción activa | `check_subscription()` consulta el CRM antes de procesar cada mensaje |
| Service Account | Mínimo privilegio: scope `drive.readonly` + `spreadsheets` solamente |
| Tokens WhatsApp | Solo en variables de entorno, nunca en código |
| Fail-open CRM | Si `check_subscription` falla por red → retorna `True` (el huésped no queda varado) y loggea el error |
| Fail-open IA | Si Gemini falla → retorna mensaje de fallback genérico sin revelar el error |
| Emergencias | `[EMERGENCIA]` en respuesta de IA → `logging.warning("DISPARAR ALERTA TWILIO/TELEGRAM")` + hook para notificar al dueño |

---

## Flujo de configuración inicial

```bash
# 1. Crear cuenta de servicio en Google Cloud Console
#    Habilitar: Drive API v3 + Sheets API v4
#    Descargar JSON → google-credentials.json (en raíz del proyecto)

# 2. Compartir con la cuenta de servicio:
#    - La carpeta de Drive con el PDF del hotel (lectura)
#    - El Spreadsheet de huéspedes (edición)

# 3. Configurar webhook en Meta for Developers
#    URL: https://tu-dominio.com/api/v1/recepcionista/whatsapp/webhook
#    Token de verificación: valor de WHATSAPP_VERIFY_TOKEN en .env

# 4. Registrar el número de WhatsApp Business
#    Copiar Phone Number ID → WHATSAPP_PHONE_NUMBER_ID en .env

# 5. Arrancar el servidor
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
