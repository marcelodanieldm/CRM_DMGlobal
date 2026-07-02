"""
Tests unitarios del Recepcionista Virtual Nocturno.

Cobertura:
  crm_service     check_subscription — status values, fail-open cases
  drive_service   get_pdf_text       — cache TTL, error fallback
  ai_service      generate_response  — Gemini mock, emergencia, fallback
  ai_service      clasificar_ticket  — EMERGENCIA vs NORMAL, 2 capas
  sheets_service  _fila_a_estado_huesped — parseo, defaults, normalización
  whatsapp_service payload builders  — estructura de List Messages
  _procesar_mensaje pipeline completo — 9 escenarios del árbol de decisión
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import virtual_receptionist.services.crm_service      as crm_svc
import virtual_receptionist.services.drive_service    as drv_svc
import virtual_receptionist.services.ai_service       as ai_svc
import virtual_receptionist.services.sheets_service   as sh_svc
import virtual_receptionist.services.whatsapp_service as wa_svc
import virtual_receptionist.routers.whatsapp          as wa_router
from virtual_receptionist.services.sheets_service import (
    EstadoEstadia, ContextoChat, _fila_a_estado_huesped,
)
from virtual_receptionist.services.whatsapp_service import BotonesMenu, BotonesIdioma


# ─── Helpers ─────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def huesped(**kw):
    base = dict(
        nombre="Ana Lopez", numero_telefono="5491100000001",
        habitacion="205", pin_acceso="4821", id_carpeta_drive="DriveABC",
        idioma="es", pre_checkin_completo=True,
        estado_estadia="CHECKED_IN", contexto_chat="NORMAL",
        email="a@t.com", fecha_checkin="2026-07-10", fecha_checkout="2026-07-15",
    )
    base.update(kw)
    return base


def _mock_httpx_resp(json_data: dict, status: int = 200):
    """httpx.Response falso con json() síncrono."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_data
    r.text = str(json_data)
    r.raise_for_status = MagicMock()
    r.is_success = (200 <= status < 300)
    return r


def _mock_async_client(response=None, side_effect=None):
    """Context-manager mock para httpx.AsyncClient() (per-call)."""
    mc = MagicMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__  = AsyncMock(return_value=False)
    if side_effect:
        mc.get = AsyncMock(side_effect=side_effect)
    else:
        mc.get = AsyncMock(return_value=response)
    return mc


# ─────────────────────────────────────────────────────────────────────────────
# crm_service.check_subscription
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckSubscription:
    """check_subscription usa httpx.AsyncClient() per-call — se parchea en el módulo."""

    def _call(self, json_data=None, side_effect=None):
        mc = _mock_async_client(
            response=_mock_httpx_resp(json_data or {}),
            side_effect=side_effect,
        )
        with patch("virtual_receptionist.services.crm_service.httpx.AsyncClient", return_value=mc):
            return run(crm_svc.check_subscription("HOTEL-X"))

    @pytest.mark.parametrize("status_val,expected", [
        ("active",   True),
        ("paid",     True),
        ("ACTIVE",   True),
        ("Paid",     True),
        ("inactive", False),
        ("expired",  False),
        ("",         False),
        ("trial",    False),
    ])
    def test_estado_json(self, status_val, expected):
        assert self._call({"status": status_val}) is expected

    def test_timeout_fail_open(self):
        assert self._call(side_effect=httpx.TimeoutException("t/o")) is True

    def test_connection_error_fail_open(self):
        assert self._call(side_effect=httpx.ConnectError("refused")) is True

    def test_http_404_retorna_false(self):
        r404 = _mock_httpx_resp({}, 404)
        r404.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found", request=MagicMock(), response=r404
        )
        mc = _mock_async_client(response=r404)
        with patch("virtual_receptionist.services.crm_service.httpx.AsyncClient", return_value=mc):
            assert run(crm_svc.check_subscription("HOTEL-GHOST")) is False

    def test_http_500_fail_open(self):
        r500 = _mock_httpx_resp({}, 500)
        r500.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=r500
        )
        mc = _mock_async_client(response=r500)
        with patch("virtual_receptionist.services.crm_service.httpx.AsyncClient", return_value=mc):
            assert run(crm_svc.check_subscription("HOTEL-X")) is True

    def test_url_contiene_hotel_id(self):
        mc = _mock_async_client(response=_mock_httpx_resp({"status": "active"}))
        with patch("virtual_receptionist.services.crm_service.httpx.AsyncClient", return_value=mc):
            run(crm_svc.check_subscription("HOTEL-TERRAZAS-99"))
        url = mc.get.call_args[0][0]
        assert "HOTEL-TERRAZAS-99" in url
        assert "/subscriptions/" in url


# ─────────────────────────────────────────────────────────────────────────────
# drive_service.get_pdf_text
# ─────────────────────────────────────────────────────────────────────────────

class TestDriveService:

    def setup_method(self):
        drv_svc.limpiar_cache()

    def test_cache_hit_no_llama_a_drive(self):
        drv_svc._cache["file-cached"] = ("Texto del PDF.", datetime.utcnow())
        llamadas = []
        with patch.object(drv_svc, "_descargar_y_extraer_sync",
                          side_effect=lambda fid: llamadas.append(fid) or "nuevo"):
            resultado = run(drv_svc.get_pdf_text("file-cached"))
        assert resultado == "Texto del PDF."
        assert llamadas == []

    def test_cache_miss_llama_a_drive_y_cachea(self):
        with patch.object(drv_svc, "_descargar_y_extraer_sync",
                          return_value="Reglamento del hotel."):
            resultado = run(drv_svc.get_pdf_text("file-nuevo"))
        assert resultado == "Reglamento del hotel."
        assert "file-nuevo" in drv_svc._cache

    def test_cache_expirado_recarga(self):
        ts_viejo = datetime.utcnow() - timedelta(hours=2)
        drv_svc._cache["file-exp"] = ("texto viejo", ts_viejo)
        with patch.object(drv_svc, "_descargar_y_extraer_sync", return_value="texto nuevo"):
            resultado = run(drv_svc.get_pdf_text("file-exp"))
        assert resultado == "texto nuevo"

    def test_error_con_cache_expirado_usa_fallback(self):
        ts_viejo = datetime.utcnow() - timedelta(hours=2)
        drv_svc._cache["file-err"] = ("datos de respaldo", ts_viejo)
        with patch.object(drv_svc, "_descargar_y_extraer_sync",
                          side_effect=RuntimeError("Drive caido")):
            resultado = run(drv_svc.get_pdf_text("file-err"))
        assert resultado == "datos de respaldo"

    def test_file_id_vacio_retorna_cadena_vacia(self):
        assert run(drv_svc.get_pdf_text("")) == ""

    def test_extraccion_pypdf_retorna_string(self):
        """_extraer_texto_pdf debe retornar str sin crashear."""
        import io, pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buf = io.BytesIO(); writer.write(buf)
        texto = drv_svc._extract_text_from_pdf(buf.getvalue())
        assert isinstance(texto, str)


# ─────────────────────────────────────────────────────────────────────────────
# ai_service.generate_response
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateResponse:

    def _mock_client(self, text):
        mock_resp = MagicMock(); mock_resp.text = text
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(return_value=mock_resp)
        return mc

    def test_respuesta_normal(self):
        with patch.object(ai_svc, "_genai_client", self._mock_client("El desayuno es a las 8.")):
            r = run(ai_svc.generate_response("A qué hora es el desayuno?", "Desayuno 8-10hs"))
        assert "8" in r or "desayuno" in r.lower()

    def test_respuesta_emergencia_tiene_tag(self):
        texto_emerg = "[EMERGENCIA] Gas detectado. Evacuá de inmediato."
        with patch.object(ai_svc, "_genai_client", self._mock_client(texto_emerg)):
            r = run(ai_svc.generate_response("hay olor a gas", "..."))
        assert ai_svc.es_emergencia(r)

    def test_error_retorna_fallback(self):
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))
        with patch.object(ai_svc, "_genai_client", mc):
            r = run(ai_svc.generate_response("consulta", "contexto"))
        assert r == ai_svc._RESPUESTA_FALLBACK

    def test_mensaje_vacio_retorna_fallback(self):
        with patch.object(ai_svc, "_genai_client", MagicMock()):
            r = run(ai_svc.generate_response("  ", "contexto"))
        assert r == ai_svc._RESPUESTA_FALLBACK

    @pytest.mark.parametrize("texto,esperado", [
        ("[EMERGENCIA] Evacuá.",          True),
        ("  [EMERGENCIA] Calma.",         True),
        ("El desayuno es bueno.",         False),
        ("emergencia no al inicio False", False),
    ])
    def test_es_emergencia(self, texto, esperado):
        assert ai_svc.es_emergencia(texto) is esperado

    @pytest.mark.parametrize("msg,esperado", [
        ("hay una fuga de gas",   True),
        ("inundacion en el baño", True),
        ("no funciona la tv",     False),
        ("necesito mas toallas",  False),
    ])
    def test_detectar_emergencia_keywords(self, msg, esperado):
        assert ai_svc.detectar_emergencia_en_mensaje(msg) is esperado


# ─────────────────────────────────────────────────────────────────────────────
# ai_service.clasificar_ticket
# ─────────────────────────────────────────────────────────────────────────────

class TestClasificarTicket:

    def test_keyword_emergencia_sin_gemini(self):
        """Capa de keywords devuelve True sin llamar a Gemini."""
        llamadas = []
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(side_effect=lambda *a, **k: llamadas.append(1))
        with patch.object(ai_svc, "_genai_client", mc):
            es_emerg, _ = run(ai_svc.clasificar_ticket("hay una inundacion en el bano"))
        assert es_emerg is True
        assert llamadas == []

    def test_texto_normal_via_gemini(self):
        mock_resp = MagicMock(); mock_resp.text = "NORMAL: falta una toalla"
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(return_value=mock_resp)
        with patch.object(ai_svc, "_genai_client", mc):
            es_emerg, resumen = run(ai_svc.clasificar_ticket("me falta una toalla"))
        assert es_emerg is False
        assert "toalla" in resumen.lower()

    def test_gemini_responde_emergencia(self):
        mock_resp = MagicMock(); mock_resp.text = "EMERGENCIA: cerradura rota de noche"
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(return_value=mock_resp)
        with patch.object(ai_svc, "_genai_client", mc):
            es_emerg, _ = run(ai_svc.clasificar_ticket("la cerradura no cierra"))
        assert es_emerg is True

    def test_gemini_falla_fallback_keywords(self):
        mc = MagicMock()
        mc.aio.models.generate_content = AsyncMock(side_effect=Exception("timeout"))
        with patch.object(ai_svc, "_genai_client", mc):
            es_emerg, _ = run(ai_svc.clasificar_ticket("no funciona el wifi"))
        assert es_emerg is False


# ─────────────────────────────────────────────────────────────────────────────
# sheets_service — parseo y normalización
# ─────────────────────────────────────────────────────────────────────────────

class TestSheetsServiceParseo:

    def test_fila_completa(self):
        fila = ["Juan","5491100000001","j@t.com","205","2026-07-10","2026-07-15",
                "SÍ","DriveXYZ","en","CHECKED_IN","AWAITING_DNI","4821"]
        e = _fila_a_estado_huesped(fila, 3)
        assert e.nombre               == "Juan"
        assert e.pre_checkin_completo is True
        assert e.idioma               == "en"
        assert e.estado_estadia       == EstadoEstadia.CHECKED_IN
        assert e.contexto_chat        == ContextoChat.AWAITING_DNI
        assert e.pin_acceso           == "4821"
        assert e._fila                == 3

    def test_fila_corta_usa_defaults(self):
        e = _fila_a_estado_huesped(["Maria", "5499000000000"], 2)
        assert e.pre_checkin_completo is False
        assert e.idioma               == "es"
        assert e.estado_estadia       == EstadoEstadia.RESERVADO
        assert e.contexto_chat        == ContextoChat.NORMAL

    def test_estado_invalido_degradado(self):
        fila = ["X","Y","","","","","NO","","es","INVALIDO","NORMAL",""]
        e = _fila_a_estado_huesped(fila, 1)
        assert e.estado_estadia == EstadoEstadia.RESERVADO

    def test_contexto_invalido_degradado(self):
        fila = ["X","Y","","","","","NO","","es","RESERVADO","INVALIDO",""]
        e = _fila_a_estado_huesped(fila, 1)
        assert e.contexto_chat == ContextoChat.NORMAL

    @pytest.mark.parametrize("si_val", ["SI", "SÍ", "YES", "S", "TRUE", "1"])
    def test_variantes_precheckin_si(self, si_val):
        fila = ["n","t","","","","",si_val,"","es","RESERVADO","NORMAL",""]
        assert _fila_a_estado_huesped(fila, 1).pre_checkin_completo is True

    @pytest.mark.parametrize("entrada,esperado", [
        ("5491187654321",       "5491187654321"),
        ("+54 9 11 8765-4321",  "5491187654321"),
        ("(54)9118765 4321",    "5491187654321"),
    ])
    def test_normalizacion_telefono(self, entrada, esperado):
        assert sh_svc._normalizar_telefono(entrada) == esperado

    def test_to_dict_no_expone_fila(self):
        fila = ["Ana","123","","","","","NO","","es","RESERVADO","NORMAL",""]
        d = _fila_a_estado_huesped(fila, 5).to_dict()
        assert "_fila" not in d
        assert "estado_estadia" in d
        assert "pin_acceso"     in d


# ─────────────────────────────────────────────────────────────────────────────
# whatsapp_service — payload builders
# ─────────────────────────────────────────────────────────────────────────────

class TestWhatsappService:

    @pytest.mark.parametrize("idioma", ["es", "en", "pt"])
    def test_menu_estadia_es_list_message_con_4_opciones(self, idioma):
        payload = wa_svc.construir_payload_menu(to="549111", idioma=idioma, nombre="Juan")
        assert payload["type"] == "interactive"
        assert payload["interactive"]["type"] == "list"
        filas = payload["interactive"]["action"]["sections"][0]["rows"]
        assert {f["id"] for f in filas} == BotonesMenu.todos()

    def test_menu_estadia_incluye_nombre(self):
        payload = wa_svc.construir_payload_menu(to="549111", idioma="es", nombre="María")
        assert "María" in payload["interactive"]["body"]["text"]

    def test_menu_idioma_tiene_3_opciones_en_la_constante(self):
        """_MENU_IDIOMA define 3 opciones (ES/EN/PT)."""
        ids = {o["id"] for o in wa_svc._MENU_IDIOMA["opciones"]}
        assert ids == BotonesIdioma.todos()

    def test_botones_idioma_lang_for(self):
        assert BotonesIdioma.lang_for("lang_es") == "es"
        assert BotonesIdioma.lang_for("lang_en") == "en"
        assert BotonesIdioma.lang_for("lang_pt") == "pt"
        assert BotonesIdioma.lang_for("unknown") == "es"

    def test_checked_out_msg_tiene_hotel(self):
        msg = wa_svc._MSG_CHECKED_OUT["es"].format(hotel="Hotel XYZ")
        assert "Hotel XYZ" in msg


# ─────────────────────────────────────────────────────────────────────────────
# routers/whatsapp — _procesar_mensaje pipeline completo
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineUnificado:
    """9 escenarios del árbol de decisión de _procesar_mensaje."""

    def _run(self, guest, texto="", button_id="", extra_patches=None):
        """Ejecuta _procesar_mensaje con todos los servicios mockeados."""
        mocks = {
            "get_guest_state":     AsyncMock(return_value=guest),
            "check_subscription":  AsyncMock(return_value=True),
            "get_hotel_rules":     AsyncMock(return_value="PDF del hotel"),
            "generate_response":   AsyncMock(return_value="Respuesta de IA"),
            "update_stay_status":  AsyncMock(return_value=True),
            "update_chat_context": AsyncMock(return_value=True),
            "update_guest_idioma": AsyncMock(return_value=True),
            "_enviar_respuesta":   AsyncMock(return_value=None),
            "registrar_ticket":    AsyncMock(return_value=True),
            "clasificar_ticket":   AsyncMock(return_value=(False, "normal")),
        }
        if extra_patches:
            mocks.update(extra_patches)

        ws_mocks = {k: AsyncMock(return_value=True) for k in [
            "enviar_menu_idioma", "enviar_menu_estadia",
            "enviar_bienvenida",  "enviar_checked_out",
            "enviar_solicitud_ticket", "enviar_confirmacion_ticket",
        ]}

        patches_router = [patch.object(wa_router, k, v) for k, v in mocks.items()]
        patches_ws     = [patch.object(wa_svc, k, v) for k, v in ws_mocks.items()]

        import contextlib
        with contextlib.ExitStack() as stack:
            [stack.enter_context(p) for p in patches_router + patches_ws]
            run(wa_router._procesar_mensaje("5491100000001", texto, "PID", button_id))
            return mocks, ws_mocks

    # ── Filtro 0 ──────────────────────────────────────────────────────────────

    def test_f0_idioma_vacio_envia_menu_idioma(self):
        _, ws = self._run(huesped(idioma=""), texto="hola")
        ws["enviar_menu_idioma"].assert_awaited_once()

    def test_f0_boton_idioma_registra_idioma_y_envia_bienvenida(self):
        m, ws = self._run(huesped(idioma=""), button_id="lang_es")
        m["update_guest_idioma"].assert_awaited_once_with("5491100000001", "es")
        ws["enviar_bienvenida"].assert_awaited_once()

    # ── Filtro 1 ──────────────────────────────────────────────────────────────

    def test_f1_suscripcion_inactiva_bloquea_sin_respuesta(self):
        m, ws = self._run(
            huesped(), texto="hola",
            extra_patches={"check_subscription": AsyncMock(return_value=False)},
        )
        m["_enviar_respuesta"].assert_not_awaited()

    # ── Filtro 2 ──────────────────────────────────────────────────────────────

    def test_f2_awaiting_dni_reitera_formulario(self):
        m, _ = self._run(
            huesped(contexto_chat="AWAITING_DNI", pre_checkin_completo=False)
        )
        assert m["_enviar_respuesta"].call_count == 1
        texto_msg = m["_enviar_respuesta"].call_args[0][2]
        assert "https://test.crm.com/precheckin/" in texto_msg

    def test_f2_awaiting_ticket_procesa_y_guarda(self):
        m, ws = self._run(
            huesped(contexto_chat="AWAITING_TICKET"),
            texto="falta una toalla",
            extra_patches={"clasificar_ticket": AsyncMock(return_value=(False, "falta toalla"))},
        )
        m["registrar_ticket"].assert_awaited_once()
        m["update_chat_context"].assert_awaited()

    # ── Filtro 3a RESERVADO ───────────────────────────────────────────────────

    def test_f3a_llegada_detectada_envia_pin_y_actualiza_estado(self):
        m, _ = self._run(
            huesped(estado_estadia="RESERVADO", contexto_chat="NORMAL"),
            texto="ya llegue al hotel",
        )
        m["update_stay_status"].assert_awaited_once()
        nuevo_estado = m["update_stay_status"].call_args[0][1]
        assert nuevo_estado == EstadoEstadia.CHECKED_IN
        texto_msg = m["_enviar_respuesta"].call_args[0][2]
        assert "4821" in texto_msg   # PIN de acceso

    # ── Filtro 3b CHECKED_IN ──────────────────────────────────────────────────

    def test_f3b_texto_libre_llama_ia_con_contexto_huesped(self):
        prompts = []
        async def mock_ia(msg, ctx): prompts.append((msg, ctx)); return "Respuesta"
        m, _ = self._run(
            huesped(), texto="a que hora cierra la piscina",
            extra_patches={"generate_response": AsyncMock(side_effect=mock_ia)},
        )
        assert len(prompts) == 1
        _, contexto = prompts[0]
        assert "Ana Lopez" in contexto      # nombre del huésped inyectado

    def test_f3b_emergencia_genera_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="virtual_receptionist.routers.whatsapp"):
            self._run(
                huesped(), texto="hay una fuga de gas",
                extra_patches={"generate_response": AsyncMock(return_value="[EMERGENCIA] Evacuá.")},
            )
        assert any(
            "ALERTA" in r.message or "TWILIO" in r.message or "TELEGRAM" in r.message
            for r in caplog.records
        )

    def test_f3b_sin_texto_envia_menu_estadia(self):
        _, ws = self._run(huesped(), texto="")
        ws["enviar_menu_estadia"].assert_awaited_once()

    # ── Filtro 3c CHECKED_OUT ─────────────────────────────────────────────────

    def test_f3c_checked_out_envia_despedida(self):
        _, ws = self._run(huesped(estado_estadia="CHECKED_OUT"), texto="hola")
        ws["enviar_checked_out"].assert_awaited_once()
