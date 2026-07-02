# Recepcionista Virtual — DM Global

Módulo asíncrono integrado al CRM FastAPI de DM Global que convierte WhatsApp Business en un **agente de atención 24/7** para hoteles, agencias de excursiones, servicios de traslado y alquiler de vehículos.

Gestiona de forma autónoma el ciclo de vida completo del huésped: pre-check-in → check-in → estadía (soporte, tickets, late checkout) → check-out, en cinco idiomas.

---

## Índice

- [Arquitectura](#arquitectura)
- [Stack tecnológico](#stack-tecnológico)
- [Reglas de negocio](#reglas-de-negocio)
- [Flujos principales](#flujos-principales)
- [Árbol de decisión del webhook](#árbol-de-decisión-del-webhook)
- [Máquina de estados del huésped](#máquina-de-estados-del-huésped)
- [Google Sheets — Layout de columnas](#google-sheets--layout-de-columnas)
- [API Endpoints](#api-endpoints)
- [Instalación y variables de entorno](#instalación-y-variables-de-entorno)
- [Estructura de archivos](#estructura-de-archivos)
- [Seguridad](#seguridad)

---

## Arquitectura

```
Huésped
  │  WhatsApp
  ▼
Meta Cloud API ──► POST /api/v1/recepcionista/whatsapp/webhook
                          │  HTTP 200 inmediato (< 15s)
                    BackgroundTask
                          │
              ┌─────────────────────────┐
              │   _procesar_mensaje()   │ ← pipeline unificado
              │                         │
              │  Filtro 0: Idioma       │──► Google Sheets (col I)
              │  Filtro 1: Suscripción  │──► CRM DM Global API
              │  Filtro 2: Contexto     │──► Google Sheets (col K)
              │  Filtro 3: Fase estadía │──► Gemini Flash + Drive PDF
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
| Google Sheets API v4 | Estado y datos del huésped | Service Account JSON |
| Google Drive API v3 | PDF de reglas del hotel | Service Account JSON |
| CRM DM Global (FastAPI interno) | Validar suscripción activa | `CRM_DM_GLOBAL_API_KEY` |

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Framework | FastAPI (async), Python 3.11+ |
| IA | Google Gemini Flash 1.5 (`google-genai>=1.0.0`, async nativo) |
| PDF | `pypdf>=4.0.0` (local, sin costo de API) |
| HTTP | `httpx` async (Meta API, CRM) |
| Config | `pydantic-settings>=2.0.0` |
| Autenticación Google | `google-auth>=2.0.0` (service account) |
| Scheduler | APScheduler (limpieza horaria de sesiones expiradas) |

**Parámetros de Gemini Flash:**

| Parámetro | Valor | Razón |
|---|---|---|
| Modelo | `gemini-1.5-flash` | Velocidad + costo bajo |
| Temperature | `0.3` | Respuestas factuales, no creativas |
| Max output tokens | `350` | Apropiado para mensajes WhatsApp |
| Contexto | PDF del hotel inyectado en system prompt | Solo responde con info real |

---

## Reglas de negocio

### Lo que puede hacer el Recepcionista Virtual

| Capacidad | Descripción |
|---|---|
| Pre-check-in | Detecta huéspedes sin DNI/pasaporte cargado y los dirige al formulario |
| Check-in autónomo | Detecta intención de llegada y envía PIN + habitación + link Drive |
| WiFi | Extrae contraseña del PDF del hotel y la envía |
| Amenities extras | Solicita descripción y registra ticket en Sheets |
| Reporte de incidente | Clasifica el problema (normal / emergencia) y registra ticket |
| Late checkout | Extrae política del PDF, solicita confirmación y registra ticket |
| Check-out | Envía instrucciones extraídas del PDF y actualiza estado |
| Detección de emergencias | Dos capas: keywords locales + clasificación semántica de Gemini |
| Multilenguaje | Español, inglés, portugués, francés y alemán (selección por menú interactivo) |
| Consulta general | IA con contexto del hotel para cualquier pregunta no clasificada |

### Lo que NO puede hacer

| Limitación | Motivo |
|---|---|
| Modificar o cancelar reservas | Sin integración con PMS / channel manager |
| Procesar pagos o cobrar extras | Sin pasarela de pago conectada |
| Hacer llamadas telefónicas | Solo canal WhatsApp |
| Escalar a un agente humano en tiempo real | Solo registra ticket y loggea warning |
| Responder con info no incluida en el PDF del hotel | Informa amablemente que el staff atenderá la consulta |

---

### Validación de suscripción

Antes de procesar **cualquier mensaje**, el bot valida que el hotel tiene suscripción activa:

```
check_subscription(hotel_id)  →  GET {CRM_URL}/subscriptions/{hotel_id}
```

| Resultado del CRM | Acción |
|---|---|
| `status: active` o `paid` | Procesar mensaje normalmente |
| `status` distinto (inactivo/suspendido) | Ignorar mensaje en silencio (sin respuesta al huésped) |
| `404 Not Found` (hotel no existe) | Ignorar mensaje en silencio |
| Error de red / timeout | **Fail-open:** procesar igual (el huésped no queda sin ayuda) |

> El fail-open es intencional: una caída temporal del CRM no debe dejar a los huéspedes sin atención.

---

### Idiomas soportados

El idioma del huésped se guarda en la columna I de Sheets (`es` / `en` / `pt` / `fr` / `de`).

**Selección de idioma (Filtro 0):**
1. Si la columna I está vacía → el bot envía un menú interactivo con los 5 idiomas.
2. El huésped selecciona → el idioma se guarda en Sheets y persiste durante toda la estadía.
3. Todos los mensajes posteriores del bot (menús, confirmaciones, alertas) se envían en el idioma elegido.

**Idiomas disponibles:**

| Código | Idioma | Botón en menú |
|---|---|---|
| `es` | Español | 🇦🇷 Español |
| `en` | English | 🇺🇸 English |
| `pt` | Português | 🇧🇷 Português |
| `fr` | Français | 🇫🇷 Français |
| `de` | Deutsch | 🇩🇪 Deutsch |

La IA (Gemini) responde en el idioma del contexto del huésped de forma automática, ya que el mensaje del huésped ya viene en su idioma.

---

### Gestión de emergencias

La detección corre en dos capas secuenciales:

**Capa 1 — Keywords locales (< 1 ms, sin llamada a la API):**
Palabras clave como `inundación`, `fuga gas`, `incendio`, `corte de luz`, `emergencia médica` en todos los idiomas.

**Capa 2 — Clasificación semántica de Gemini:**
Para casos ambiguos (ej. "el baño está haciendo ruido raro"), Gemini clasifica si es emergencia o incidente normal.

**Acción ante emergencia:**
1. El bot responde al huésped con instrucciones de calma y números de emergencia (911/15/17/18/110/112 según idioma).
2. Se registra un ticket con `Tipo = EMERGENCIA` en la pestaña `Tickets_Soporte` de Sheets.
3. Se emite `logging.warning("DISPARAR ALERTA TWILIO/TELEGRAM | ...")` para notificación al administrador.

> Las alertas automáticas (Twilio/Telegram) están marcadas como `TODO producción`. Actualmente solo se loggea y se registra el ticket.

---

### Flujo de Late Checkout

```
Huésped escribe intención de late checkout (en cualquier idioma)
                    │
    detectar_intencion_late_checkout(texto, idioma)
                    │ True
    Gemini extrae política de late checkout del PDF del hotel
                    │
    Bot envía política + pregunta de confirmación
    ("¿Deseas solicitarlo? Respondé sí/no")
                    │
    contexto → AWAITING_LATE_CHECKOUT_CONFIRM
                    │
         ┌──────────┴──────────┐
     sí / oui / ja        no / non / nein
         │                     │
    Registra ticket         Cancela
    LATE_CHECKOUT en        (mensaje estándar)
    Tickets_Soporte
         │
    "Solicitud enviada al administrador.
     Te confirmaremos a la brevedad."
```

---

### Gestión de sesiones IA

- Sesiones en memoria (dict global por número WhatsApp).
- TTL: `RECEPTIONIST_SESSION_TTL_MINUTES` (default: 60 minutos).
- Historial máximo: `RECEPTIONIST_MAX_HISTORY` turnos (default: 10).
- Limpieza automática: cron horario vía APScheduler.
- Las sesiones son independientes del estado en Sheets; Sheets es la fuente de verdad del ciclo de vida del huésped.

---

## Flujos principales

### Flujo 1 — Pre-check-in

```
Huésped con estado RESERVADO escribe cualquier mensaje
                    │
    ¿col G (Pre-CheckIn) == "SÍ"?
         │ NO
         ▼
    Bot envía link al formulario de pre-check-in
    contexto → AWAITING_DNI
         │
    Huésped escribe mientras tanto → bot reitera el link
         │
    Huésped completa el formulario externamente
    (actualiza col G = "SÍ" vía Google Apps Script)
         │
    Próximo mensaje: reconoce estado RESERVADO + pre_ci=True
    → Filtro 3a: esperar intención de llegada
```

### Flujo 2 — Check-in autónomo

```
Huésped con estado RESERVADO + pre_ci=True escribe
"ya llegué" / "I'm here" / "je suis arrivé" / "ich bin da" / etc.
                    │
    detectar_intencion_llegada(texto, idioma) → True
                    │
    Parallel: update col J = CHECKED_IN + update col K = NORMAL
                    │
    Bot envía:
    ✅ Bienvenido/a, {nombre}!
    🚪 Habitación: {habitacion}
    🔑 PIN de acceso: {pin}
    📍 Mapa e instrucciones: {drive_url}  ← si hay carpeta en col H
```

### Flujo 3 — Soporte durante estadía (CHECKED_IN)

Sin texto ni botón específico → bot envía menú interactivo de estadía:

| Opción | Acción |
|---|---|
| 📶 Wi-Fi | Gemini extrae contraseña del PDF → envía al huésped |
| 🛏️ Amenities | Bot solicita descripción → registra ticket NORMAL |
| 🛠️ Incidente | Bot solicita descripción → clasifica (normal/emergencia) → registra ticket |
| ❓ Consulta | Gemini con contexto PDF + datos del huésped → respuesta libre |

### Flujo 4 — Check-out

```
Huésped escribe intención de checkout (en cualquier idioma)
                    │
    Gemini extrae instrucciones de check-out del PDF
                    │
    Bot envía instrucciones completas (qué apagar, dónde dejar llave, etc.)
                    │
    update col J = CHECKED_OUT
                    │
    Bot envía mensaje de despedida + link de reseña Google (si configurado)
```

---

## Árbol de decisión del webhook

El endpoint `POST /webhook` siempre retorna **HTTP 200 inmediatamente** a Meta, y el procesamiento real corre en `BackgroundTask`:

```
_procesar_mensaje(numero_wa, texto, phone_number_id, button_id)
│
├─ get_guest_state(numero_wa)              → Google Sheets lookup por col B
│    └─ None → _flujo_ia_general()         ← huésped no en Sheets
│
├─ FILTRO 0: Idioma (col I vacía)
│    ├─ button_id in {lang_es,en,pt,fr,de} → guardar + bienvenida + menú fase
│    └─ vacío → enviar_menu_idioma()        ← lista interactiva 5 idiomas
│
├─ FILTRO 1: Suscripción
│    └─ check_subscription(hotel_id) == False → return silencioso
│
├─ FILTRO 2: Contexto temporal (col K)
│    ├─ AWAITING_DNI          → reiterar link formulario pre-check-in
│    ├─ AWAITING_TICKET + texto → clasificar_ticket() → Sheets + confirmación
│    └─ AWAITING_LATE_CHECKOUT_CONFIRM + texto → sí/no → registrar o cancelar
│
└─ FILTRO 3: Fase de estadía (col J)
     ├─ RESERVADO
     │    ├─ pre_ci=False → AWAITING_DNI + link formulario
     │    ├─ intención llegada detectada → PIN + Drive → CHECKED_IN
     │    └─ consulta genérica → IA básica
     │
     ├─ CHECKED_IN
     │    ├─ botón menú → WiFi | Amenities | Incidente | Consulta IA
     │    └─ texto libre
     │         ├─ checkout detectado → instrucciones PDF + CHECKED_OUT
     │         ├─ late checkout detectado → política PDF + confirmación
     │         └─ consulta general → Gemini (PDF del hotel + datos del huésped)
     │                                └─ [EMERGENCIA] → ticket + logging.warning
     │
     └─ CHECKED_OUT → mensaje de despedida + link de reseña
```

---

## Máquina de estados del huésped

### Estado de Estadía — columna J

```
RESERVADO ──(llegada detectada)──► CHECKED_IN ──(checkout)──► CHECKED_OUT
```

Unidireccional. Ninguna transición va hacia atrás.

### Contexto de Chat — columna K

```
NORMAL ◄─────────────────────────────────────────────────────┐
  │                                                           │ (reset tras procesar)
  ├──► AWAITING_DNI                  (esperando formulario pre-check-in)
  ├──► AWAITING_TICKET               (esperando descripción del problema)
  └──► AWAITING_LATE_CHECKOUT_CONFIRM (esperando sí/no del huésped)
```

El contexto se resetea a `NORMAL` automáticamente después de procesar la respuesta del huésped.

---

## Google Sheets — Layout de columnas

La pestaña principal (default: **`Huéspedes`**) tiene la siguiente estructura:

| Col | Letra | Campo | Valores posibles |
|-----|-------|-------|-----------------|
| 1 | A | Nombre Turista | Texto libre |
| 2 | B | Teléfono | Número WhatsApp internacional — **clave de búsqueda** |
| 3 | C | Email | |
| 4 | D | Habitación | |
| 5 | E | Fecha Check-in | `YYYY-MM-DD` |
| 6 | F | Fecha Check-out | `YYYY-MM-DD` |
| 7 | G | Pre-CheckIn Completo | `SÍ` / `NO` |
| 8 | H | ID Carpeta Drive | ID de la carpeta con instrucciones de habitación |
| 9 | I | Idioma | `es` / `en` / `pt` / `fr` / `de` |
| 10 | J | **Estado de Estadía** | `RESERVADO` / `CHECKED_IN` / `CHECKED_OUT` |
| 11 | K | **Contexto Chat** | `NORMAL` / `AWAITING_DNI` / `AWAITING_TICKET` / `AWAITING_LATE_CHECKOUT_CONFIRM` |
| 12 | L | PIN Acceso | Código de la cerradura |

> La columna B (teléfono) es la clave primaria de búsqueda. Debe contener el número WhatsApp en formato internacional sin el `+` (ej. `5491187654321`).

### Pestaña `Tickets_Soporte` (creada automáticamente)

Se crea la primera vez que se registra un ticket:

| Col | Campo | Valores |
|-----|-------|---------|
| A | Fecha | `YYYY-MM-DD` |
| B | Hora | `HH:MM` UTC |
| C | Habitación | Del col D del huésped |
| D | Teléfono | Número WhatsApp del huésped |
| E | Detalle | Descripción en texto libre |
| F | Tipo | `NORMAL` / `EMERGENCIA` / `LATE_CHECKOUT` |
| G | Estado | `PENDIENTE` (siempre — el staff lo actualiza manualmente) |

---

## API Endpoints

### `GET /api/v1/recepcionista/whatsapp/webhook`

Verificación del webhook al configurar en Meta for Developers.

**Query params:**
- `hub.mode` — debe ser `subscribe`
- `hub.verify_token` — comparado con `WHATSAPP_VERIFY_TOKEN` via `hmac.compare_digest`
- `hub.challenge` — retornado como entero si el token coincide

### `POST /api/v1/recepcionista/whatsapp/webhook`

Recepción de mensajes entrantes de WhatsApp.

- Retorna **HTTP 200 siempre e inmediatamente** (Meta timeout = 15 s)
- El procesamiento real corre en `BackgroundTask` asíncrono
- Valida la firma `X-Hub-Signature-256` si está presente en el header

**Tipos de mensaje procesados:**
- `text` — mensaje de texto libre
- `interactive` (list_reply / button_reply) — selección de menú

**Tipos ignorados:**
- Imágenes, audio, video, stickers, actualizaciones de estado

---

## Instalación y variables de entorno

```bash
pip install -r requirements.txt
cp .env.example .env
cp /ruta/service-account.json google-credentials.json
```

```env
# CRM interno
CRM_DM_GLOBAL_API_URL=http://localhost:8001
CRM_DM_GLOBAL_API_KEY=
CRM_HOTEL_ID=HOTEL-NOMBRE-01

# Gemini
GEMINI_API_KEY=

# Google Drive (PDF de reglas del hotel)
GOOGLE_DRIVE_FILE_ID=
GOOGLE_SERVICE_ACCOUNT_FILE=google-credentials.json

# Google Sheets (estado de huéspedes)
GOOGLE_SHEETS_ID=
GOOGLE_SHEETS_TAB=Huéspedes

# WhatsApp Business (Meta)
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=

# Formulario pre-check-in
PRECHECKIN_FORM_URL=https://tu-crm.com/precheckin/

# Comportamiento
RECEPTIONIST_BUSINESS_NAME=Hotel DM Global
RECEPTIONIST_DEFAULT_LANG=es          # es | en | pt | fr | de
RECEPTIONIST_MAX_HISTORY=10
RECEPTIONIST_SESSION_TTL_MINUTES=60
```

### Configuración inicial de Google Cloud

```bash
# 1. Crear cuenta de servicio en Google Cloud Console
#    Habilitar: Drive API v3 + Sheets API v4
#    Descargar JSON → google-credentials.json

# 2. Compartir con la cuenta de servicio:
#    - Carpeta Drive con el PDF del hotel (lectura)
#    - Spreadsheet de huéspedes (edición)

# 3. Configurar webhook en Meta for Developers
#    URL: https://tu-dominio.com/api/v1/recepcionista/whatsapp/webhook
#    Token de verificación: valor de WHATSAPP_VERIFY_TOKEN

# 4. Copiar Phone Number ID → WHATSAPP_PHONE_NUMBER_ID
```

---

## Estructura de archivos

```
virtual_receptionist/
│
├── config.py                   ← Settings (pydantic-settings, .env)
│
├── routers/
│   └── whatsapp.py             ← Endpoints GET/POST /webhook + pipeline completo
│                                  (detección de intenciones, constructores de mensajes)
│
└── services/
    ├── ai_service.py           ← Gemini Flash: generate_response, clasificar_ticket, es_emergencia
    ├── crm_service.py          ← check_subscription → CRM DM Global API
    ├── drive_service.py        ← get_hotel_rules: PDF → texto, caché 1 hora
    ├── sheets_service.py       ← Estado del huésped: get/update EstadoEstadia, ContextoChat, idioma
    └── whatsapp_service.py     ← Constructores de payloads Meta API, envíos HTTP, traducciones
```

---

## Seguridad

| Mecanismo | Implementación |
|---|---|
| Verificación de webhook Meta | `hmac.compare_digest` en tiempo constante (anti timing-attack) |
| Firma de payload | `X-Hub-Signature-256` HMAC-SHA256 (opcional, recomendada en prod) |
| Suscripción activa | `check_subscription()` en cada mensaje antes de procesar |
| Fail-open en CRM | Red caída → procesar igual; 404 → bloquear |
| Service Account Google | Mínimo privilegio: `drive.readonly` + `spreadsheets` |
| Tokens WhatsApp y Gemini | Solo en variables de entorno, nunca en código |
| Fail-open en IA | Gemini falla → fallback genérico sin exponer el error al huésped |
| Emergencias | `[EMERGENCIA]` en respuesta → ticket EMERGENCIA + `logging.warning` (alertas Twilio/Telegram: TODO producción) |
