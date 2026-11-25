"""Corrida diaria de punta a punta con red, medios y Claude simulados (sin conexión ni claves)."""
import json
from types import SimpleNamespace as NS

import pytest

from radar_vial import claude as modulo_claude
from radar_vial import pipeline
from radar_vial.claude import Claude
from radar_vial.historial import Historial, clave_url
from radar_vial.notas import Notas

FICHA = {"fecha_hecho": "2026-11-18", "fecha_aproximada": False, "hora_franja": "noche", "provincia": "Salta",
         "departamento": None, "localidad": "Cafayate", "via": "RN 40", "tipo_via": "ruta_nacional",
         "tipo_siniestro": "vuelco", "vehiculos": ["camion"], "fallecidos": 0, "heridos_graves": 1, "heridos_leves": None,
         "heridos_sin_detalle": None, "factores_mencionados": [], "grupos_etarios": [],
         "resumen": "Vuelco de un camión en la RN 40, cerca de Cafayate: una persona resultó gravemente herida.",
         "confianza": "alta"}


def _items():
    base = {"bajada": "", "medio": "Medio", "provincia_medio": "66", "nivel_medio": "provincial",
            "publicada": "2026-11-18T22:00:00+00:00", "tipo_busqueda": "siniestro", "titulo_provisional": False}
    return [
        {**base, "id": "n_a", "titulo": "Volcó un camión en la Ruta 40 cerca de Cafayate y su chofer está grave",
         "url": "https://news.google.com/rss/articles/A", "gn_id": "A", "clave": None, "hash_titulo": "ha",
         "sitio": "medio-a.com.ar", "origenes": [{"tipo": "google_news", "consulta": "q", "provincia": "66", "termino": "vuelco"}]},
        {**base, "id": "n_b", "titulo": "Choque en la ruta 9 dejó heridos en las afueras de la ciudad de Salta",
         "url": "https://news.google.com/rss/articles/B", "gn_id": "B", "clave": None, "hash_titulo": "hb",
         "sitio": "medio-b.com.ar", "origenes": [{"tipo": "google_news", "consulta": "q", "provincia": "66", "termino": "choque"}]},
        {**base, "id": "n_c", "titulo": "Choque de opiniones en la Legislatura por el presupuesto provincial",
         "url": "https://medio-c.com.ar/politica/1", "gn_id": None, "clave": clave_url("https://medio-c.com.ar/politica/1"),
         "hash_titulo": "hc", "sitio": "medio-c.com.ar", "origenes": [{"tipo": "rss", "consulta": "RSS C", "provincia": "66", "termino": None}]},
    ]


def _respuesta(kw):
    sistema = kw["system"][0]["text"]
    if "lista numerada" in sistema:  # filtro
        mensaje = kw["messages"][0]["content"]
        notas = []
        for linea in mensaje.splitlines():
            if linea[:1].isdigit() and ". " in linea:
                n, titulo = linea.split(". ", 1)
                notas.append({"n": int(n), "argentina": True,
                              "categoria": "descartar" if "opiniones" in titulo else "siniestro"})
        datos = {"notas": notas}
    else:  # extracción
        datos = {"categoria": "siniestro", "siniestros": [dict(FICHA)], "contexto": None}
    return NS(stop_reason="end_turn", stop_details=None,
              usage=NS(input_tokens=500, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0),
              content=[NS(type="text", text=json.dumps(datos))])


class _Cliente:
    def __init__(self):
        self.llamadas = []
        crear = lambda **kw: (self.llamadas.append(kw), _respuesta(kw))[1]  # noqa: E731
        self.messages = NS(create=crear)
        self.beta = NS(messages=NS(create=crear))


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    estado = {"resolubles": {"A"}, "cliente": _Cliente(), "cache": {}}
    monkeypatch.setattr(pipeline, "Historial", lambda: Historial(tmp_path / "historial.jsonl"))
    monkeypatch.setattr(pipeline, "Notas", lambda: Notas(tmp_path / "notas.jsonl"))
    monkeypatch.setattr(modulo_claude, "ARCHIVO_COSTOS", tmp_path / "costos.jsonl")
    monkeypatch.setattr(pipeline, "Claude", lambda registro: Claude(registro, cliente=estado["cliente"]))
    monkeypatch.setattr(pipeline, "recolectar", lambda red, log=None: (_items(), []))
    monkeypatch.setattr(pipeline, "guardar_texto", lambda i, d: estado["cache"].__setitem__(i, d))
    monkeypatch.setattr(pipeline, "cargar_texto", lambda i: estado["cache"].get(i))
    monkeypatch.setattr(pipeline, "podar_textos", lambda: 0)
    from radar_vial import agregados
    from radar_vial.eventos import armar_eventos

    monkeypatch.setattr(agregados, "publicar", lambda **kw: None)   # no tocar docs/data

    # eventos en la carpeta temporal y sin Georef (las fichas sin geo se comparan igual)
    monkeypatch.setattr(pipeline, "geo_y_eventos", lambda notas, claude, log=None: armar_eventos(
        notas, None, log=lambda *a: None, archivo=tmp_path / "eventos.jsonl", archivo_decisiones=tmp_path / "dec.json"))

    class _Resolvedor:
        def __init__(self, red):
            pass

        def resolver_con_metodo(self, it):
            if it.get("gn_id") in estado["resolubles"]:
                return f"https://{it['sitio']}/nota-{it['gn_id']}", "medio"
            return (None, None) if it.get("gn_id") else (it["url"], "directa")

        def guardar(self):
            pass

    def _bajar(red, robots, url):
        return {"url_final": url, "url_canonica": url, "clave": clave_url(url), "titulo": "", "error": None,
                "texto": "Texto completo de la nota con los detalles del vuelco del camión en la RN 40.", "fecha": None}

    monkeypatch.setattr(pipeline, "Resolvedor", _Resolvedor)
    monkeypatch.setattr(pipeline, "Robots", lambda red: None)
    monkeypatch.setattr(pipeline, "bajar_nota", _bajar)
    estado["tmp"] = tmp_path
    return estado


def test_dos_corridas_seguidas(entorno):
    silencio = lambda *a: None  # noqa: E731
    r1 = pipeline.correr_diario(log=silencio)
    assert r1["siniestro"] == 2 and r1["solo_titulo"] == 1
    notas = Notas(entorno["tmp"] / "notas.jsonl")
    assert set(notas.por_id) == {"n_a", "n_b"}
    assert notas.por_id["n_a"]["fuente_texto"] == "completo"
    assert notas.por_id["n_b"]["fuente_texto"] == "titulo"
    assert notas.por_id["n_a"]["url"] == "https://medio-a.com.ar/nota-A"
    # las fichas no guardan títulos
    assert "Cafayate y su chofer" not in (entorno["tmp"] / "notas.jsonl").read_text(encoding="utf-8")
    h = Historial(entorno["tmp"] / "historial.jsonl")
    assert h.buscar({"gn_id": "A"})["estado"] == "siniestro"
    assert h.buscar({"gn_id": "B"})["estado"] == "solo_titulo"
    assert h.buscar({"clave": clave_url("https://medio-c.com.ar/politica/1")})["estado"] == "descartada"
    costos = [json.loads(x) for x in (entorno["tmp"] / "costos.jsonl").read_text(encoding="utf-8").splitlines()]
    assert costos[0]["costo_total_usd"] > 0 and costos[0]["notas"]["recolectadas"] == 3
    # A y B devuelven la misma ficha simulada, pero B es solo de título y sin desempate queda aparte
    assert r1["eventos"] == 2 and (entorno["tmp"] / "eventos.jsonl").exists()

    # Segunda corrida: la nota B ya se puede resolver; A y C no se vuelven a procesar
    entorno["resolubles"].add("B")
    llamadas_antes = len(entorno["cliente"].llamadas)
    r2 = pipeline.correr_diario(log=silencio)
    assert r2["nuevas"] == 1 and r2["siniestro"] == 1 and r2["solo_titulo"] == 0
    nuevas = entorno["cliente"].llamadas[llamadas_antes:]
    assert all("lista numerada" not in ll["system"][0]["text"] for ll in nuevas)  # B no se vuelve a filtrar
    notas = Notas(entorno["tmp"] / "notas.jsonl")
    assert notas.por_id["n_b"]["fuente_texto"] == "completo"
    assert Historial(entorno["tmp"] / "historial.jsonl").buscar({"gn_id": "B"})["estado"] == "siniestro"


def test_ficha_de_solo_titulo_que_resulta_duplicada_deja_de_contarse(entorno, monkeypatch):
    silencio = lambda *a: None  # noqa: E731
    pipeline.correr_diario(log=silencio)
    assert "n_b" in Notas(entorno["tmp"] / "notas.jsonl").por_id   # ficha hecha solo con el título

    # Segunda corrida: B se resuelve a la misma URL que trae, directa, una nota del RSS del medio
    url_b = "https://medio-b.com.ar/nota-B"
    directa = {**_items()[1], "id": "n_rss_b", "url": url_b, "gn_id": None, "clave": clave_url(url_b),
               "hash_titulo": None, "titulo": "Choque en la RN 9: heridos (versión del RSS del medio)",
               "origenes": [{"tipo": "rss", "consulta": "RSS B", "provincia": "66", "termino": None}]}
    monkeypatch.setattr(pipeline, "recolectar", lambda red, log=None: ([directa] + _items(), []))
    entorno["resolubles"].add("B")
    pipeline.correr_diario(log=silencio)
    notas = Notas(entorno["tmp"] / "notas.jsonl").por_id
    assert "n_rss_b" in notas and "n_b" not in notas   # el siniestro queda contado una sola vez


def test_nota_en_cola_que_reaparece_no_se_vuelve_a_filtrar(entorno):
    silencio = lambda *a: None  # noqa: E731
    r1 = pipeline.correr_diario(log=silencio, tope=1)
    assert r1["postergadas"] == 1                       # una de las dos relevantes quedó en la cola
    antes = len(entorno["cliente"].llamadas)
    pipeline.correr_diario(log=silencio, tope=5)         # reaparece en la recolección
    nuevas = entorno["cliente"].llamadas[antes:]
    assert all("lista numerada" not in ll["system"][0]["text"] for ll in nuevas)
    assert len(Notas(entorno["tmp"] / "notas.jsonl").por_id) == 2


def test_el_contexto_tiene_cupo_propio_dentro_del_tope():
    rel = [{"id": f"s{i}", "filtro": "siniestro"} for i in range(10)] + [{"id": f"c{i}", "filtro": "contexto"} for i in range(5)]
    elegidas, postergadas = pipeline.elegir_para_extraer(rel, tope=6, cupo_contexto=2)
    assert [it["id"] for it in elegidas] == ["s0", "s1", "s2", "s3", "c0", "c1"]
    assert len(postergadas) == 9
    # si hay pocos siniestros, el lugar que sobra lo usa el contexto
    elegidas, _ = pipeline.elegir_para_extraer(rel[8:], tope=6, cupo_contexto=2)
    assert [it["id"] for it in elegidas] == ["s8", "s9", "c0", "c1", "c2", "c3"]


# ------------------------------------------------------------------ casos de la revisión del 20-11-2026

def _extracciones(entorno):
    return sum(1 for ll in entorno["cliente"].llamadas if "lista numerada" not in ll["system"][0]["text"])


def test_una_duplicada_no_pisa_el_registro_de_la_original(entorno, monkeypatch):
    silencio = lambda *a: None  # noqa: E731
    pipeline.correr_diario(log=silencio)
    # la nota A, ya extraída, vuelve por el RSS del medio (misma URL) con un título que no deduplica
    url_a = "https://medio-a.com.ar/nota-A"
    directa = {**_items()[0], "id": "n_rss_a", "url": url_a, "gn_id": None, "clave": None, "hash_titulo": None,
               "origenes": [{"tipo": "rss", "consulta": "RSS A", "provincia": "66", "termino": None}]}
    otra_via = {**directa, "id": "n_gn_a2", "gn_id": "A", "url": "https://news.google.com/rss/articles/A"}
    otra_via["gn_id"] = "A2"
    entorno["resolubles"].add("A2")
    monkeypatch.setattr(pipeline.Resolvedor, "resolver_con_metodo",
                        lambda self, it: (url_a, "medio") if it.get("gn_id") == "A2" else (None, None))
    monkeypatch.setattr(pipeline, "recolectar", lambda red, log=None: ([otra_via], []))
    antes = _extracciones(entorno)
    pipeline.correr_diario(log=silencio)
    h = Historial(entorno["tmp"] / "historial.jsonl")
    original = h.buscar({"gn_id": "A"})
    assert original["estado"] == "siniestro" and original["id_nota"] == "n_a"   # no quedó como "duplicada"
    assert h.buscar({"gn_id": "A2"}) is original                                # la otra vía es un alias
    assert _extracciones(entorno) == antes                                      # no se pagó otra extracción
    assert set(Notas(entorno["tmp"] / "notas.jsonl").por_id) == {"n_a", "n_b"}
    r3 = pipeline.correr_diario(log=silencio)                                   # y ya no vuelve a entrar
    assert r3["nuevas"] == 0


def test_si_el_filtro_no_responde_la_corrida_queda_incompleta_y_nada_se_pierde(entorno, monkeypatch):
    silencio = lambda *a: None  # noqa: E731
    filtro_real = pipeline.filtrar

    def caido(claude, items, log=None):
        for it in items:
            it["filtro"] = "sin_evaluar"

    monkeypatch.setattr(pipeline, "filtrar", caido)
    r1 = pipeline.correr_diario(log=silencio)
    assert r1["incompleta"] and r1["sin_evaluar"] == 3
    cola = pipeline.cargar_pendientes()
    assert len(cola) == 3 and all(p["filtro"] is None for p in cola)
    # al día siguiente las notas ya salieron de la ventana, pero siguen en la cola y se procesan
    monkeypatch.setattr(pipeline, "filtrar", filtro_real)
    monkeypatch.setattr(pipeline, "recolectar", lambda red, log=None: ([], []))
    r2 = pipeline.correr_diario(log=silencio)
    assert not r2["incompleta"] and r2["siniestro"] == 2
    assert pipeline.cargar_pendientes() == []


def test_una_corrida_cortada_conserva_lo_extraido_y_la_cola(entorno, monkeypatch):
    silencio = lambda *a: None  # noqa: E731
    real = pipeline.extraer_nota

    def se_corta(claude, it, texto):
        if it["id"] == "n_b":
            raise KeyboardInterrupt
        return real(claude, it, texto)

    monkeypatch.setattr(pipeline, "extraer_nota", se_corta)
    with pytest.raises(KeyboardInterrupt):
        pipeline.correr_diario(log=silencio)
    assert set(Notas(entorno["tmp"] / "notas.jsonl").por_id) == {"n_a"}       # lo ya pagado quedó guardado
    assert [p["id"] for p in pipeline.cargar_pendientes()] == ["n_b"]          # lo que faltaba sigue en la cola
    costos = (entorno["tmp"] / "costos.jsonl").read_text(encoding="utf-8")
    assert '"interrumpida": true' in costos


def test_los_reintentos_de_solo_titulo_no_ocupan_el_tope(entorno, monkeypatch):
    silencio = lambda *a: None  # noqa: E731
    pipeline.correr_diario(log=silencio)                          # B queda con ficha de solo título
    # Corrida cercana: B vuelve (sigue sin poder resolverse) junto con una nota nueva, más vieja que B
    nueva = {**_items()[0], "id": "n_d", "titulo": "Chocaron dos autos en la avenida principal de Tartagal",
             "gn_id": "D", "url": "https://news.google.com/rss/articles/D", "hash_titulo": "hd",
             "sitio": "medio-d.com.ar", "publicada": "2026-11-18T10:00:00+00:00"}
    monkeypatch.setattr(pipeline, "recolectar", lambda red, log=None: ([nueva] + _items(), []))
    entorno["resolubles"].add("D")
    r = pipeline.correr_diario(log=silencio, tope=1)
    assert r["postergadas"] == 0 and r["reintentos"] == 1         # B se reintenta aparte del tope
    assert "n_d" in Notas(entorno["tmp"] / "notas.jsonl").por_id   # y la nota nueva entra
    assert Historial(entorno["tmp"] / "historial.jsonl").buscar({"gn_id": "B"})["intentos"] == 2


def test_la_cola_avisa_lo_que_vence_sin_procesarse(entorno):
    from datetime import datetime, timedelta, timezone
    ahora = datetime.now(timezone.utc)
    vieja = {**_items()[0], "filtro": "siniestro", "publicada": (ahora - timedelta(days=8)).isoformat()}
    vieja_ctx = {**_items()[1], "filtro": "contexto", "publicada": (ahora - timedelta(days=9)).isoformat()}
    fresca = {**_items()[2], "filtro": "siniestro", "publicada": (ahora - timedelta(days=1)).isoformat()}
    pipeline.guardar_pendientes([vieja, vieja_ctx, fresca])
    mensajes = []
    cola = pipeline.cargar_pendientes(log=mensajes.append)
    assert [p["id"] for p in cola] == ["n_c"]
    assert len(mensajes) == 1 and "2 notas" in mensajes[0] and "1 de siniestros" in mensajes[0]


def test_con_un_tope_chico_igual_entran_siniestros():
    rel = [{"id": f"s{i}", "filtro": "siniestro"} for i in range(100)] + [{"id": f"c{i}", "filtro": "contexto"} for i in range(60)]
    elegidas, _ = pipeline.elegir_para_extraer(rel, tope=10, cupo_contexto=50)
    assert sum(1 for it in elegidas if it["filtro"] == "siniestro") == 7
    elegidas, _ = pipeline.elegir_para_extraer(rel, tope=150, cupo_contexto=50)
    assert sum(1 for it in elegidas if it["filtro"] == "contexto") == 50


def test_corrida_incompleta_o_con_tope_no_marca_el_dia(monkeypatch):
    from radar_vial import __main__ as cli
    from radar_vial import estado

    marcas = []
    monkeypatch.setattr(estado, "marcar_diario", lambda resumen, publicado: marcas.append(resumen))
    args = NS(si_no_corrio_hoy=False, sin_publicar=False, tope=None)
    monkeypatch.setattr(pipeline, "correr_diario", lambda **kw: {"incompleta": "el filtro no pudo evaluar 40 de 40 notas"})
    with pytest.raises(SystemExit):
        cli.cmd_diario(args)
    monkeypatch.setattr(pipeline, "correr_diario", lambda **kw: {"incompleta": None})
    cli.cmd_diario(NS(si_no_corrio_hoy=False, sin_publicar=False, tope=30))
    assert marcas == []
    cli.cmd_diario(args)
    assert len(marcas) == 1
