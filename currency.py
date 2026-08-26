"""
currency.py — Conversión y formato de monedas para precios del CRM DMGlobal.

Soporta ARS (moneda interna de referencia), USD, BRL y EUR. Las tasas son
de referencia (no en tiempo real) y viven en TASAS_A_ARS; para actualizarlas
alcanza con editar los valores de este diccionario. No depende de ninguna
API externa: mantiene la app sin nuevas dependencias, alineado con la
convención del proyecto de mínima infraestructura.
"""
from typing import Literal

Moneda = Literal["ARS", "USD", "BRL", "EUR"]

MONEDAS_SOPORTADAS: tuple[Moneda, ...] = ("ARS", "USD", "BRL", "EUR")

# Cuántos ARS equivale 1 unidad de cada moneda (tasas de referencia).
TASAS_A_ARS: dict[Moneda, float] = {
    "ARS": 1.0,
    "USD": 1250.0,
    "BRL": 210.0,
    "EUR": 1350.0,
}

SIMBOLOS: dict[Moneda, str] = {
    "ARS": "$",
    "USD": "US$",
    "BRL": "R$",
    "EUR": "€",
}


def convertir(monto: float, moneda_origen: Moneda, moneda_destino: Moneda) -> float:
    """Convierte un monto entre monedas usando las tasas de referencia (vía ARS)."""
    if moneda_origen == moneda_destino:
        return monto
    monto_en_ars = monto * TASAS_A_ARS[moneda_origen]
    return monto_en_ars / TASAS_A_ARS[moneda_destino]


def formatear(monto: float, moneda: Moneda) -> str:
    """Formatea un monto con el símbolo de su moneda (para logs/AuditLog, no UI)."""
    return f"{SIMBOLOS.get(moneda, moneda)} {monto:,.2f}"
