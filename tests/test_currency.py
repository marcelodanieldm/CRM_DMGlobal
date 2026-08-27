"""
Tests unitarios de currency.py — conversión y formato de monedas.
"""
import pytest

import currency


class TestConvertir:
    def test_misma_moneda_devuelve_el_mismo_monto(self):
        assert currency.convertir(1000, "ARS", "ARS") == 1000

    def test_usd_a_ars_usa_la_tasa_configurada(self):
        resultado = currency.convertir(10, "USD", "ARS")

        assert resultado == 10 * currency.TASAS_A_ARS["USD"]

    def test_ars_a_usd_es_la_inversa_de_usd_a_ars(self):
        monto_original = 1250.0

        en_usd = currency.convertir(monto_original, "ARS", "USD")
        de_vuelta_ars = currency.convertir(en_usd, "USD", "ARS")

        assert de_vuelta_ars == pytest.approx(monto_original)

    def test_conversion_cruzada_brl_a_eur(self):
        resultado = currency.convertir(100, "BRL", "EUR")

        esperado = (100 * currency.TASAS_A_ARS["BRL"]) / currency.TASAS_A_ARS["EUR"]
        assert resultado == pytest.approx(esperado)

    def test_monto_cero_devuelve_cero(self):
        assert currency.convertir(0, "USD", "EUR") == 0


class TestFormatear:
    def test_formatea_ars_con_simbolo_pesos(self):
        assert currency.formatear(1234.5, "ARS") == "$ 1,234.50"

    def test_formatea_usd_con_simbolo_dolar(self):
        assert currency.formatear(99, "USD") == "US$ 99.00"

    def test_formatea_moneda_desconocida_usa_el_codigo_como_simbolo(self):
        assert currency.formatear(10, "XYZ") == "XYZ 10.00"
