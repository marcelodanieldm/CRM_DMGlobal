"""
WhatsApp Service — Constructor de mensajes interactivos para el Recepcionista Virtual.

Responsabilidades:
    1. Definir los IDs de botón del menú de estadía (constantes).
    2. Construir los payloads de mensajes interactivos (lista con opciones).
    3. Proveer templates de texto multilingüe (es / en / pt) para cada opción.
    4. Enviar mensajes interactivos (list messages) a través de la Graph API de Meta.

Arquitectura:
    Este módulo NO mantiene estado de clientes HTTP (a diferencia del router).
    Cada función de envío crea su propio ``httpx.AsyncClient`` por llamada,
    igual que ``check_subscription`` en crm_service.  Esto mantiene el módulo
    independiente del ciclo de vida del router de FastAPI.

Tipos de mensajes:
    ┌─────────────────────────────────────────────────────────────────────┐
    │ List Message (tipo: "list")                                          │
    │   → Hasta 10 opciones organizadas en secciones                      │
    │   → El usuario ve un menú expandible con título y descripción        │
    │   → La respuesta llega como message.type == "interactive"           │
    │     con interactive.type == "list_reply" e interactive.list_reply.id│
    └─────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging

import httpx

from virtual_receptionist.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# IDs de botón del menú (se usan como clave en el router para routing)
# ─────────────────────────────────────────────────────────────────────────────

class BotonesIdioma:
    """Identificadores de los botones de selección de idioma (Filtro 0)."""
    ES = "lang_es"
    EN = "lang_en"
    PT = "lang_pt"

    @classmethod
    def todos(cls) -> frozenset[str]:
        return frozenset({cls.ES, cls.EN, cls.PT})

    @classmethod
    def lang_for(cls, button_id: str) -> str:
        """Retorna el código de idioma para un button_id ('lang_es' → 'es')."""
        return {cls.ES: "es", cls.EN: "en", cls.PT: "pt"}.get(button_id, "es")


class BotonesMenu:
    """Identificadores únicos de cada opción del menú de estadía.

    Deben coincidir con los ``id`` en ``_construir_payload_menu`` y con los
    casos del switch en el pipeline del router.
    """
    WIFI      = "MENU_WIFI"        # 📶 Wi-Fi / Clave
    AMENITIES = "MENU_AMENITIES"   # 🛏️ Amenities Extras
    INCIDENTE = "MENU_INCIDENTE"   # 🛠️ Reportar Incidente Técnico
    CONSULTA  = "MENU_CONSULTA"    # ❓ Otra Consulta (IA)

    @classmethod
    def todos(cls) -> frozenset[str]:
        return frozenset({cls.WIFI, cls.AMENITIES, cls.INCIDENTE, cls.CONSULTA})


# ─────────────────────────────────────────────────────────────────────────────
# Traducciones del menú y mensajes automáticos
# ─────────────────────────────────────────────────────────────────────────────

_MENU: dict[str, dict] = {
    "es": {
        "header":          "Servicios durante tu estadía 🏨",
        "body":            "¿En qué podemos ayudarte esta noche?",
        "footer":          "Recepcionista Virtual • Disponible 24hs",
        "boton_expandir":  "Ver opciones",
        "titulo_seccion":  "Servicios",
        "opciones": [
            {"id": BotonesMenu.WIFI,      "title": "📶 Wi-Fi / Clave",          "description": "Red y contraseña de internet"},
            {"id": BotonesMenu.AMENITIES, "title": "🛏️ Amenities Extras",       "description": "Toallas, almohadas, etc."},
            {"id": BotonesMenu.INCIDENTE, "title": "🛠️ Reportar Incidente",     "description": "Problema técnico en la habitación"},
            {"id": BotonesMenu.CONSULTA,  "title": "❓ Otra Consulta",           "description": "Asistente de IA disponible"},
        ],
    },
    "en": {
        "header":          "Services during your stay 🏨",
        "body":            "How can we help you tonight?",
        "footer":          "Virtual Receptionist • Available 24hs",
        "boton_expandir":  "See options",
        "titulo_seccion":  "Services",
        "opciones": [
            {"id": BotonesMenu.WIFI,      "title": "📶 Wi-Fi / Password",        "description": "Internet network and password"},
            {"id": BotonesMenu.AMENITIES, "title": "🛏️ Extra Amenities",        "description": "Towels, pillows, etc."},
            {"id": BotonesMenu.INCIDENTE, "title": "🛠️ Report Issue",            "description": "Technical problem in the room"},
            {"id": BotonesMenu.CONSULTA,  "title": "❓ Other Query",             "description": "AI assistant available"},
        ],
    },
    "pt": {
        "header":          "Serviços durante sua estadia 🏨",
        "body":            "Como podemos te ajudar esta noite?",
        "footer":          "Recepcionista Virtual • Disponível 24hs",
        "boton_expandir":  "Ver opções",
        "titulo_seccion":  "Serviços",
        "opciones": [
            {"id": BotonesMenu.WIFI,      "title": "📶 Wi-Fi / Senha",           "description": "Rede e senha da internet"},
            {"id": BotonesMenu.AMENITIES, "title": "🛏️ Amenities Extras",        "description": "Toalhas, travesseiros, etc."},
            {"id": BotonesMenu.INCIDENTE, "title": "🛠️ Reportar Problema",       "description": "Problema técnico no quarto"},
            {"id": BotonesMenu.CONSULTA,  "title": "❓ Outra Consulta",          "description": "Assistente de IA disponível"},
        ],
    },
}

# Mensaje que el bot envía ANTES de recibir el detalle del ticket (AWAITING_TICKET)
_MSG_AWAITING_TICKET: dict[str, str] = {
    "es": (
        "Entendido. 📝\n\n"
        "Por favor, detalla tu requerimiento o problema en *un solo mensaje de texto*. "
        "El sistema lo procesará de inmediato y notificará al staff."
    ),
    "en": (
        "Understood. 📝\n\n"
        "Please describe your request or issue in *a single text message*. "
        "The system will process it immediately and notify the staff."
    ),
    "pt": (
        "Entendido. 📝\n\n"
        "Por favor, descreva seu pedido ou problema em *uma única mensagem de texto*. "
        "O sistema irá processá-lo imediatamente e notificar a equipe."
    ),
}

# Confirmación enviada al huésped cuando su ticket normal fue registrado
_MSG_TICKET_REGISTRADO: dict[str, str] = {
    "es": (
        "✅ Tu reporte fue registrado correctamente.\n\n"
        "El staff fue notificado y te atenderá a la brevedad. "
        "Si es urgente, llamá a recepción."
    ),
    "en": (
        "✅ Your report was successfully registered.\n\n"
        "The staff has been notified and will attend to you shortly. "
        "If urgent, please call reception."
    ),
    "pt": (
        "✅ Seu relatório foi registrado com sucesso.\n\n"
        "A equipe foi notificada e te atenderá em breve. "
        "Se for urgente, ligue para a recepção."
    ),
}

# Respuesta inmediata cuando se detecta una emergencia en un ticket
_MSG_EMERGENCIA_TICKET: dict[str, str] = {
    "es": (
        "🚨 *EMERGENCIA DETECTADA*\n\n"
        "Estamos alertando al administrador del hotel de inmediato. "
        "Por favor, mantené la calma y seguí estas indicaciones:\n\n"
        "• Si hay riesgo inmediato, evacuá la habitación.\n"
        "• Llamá al número de emergencias del hotel o al 911.\n"
        "• Mantenete en contacto por este chat."
    ),
    "en": (
        "🚨 *EMERGENCY DETECTED*\n\n"
        "We are alerting the hotel manager immediately. "
        "Please stay calm and follow these instructions:\n\n"
        "• If there is immediate risk, evacuate the room.\n"
        "• Call the hotel's emergency number or 911.\n"
        "• Stay in contact through this chat."
    ),
    "pt": (
        "🚨 *EMERGÊNCIA DETECTADA*\n\n"
        "Estamos alertando o gerente do hotel imediatamente. "
        "Por favor, mantenha a calma e siga estas instruções:\n\n"
        "• Se houver risco imediato, evacue o quarto.\n"
        "• Ligue para o número de emergências do hotel ou 193.\n"
        "• Mantenha contato por este chat."
    ),
}


# Prompts para que la IA extraiga información específica del PDF del hotel
PROMPT_INSTRUCCIONES_CHECKOUT: dict[str, str] = {
    "es": (
        "¿Cuáles son las instrucciones completas para el check-out? "
        "Incluye: qué apagar, dónde dejar la llave o tarjeta, "
        "y cualquier instrucción especial de salida."
    ),
    "en": (
        "What are the complete check-out instructions? "
        "Include: what to turn off, where to leave the key or card, "
        "and any special departure instructions."
    ),
    "pt": (
        "Quais são as instruções completas para o check-out? "
        "Inclua: o que desligar, onde deixar a chave ou cartão, "
        "e quaisquer instruções especiais de saída."
    ),
}

PROMPT_POLITICA_LATE_CHECKOUT: dict[str, str] = {
    "es": (
        "¿Cuál es la política de late check-out del hotel? "
        "Indica: horario estándar de salida, hasta qué hora es posible el late check-out, "
        "y cuánto cuesta el late check-out adicional."
    ),
    "en": (
        "What is the hotel's late check-out policy? "
        "State: standard departure time, latest possible late check-out time, "
        "and how much extra the late check-out costs."
    ),
    "pt": (
        "Qual é a política de late check-out do hotel? "
        "Informe: horário padrão de saída, horário máximo disponível para late check-out, "
        "e qual é o custo adicional."
    ),
}

# Sufijo que se agrega a la respuesta de la IA sobre política de late checkout
_MENU_IDIOMA = {
    "header":         "🌐 Language / Idioma / Língua",
    "body":           "Please select your language to continue.\nSeleccioná tu idioma para continuar.\nSelecione seu idioma para continuar.",
    "boton_expandir": "Select / Seleccionar",
    "titulo_seccion": "Idiomas disponibles",
    "opciones": [
        {"id": BotonesIdioma.ES, "title": "🇦🇷 Español", "description": "Continuar en español"},
        {"id": BotonesIdioma.EN, "title": "🇺🇸 English", "description": "Continue in English"},
        {"id": BotonesIdioma.PT, "title": "🇧🇷 Português", "description": "Continuar em português"},
    ],
}

_BIENVENIDA_NUEVA_SESION: dict[str, str] = {
    "es": "¡Hola{nombre}! Bienvenido/a. ¿En qué puedo ayudarte?",
    "en": "Hello{nombre}! Welcome. How can I help you?",
    "pt": "Olá{nombre}! Bem-vindo/a. Como posso ajudar?",
}

_MSG_CHECKED_OUT: dict[str, str] = {
    "es": (
        "Tu estadía ha finalizado. 🙏\n\n"
        "Esperamos verte pronto de nuevo en {hotel}. "
        "¡Buen viaje!"
    ),
    "en": (
        "Your stay has ended. 🙏\n\n"
        "We hope to see you again soon at {hotel}. "
        "Safe travels!"
    ),
    "pt": (
        "Sua estadia chegou ao fim. 🙏\n\n"
        "Esperamos vê-lo novamente em breve em {hotel}. "
        "Boa viagem!"
    ),
}

_MSG_LATE_CHECKOUT_PREGUNTA: dict[str, str] = {
    "es": "\n\n¿Deseas solicitar el late check-out al administrador? Respondé *sí* para confirmar.",
    "en": "\n\nWould you like to request late check-out from the administrator? Reply *yes* to confirm.",
    "pt": "\n\nDeseja solicitar o late check-out ao administrador? Responda *sim* para confirmar.",
}

_MSG_LATE_CHECKOUT_SOLICITADO: dict[str, str] = {
    "es": (
        "✅ Tu solicitud de late check-out fue enviada al administrador del hotel.\n\n"
        "Te confirmaremos la disponibilidad a la brevedad por este mismo chat."
    ),
    "en": (
        "✅ Your late check-out request has been sent to the hotel administrator.\n\n"
        "We'll confirm availability shortly via this chat."
    ),
    "pt": (
        "✅ Sua solicitação de late check-out foi enviada ao administrador do hotel.\n\n"
        "Confirmaremos a disponibilidade em breve por este chat."
    ),
}

_MSG_LATE_CHECKOUT_CANCELADO: dict[str, str] = {
    "es": "Entendido. La salida seguirá siendo en el horario estándar. ¿Puedo ayudarte con algo más?",
    "en": "Understood. Check-out will be at the standard time. Can I help you with anything else?",
    "pt": "Entendido. A saída será no horário padrão. Posso ajudar com mais alguma coisa?",
}

_MSG_CHECKOUT_PROCESADO: dict[str, str] = {
    "es": (
        "✅ *¡Hasta pronto!* Tu check-out fue registrado exitosamente. 🙏\n\n"
        "Fue un placer tenerte con nosotros. Si tu experiencia fue positiva, "
        "nos encantaría leer tu opinión:\n{review_link}"
    ),
    "en": (
        "✅ *See you soon!* Your check-out has been processed successfully. 🙏\n\n"
        "It was a pleasure having you with us. If you enjoyed your stay, "
        "we'd love to hear from you:\n{review_link}"
    ),
    "pt": (
        "✅ *Até logo!* Seu check-out foi registrado com sucesso. 🙏\n\n"
        "Foi um prazer tê-lo conosco. Se sua experiência foi positiva, "
        "adoraríamos ler sua opinião:\n{review_link}"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Constructores de payload
# ─────────────────────────────────────────────────────────────────────────────


def construir_payload_menu(
    to:          str,
    idioma:      str,
    nombre:      str = "",
) -> dict:
    """Construye el payload JSON para un List Message de WhatsApp.

    Args:
        to:      Número del destinatario (formato internacional sin '+').
        idioma:  Código de idioma (es | en | pt). Fallback: es.
        nombre:  Nombre del huésped (para personalizar el body).

    Returns:
        Diccionario listo para enviar a la Graph API de Meta vía POST.
    """
    t   = _MENU.get(idioma, _MENU["es"])
    saludo = f" {nombre}!" if nombre else "!"

    body_personalizado = t["body"].replace(
        "¿En qué podemos ayudarte esta noche?",
        f"Hola{saludo} ¿En qué podemos ayudarte esta noche?",
    ).replace(
        "How can we help you tonight?",
        f"Hello{saludo} How can we help you tonight?",
    ).replace(
        "Como podemos te ajudar esta noite?",
        f"Olá{saludo} Como podemos te ajudar esta noite?",
    )

    return {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": t["header"]},
            "body":   {"text": body_personalizado},
            "footer": {"text": t["footer"]},
            "action": {
                "button": t["boton_expandir"],
                "sections": [{
                    "title": t["titulo_seccion"],
                    "rows":  t["opciones"],
                }],
            },
        },
    }


def construir_payload_texto(to: str, texto: str) -> dict:
    """Construye el payload para un mensaje de texto simple."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text": {"preview_url": False, "body": texto},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Funciones de envío (crean su propio cliente httpx por llamada)
# ─────────────────────────────────────────────────────────────────────────────

_TIMEOUT_WA = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


async def enviar_menu_estadia(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
    nombre:          str = "",
) -> bool:
    """Envía el menú interactivo de estadía al huésped.

    Args:
        phone_number_id: ID del número de WhatsApp Business del hotel (Meta).
        to:              Número del huésped (internacional, sin '+').
        idioma:          Código de idioma (es|en|pt).
        nombre:          Nombre del huésped para personalizar el saludo.

    Returns:
        True si Meta respondió con HTTP 200/201.
    """
    payload = construir_payload_menu(to=to, idioma=idioma, nombre=nombre)
    return await _enviar_payload(phone_number_id, payload, contexto="menu")


async def enviar_solicitud_ticket(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
) -> bool:
    """Envía el mensaje que solicita al huésped que describa su problema."""
    texto   = _MSG_AWAITING_TICKET.get(idioma, _MSG_AWAITING_TICKET["es"])
    payload = construir_payload_texto(to=to, texto=texto)
    return await _enviar_payload(phone_number_id, payload, contexto="solicitar_ticket")


async def enviar_confirmacion_ticket(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
) -> bool:
    """Confirma al huésped que su reporte normal fue registrado."""
    texto   = _MSG_TICKET_REGISTRADO.get(idioma, _MSG_TICKET_REGISTRADO["es"])
    payload = construir_payload_texto(to=to, texto=texto)
    return await _enviar_payload(phone_number_id, payload, contexto="ticket_registrado")


async def enviar_aviso_emergencia(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
) -> bool:
    """Envía instrucciones de calma ante una emergencia detectada."""
    texto   = _MSG_EMERGENCIA_TICKET.get(idioma, _MSG_EMERGENCIA_TICKET["es"])
    payload = construir_payload_texto(to=to, texto=texto)
    return await _enviar_payload(phone_number_id, payload, contexto="emergencia_ticket")


async def _enviar_payload(
    phone_number_id: str,
    payload:         dict,
    contexto:        str = "",
) -> bool:
    """Envía un payload JSON a la Graph API de Meta."""
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_number_id}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT_WA, headers=headers) as client:
        try:
            r = await client.post(url, json=payload)
            if r.is_success:
                logger.info(
                    "WhatsApp Service: enviado [%s] | to=%s | HTTP=%s",
                    contexto, payload.get("to"), r.status_code,
                )
                return True
            logger.error(
                "WhatsApp Service: error [%s] | HTTP %s | %s",
                contexto, r.status_code, r.text[:150],
            )
            return False
        except Exception as exc:
            logger.error(
                "WhatsApp Service: excepción [%s] | %s: %s",
                contexto, type(exc).__name__, exc,
            )
            return False


async def enviar_menu_idioma(phone_number_id: str, to: str) -> bool:
    """Envía el menú de selección de idioma (Filtro 0 — primer contacto)."""
    tab_safe = _MENU_IDIOMA["titulo_seccion"].replace("'", "\\'")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": _MENU_IDIOMA["header"]},
            "body":   {"text": _MENU_IDIOMA["body"]},
            "action": {
                "button":   _MENU_IDIOMA["boton_expandir"],
                "sections": [{
                    "title": _MENU_IDIOMA["titulo_seccion"],
                    "rows":  _MENU_IDIOMA["opciones"],
                }],
            },
        },
    }
    return await _enviar_payload(phone_number_id, payload, contexto="menu_idioma")


async def enviar_bienvenida(
    phone_number_id: str,
    to:              str,
    nombre:          str = "",
    idioma:          str = "es",
) -> bool:
    """Envía el saludo de bienvenida tras la selección de idioma."""
    plantilla = _BIENVENIDA_NUEVA_SESION.get(idioma, _BIENVENIDA_NUEVA_SESION["es"])
    n         = f", {nombre}" if nombre else ""
    texto     = plantilla.format(nombre=n)
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="bienvenida",
    )


async def enviar_checked_out(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
    hotel_name:      str = "",
) -> bool:
    """Mensaje de estadía finalizada para huéspedes con estado CHECKED_OUT."""
    plantilla = _MSG_CHECKED_OUT.get(idioma, _MSG_CHECKED_OUT["es"])
    texto     = plantilla.format(hotel=hotel_name or "nosotros")
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="checked_out",
    )


async def enviar_late_checkout_pregunta(
    phone_number_id: str,
    to:              str,
    respuesta_ia:    str,
    idioma:          str = "es",
) -> bool:
    """Envía la política de late checkout + pregunta de confirmación."""
    sufijo = _MSG_LATE_CHECKOUT_PREGUNTA.get(idioma, _MSG_LATE_CHECKOUT_PREGUNTA["es"])
    texto  = f"{respuesta_ia.strip()}{sufijo}"
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="late_checkout_pregunta",
    )


async def enviar_late_checkout_confirmado(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
) -> bool:
    """Confirma que la solicitud de late checkout fue enviada al hotel."""
    texto = _MSG_LATE_CHECKOUT_SOLICITADO.get(idioma, _MSG_LATE_CHECKOUT_SOLICITADO["es"])
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="late_checkout_confirmado",
    )


async def enviar_late_checkout_cancelado(
    phone_number_id: str,
    to:              str,
    idioma:          str = "es",
) -> bool:
    """Confirma que el huésped no quiere late checkout."""
    texto = _MSG_LATE_CHECKOUT_CANCELADO.get(idioma, _MSG_LATE_CHECKOUT_CANCELADO["es"])
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="late_checkout_cancelado",
    )


async def enviar_checkout_completado(
    phone_number_id: str,
    to:              str,
    instrucciones:   str,
    review_link:     str = "",
    idioma:          str = "es",
) -> bool:
    """Envía instrucciones de salida + despedida + link a Google Reviews."""
    plantilla = _MSG_CHECKOUT_PROCESADO.get(idioma, _MSG_CHECKOUT_PROCESADO["es"])
    despedida  = plantilla.format(review_link=review_link or "")
    # Combinar instrucciones de salida del PDF + despedida con review link
    texto = f"{instrucciones.strip()}\n\n{'—' * 20}\n\n{despedida}".strip()
    return await _enviar_payload(
        phone_number_id,
        construir_payload_texto(to=to, texto=texto),
        contexto="checkout_completado",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de extracción de Wi-Fi desde el PDF del hotel
# ─────────────────────────────────────────────────────────────────────────────

def construir_prompt_wifi(hotel_context: str, idioma: str) -> tuple[str, str]:
    """Construye el prompt para extraer información de Wi-Fi del PDF del hotel.

    Returns:
        (guest_message, hotel_context) listos para pasarse a generate_response.
    """
    preguntas = {
        "es": "¿Cuál es la red Wi-Fi y la contraseña del hotel?",
        "en": "What is the hotel's Wi-Fi network name and password?",
        "pt": "Qual é a rede Wi-Fi e a senha do hotel?",
    }
    pregunta = preguntas.get(idioma, preguntas["es"])
    return pregunta, hotel_context
