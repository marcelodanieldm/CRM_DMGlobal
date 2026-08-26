/**
 * monedas.js — Utilidades de moneda para el panel · DM Global
 *
 * Soporta ARS (interna), USD, BRL (Reales) y EUR. Las tasas son de
 * referencia (no en tiempo real) — deben coincidir con currency.py del
 * backend. Para actualizarlas alcanza con editar TASAS_A_ARS.
 *
 * Cargar DESPUÉS de config.js y ANTES de cualquier script que use MONEDA.*
 */

const MONEDA = Object.freeze({

  // Código → { etiqueta, símbolo, locale para Intl.NumberFormat }
  INFO: {
    ARS: { etiqueta: 'Pesos (ARS)',  simbolo: '$',   locale: 'es-AR' },
    USD: { etiqueta: 'Dólares (USD)', simbolo: 'US$', locale: 'en-US' },
    BRL: { etiqueta: 'Reales (BRL)',  simbolo: 'R$',  locale: 'pt-BR' },
    EUR: { etiqueta: 'Euros (EUR)',   simbolo: '€',   locale: 'de-DE' },
  },

  // Cuántos ARS equivale 1 unidad de cada moneda (tasa de referencia).
  TASA_A_ARS: { ARS: 1, USD: 1250, BRL: 210, EUR: 1350 },

  /** Convierte un monto de una moneda a otra usando las tasas de referencia. */
  convertir(monto, monedaOrigen, monedaDestino) {
    if (monedaOrigen === monedaDestino) return monto;
    const enArs = monto * this.TASA_A_ARS[monedaOrigen];
    return enArs / this.TASA_A_ARS[monedaDestino];
  },

  /** Formatea un monto con el símbolo/locale de su moneda. */
  formatear(monto, moneda = 'ARS') {
    const info = this.INFO[moneda] ?? this.INFO.ARS;
    return new Intl.NumberFormat(info.locale, {
      style: 'currency', currency: moneda, maximumFractionDigits: 0,
    }).format(monto);
  },

  /** Llena un <select> con las 4 monedas soportadas. */
  poblarSelect(selectEl, seleccionada = 'ARS') {
    selectEl.innerHTML = Object.keys(this.INFO)
      .map(cod => `<option value="${cod}">${this.INFO[cod].etiqueta}</option>`)
      .join('');
    selectEl.value = seleccionada;
  },
});
