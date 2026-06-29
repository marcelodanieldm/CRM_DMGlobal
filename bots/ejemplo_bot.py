"""
ejemplo_bot.py — Tres patrones de integración del guardia de acceso.

Copiar y adaptar al inicio de cada bot existente.
Las variables de entorno se cargan desde un archivo .env local.

Requerimientos:
    pip install requests python-dotenv playwright
    playwright install chromium
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Cargar .env ANTES de importar bot_guard (lee env vars al importarse)
load_dotenv()

from bot_guard import (
    abortar_si_no_autorizado,
    requiere_suscripcion_activa,
    validar_acceso,
    verificar_licencia_dm_global,
)

# ---------------------------------------------------------------------------
# Logging del bot
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dmglobal.bot")

# ---------------------------------------------------------------------------
# Configuración del bot (leer desde .env o variables del sistema)
# ---------------------------------------------------------------------------

CUIT_CLIENTE: str = os.environ["CUIT_CLIENTE"]       # ej: "20123456789"
NOMBRE_SERVICIO: str = "Monitoreo Web"                # debe coincidir exactamente con el CRM
BOT_ID: str = "bot-monitoreo-web-01"


# ===========================================================================
# PATRÓN 0 — verificar_licencia_dm_global (integración mínima, una línea)
# La forma más simple de proteger un bot existente. Copia esta línea al inicio
# de cualquier script y listo: si no está autorizado, el proceso se detiene
# con sys.exit(0) antes de tocar navegadores, proxies o cualquier otro recurso.
# ===========================================================================

def ejecutar_bot_minimo() -> None:
    verificar_licencia_dm_global(CUIT_CLIENTE, NOMBRE_SERVICIO)

    # A partir de aquí el acceso está garantizado — el resto del bot sin cambios
    logger.info("[Patrón 0] Bot en ejecución...")

    # from playwright.sync_api import sync_playwright
    # with sync_playwright() as p:
    #     browser = p.chromium.launch(proxy={"server": "http://proxy:8080"})
    #     page = browser.new_page()
    #     page.goto("https://objetivo.com")
    #     browser.close()


# ===========================================================================
# PATRÓN A — Decorador
# El más limpio. Recomendado cuando el bot tiene un único punto de entrada.
# El guardia corre antes del cuerpo de la función; si falla, sys.exit(1).
# ===========================================================================

@requiere_suscripcion_activa(
    cuit=CUIT_CLIENTE,
    nombre_servicio=NOMBRE_SERVICIO,
    bot_id=BOT_ID,
)
def ejecutar_patron_a() -> None:
    """El decorador ya validó la suscripción — aquí abrimos recursos."""
    logger.info("[Patrón A] Iniciando navegador y proxies...")

    # Ejemplo con Playwright (sync API):
    # from playwright.sync_api import sync_playwright
    # with sync_playwright() as p:
    #     browser = p.chromium.launch(proxy={"server": "http://proxy:8080"})
    #     page = browser.new_page()
    #     page.goto("https://objetivo.com")
    #     contenido = page.content()
    #     browser.close()

    logger.info("[Patrón A] Bot finalizado correctamente.")


# ===========================================================================
# PATRÓN B — Guardia imperativo
# Útil cuando se necesita acceder al motivo de denegación antes de abortar,
# o cuando el flujo del bot es condicional (multi-cliente en un mismo script).
# ===========================================================================

def ejecutar_patron_b() -> None:
    # --- Validación explícita antes de abrir cualquier recurso ---
    autorizado, motivo = validar_acceso(cuit=CUIT_CLIENTE, nombre_servicio=NOMBRE_SERVICIO)

    if not autorizado:
        logger.warning(
            "[Patrón B] Suscripción inactiva o no encontrada | motivo=%s — saliendo.",
            motivo or "desconocido",
        )
        sys.exit(1)

    # --- A partir de aquí la suscripción está confirmada ---
    logger.info("[Patrón B] Acceso confirmado. Iniciando scraping...")

    # Ejemplo con Selenium:
    # from selenium import webdriver
    # options = webdriver.ChromeOptions()
    # options.add_argument("--proxy-server=http://proxy:8080")
    # driver = webdriver.Chrome(options=options)
    # driver.get("https://objetivo.com")
    # driver.quit()

    logger.info("[Patrón B] Bot finalizado correctamente.")


# ===========================================================================
# PATRÓN C — Decorador async
# Para bots que usan asyncio + Playwright async API u otras librerías async.
# ===========================================================================

@requiere_suscripcion_activa(
    cuit=CUIT_CLIENTE,
    nombre_servicio=NOMBRE_SERVICIO,
    bot_id=f"{BOT_ID}-async",
)
async def ejecutar_patron_c() -> None:
    """Variante async: el decorador detecta la corrutina y la envuelve correctamente."""
    logger.info("[Patrón C] Bot async iniciado...")

    # Ejemplo con Playwright async API:
    # from playwright.async_api import async_playwright
    # async with async_playwright() as p:
    #     browser = await p.chromium.launch()
    #     page = await browser.new_page()
    #     await page.goto("https://objetivo.com")
    #     await browser.close()

    logger.info("[Patrón C] Bot async finalizado correctamente.")


# ===========================================================================
# PATRÓN D — Multi-cliente en un loop
# Un mismo script corre para varios clientes; valida cada uno por separado.
# Usa abortar_si_no_autorizado() para el cliente activo o continúa si omite.
# ===========================================================================

CLIENTES: list[dict] = [
    {"cuit": "20123456789", "servicio": "Monitoreo Web"},
    {"cuit": "27987654321", "servicio": "Scraping de Precios"},
    {"cuit": "30111222333", "servicio": "Monitoreo Web"},
]


def ejecutar_patron_d() -> None:
    for cliente in CLIENTES:
        cuit = cliente["cuit"]
        servicio = cliente["servicio"]

        autorizado, motivo = validar_acceso(cuit=cuit, nombre_servicio=servicio)

        if not autorizado:
            logger.warning(
                "[Patrón D] Saltando cliente | cuit=%s servicio=%s motivo=%s",
                cuit, servicio, motivo or "inactivo",
            )
            continue  # en multi-cliente se puede continuar con el siguiente

        logger.info("[Patrón D] Procesando | cuit=%s servicio=%s", cuit, servicio)
        # ... lógica de scraping para este cliente ...


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bot de scraping DM Global")
    parser.add_argument(
        "--patron",
        choices=["a", "b", "c", "d"],
        default="a",
        help="Patrón de integración a ejecutar (default: a)",
    )
    args = parser.parse_args()

    patrones = {
        "a": ejecutar_patron_a,
        "b": ejecutar_patron_b,
        "c": lambda: asyncio.run(ejecutar_patron_c()),
        "d": ejecutar_patron_d,
    }
    patrones[args.patron]()
