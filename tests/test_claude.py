"""Filtro, extracción y cliente de Claude con una API simulada (sin red ni claves)."""
import json
from types import SimpleNamespace as NS

import pytest

from radar_vial.claude import Claude, ErrorClaude, RegistroCostos
from radar_vial.extraer import extraer_nota
from radar_vial.filtrar import filtrar


def _resp(datos, stop="end_turn", entrada=1000, salida=200):
    return NS(stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=entrada, output_tokens=salida, cache_read_input_tokens=0, cache_creation_input_tokens=0),
              content=[NS(type="thinking", thinking=""), NS(type="text", text=json.dumps(datos))])


class _Mensajes:
    def __init__(self, respuestas, registro_llamadas):
        self.respuestas, self.llamadas = respuestas, registro_llamadas

    def create(self, **kw):
        self.llamadas.append(kw)
        r = self.respuestas.pop(0)
        return r(kw) if callable(r) else r


class ClienteFalso:
    def __init__(self, respuestas):
        self.llamadas = []
        self.messages = _Mensajes(respuestas, self.llamadas)
        self.beta = NS(messages=_Mensajes(respuestas, self.llamadas))


def _claude(respuestas):
    registro = RegistroCostos("test")
    return Claude(registro, cliente=ClienteFalso(respuestas)), registro


# ---------------------------------------------------------------- cliente

def test_respuesta_json_y_costo():
    claude, registro = _claude([_resp({"ok": True}, entrada=1_000_000, salida=100_000)])
    assert claude.json("filtro", "claude-haiku-5-5", "sis", "msg", {"type": "object"}) == {"ok": True}
    llamada = claude.cliente.llamadas[0]
    assert llamada["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in llamada and "fallbacks" not in llamada
    # 1M de entrada a 0,10 + 100k de salida a 0,50 = 0,15
    assert registro.resumen()["costo_total_usd"] == pytest.approx(0.15)


def test_sonnet_lleva_respaldo_por_rechazo():
    claude, _ = _claude([_resp({"ok": True})])
    claude.json("extraccion", "claude-sonnet-5-5", "sis", "msg", {"type": "object"})
    llamada = claude.cliente.llamadas[0]
    assert llamada["fallbacks"] == "default" and llamada["betas"] == ["server-side-fallback-2026-07-01"]


def test_rechazo_y_respuesta_cortada_son_errores():
    claude, registro = _claude([_resp({}, stop="refusal"), _resp({}, stop="max_tokens")])
    with pytest.raises(ErrorClaude, match="rechaz"):
        claude.json("filtro", "claude-haiku-5-5", "s", "m", {})
    with pytest.raises(ErrorClaude, match="max_tokens"):
        claude.json("filtro", "claude-haiku-5-5", "s", "m", {})
    assert registro.resumen()["etapas"][0]["rechazos"] == 1


# ---------------------------------------------------------------- filtro

def _item(n, titulo):
    return {"id": f"n_{n}", "titulo": titulo, "bajada": "", "medio": "Medio", "sitio": "medio.com.ar",
            "origenes": [{"provincia": "90"}], "publicada": "2026-11-18T12:00:00+00:00"}


def test_filtro_clasifica_y_lo_que_falta_queda_sin_evaluar():
    items = [_item(1, "Choque fatal en la RN 9"), _item(2, "Choque de opiniones en el Concejo"),
             _item(3, "Choque en Córdoba, España"), _item(4, "Controles de alcoholemia en Tafí")]
    respuesta = {"notas": [{"n": 1, "argentina": True, "categoria": "siniestro"},
                           {"n": 2, "argentina": True, "categoria": "descartar"},
                           {"n": 3, "argentina": False, "categoria": "siniestro"}]}
    claude, _ = _claude([_resp(respuesta)])
    filtrar(claude, items, log=lambda *a: None)
    assert [it["filtro"] for it in items] == ["siniestro", "descartar", "descartar", "sin_evaluar"]
    assert "Buscada por: Tucumán" in claude.cliente.llamadas[0]["messages"][0]["content"]


def test_lote_fallido_queda_sin_evaluar():
    claude, _ = _claude([_resp({}, stop="refusal")])
    items = [_item(1, "Choque fatal en la RN 9")]
    filtrar(claude, items, log=lambda *a: None)
    assert items[0]["filtro"] == "sin_evaluar"


# ---------------------------------------------------------------- extracción

FICHA = {
    "fecha_hecho": "2026-11-17", "fecha_aproximada": False, "hora_franja": "madrugada", "provincia": "Tucumán",
    "departamento": None, "localidad": "Banda del Río Salí", "via": "RN 9 km 1290", "tipo_via": "ruta_nacional",
    "tipo_siniestro": "choque_frontal", "vehiculos": ["auto", "moto", "auto"], "fallecidos": 1, "heridos_graves": None,
    "heridos_leves": 2, "heridos_sin_detalle": None,
    "factores_mencionados": [{"factor": "alcohol", "presunto": True}, {"factor": "alcohol", "presunto": False}],
    "grupos_etarios": ["joven"], "resumen": "Choque frontal entre un auto y una moto en la RN 9: una persona murió.",
    "confianza": "alta",
}


def test_extraccion_valida_y_normaliza():
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [FICHA], "contexto": None})])
    nota = {**_item(1, "Choque fatal en la RN 9"), "provincia_medio": "90"}
    ext = extraer_nota(claude, nota, "Texto de la nota sobre el choque en la RN 9 con una persona fallecida.")
    f = ext["siniestros"][0]
    assert f["provincia_id"] == "90"
    assert f["vehiculos"] == ["auto", "moto"]
    assert len(f["factores_mencionados"]) == 1
    sistema = claude.cliente.llamadas[0]["system"][0]
    assert sistema["cache_control"] == {"type": "ephemeral"}
    assert "Fecha de publicación: 2026-11-18" in claude.cliente.llamadas[0]["messages"][0]["content"]


def test_fecha_posterior_a_la_publicacion_se_corrige():
    ficha = {**FICHA, "fecha_hecho": "2026-12-01"}
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [ficha], "contexto": None})])
    f = extraer_nota(claude, _item(1, "x"), "texto")["siniestros"][0]
    assert f["fecha_hecho"] == "2026-11-18" and f["fecha_aproximada"] is True


def test_nombre_colado_en_el_resumen_se_reemplaza():
    ficha = {**FICHA, "resumen": "Murió Juan Carlos Pérez en un choque frontal en la RN 9."}
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [ficha], "contexto": None})])
    texto = "La víctima fue identificada como Juan Carlos Pérez, de 34 años."
    f = extraer_nota(claude, _item(1, "Choque fatal"), texto)["siniestros"][0]
    assert "Pérez" not in f["resumen"]


def test_siniestro_sin_fichas_no_se_cuenta():
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [], "contexto": None})])
    assert extraer_nota(claude, _item(1, "x"), "texto")["categoria"] == "descartar"


def test_solo_titulo_lo_avisa_en_el_mensaje():
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [FICHA], "contexto": None})])
    extraer_nota(claude, _item(1, "Choque fatal en la RN 9"), None)
    assert "solo hay título" in claude.cliente.llamadas[0]["messages"][0]["content"]


def test_anio_mal_puesto_se_corrige_y_los_hechos_viejos_no_se_cuentan():
    from datetime import date

    from radar_vial.extraer import corregir_anio

    assert corregir_anio(date(2025, 11, 14), date(2026, 11, 19)) == date(2026, 11, 14)
    assert corregir_anio(date(2026, 12, 30), date(2027, 1, 2)) == date(2026, 12, 30)   # cambio de año, ya bien
    assert corregir_anio(date(2026, 12, 30).replace(year=2025), date(2027, 1, 2)) == date(2026, 12, 30)
    assert corregir_anio(date(2024, 3, 1), date(2026, 11, 19)) == date(2024, 3, 1)      # viejo de verdad
    vieja = {**FICHA, "fecha_hecho": "2025-06-10"}
    claude, _ = _claude([_resp({"categoria": "siniestro", "siniestros": [vieja], "contexto": None})])
    assert extraer_nota(claude, _item(1, "Juicio por un choque"), "texto")["categoria"] == "descartar"


def test_los_lotes_del_filtro_van_de_a_varios():
    import threading

    class Claude:
        barrera = threading.Barrier(2, timeout=3)

        def json(self, etapa, modelo, sistema, mensaje, schema, **kw):
            self.barrera.wait()     # si los lotes fueran de a uno, la espera se vence y la prueba falla
            n = sum(1 for linea in mensaje.splitlines() if linea[:1].isdigit() and ". " in linea)
            return {"notas": [{"n": i, "argentina": True, "categoria": "siniestro"} for i in range(1, n + 1)]}

    items = [_item(i, f"Choque número {i} en la ruta") for i in range(80)]     # dos lotes de 40
    filtrar(Claude(), items, log=lambda *a: None)
    assert all(it["filtro"] == "siniestro" for it in items)
