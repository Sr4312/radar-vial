"""Recuperación histórica con la cuenta de Claude (sin red, sin claves y sin llamar a Claude Code)."""
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from radar_vial import historico
from radar_vial.cuenta import AutenticacionNoEsCuenta, ClaudeCuenta, LimiteCuenta

FICHA = {"fecha_hecho": "2026-11-10", "fecha_aproximada": False, "hora_franja": "noche", "provincia": "Salta",
         "departamento": None, "localidad": "Cafayate", "via": "RN 40", "tipo_via": "ruta_nacional",
         "tipo_siniestro": "vuelco", "vehiculos": ["camion"], "fallecidos": 0, "heridos_graves": 1, "heridos_leves": None,
         "heridos_sin_detalle": None, "factores_mencionados": [], "grupos_etarios": [],
         "resumen": "Vuelco de un camión en la RN 40, cerca de Cafayate: una persona resultó gravemente herida.",
         "confianza": "alta"}


def test_ventanas_de_dos_dias_de_la_mas_reciente_a_la_mas_vieja():
    v = historico.ventanas(date(2026, 10, 18), date(2026, 10, 22))
    assert v == [(date(2026, 10, 22), date(2026, 10, 22)), (date(2026, 10, 20), date(2026, 10, 21)),
                 (date(2026, 10, 18), date(2026, 10, 19))]
    url = "https://news.google.com/rss/search?q=choque+Salta+when:2d&hl=es-419"
    assert historico.url_ventana(url, date(2026, 10, 20), date(2026, 10, 21)) == \
        "https://news.google.com/rss/search?q=choque+Salta+after:2026-10-19+before:2026-10-22&hl=es-419"


# ------------------------------------------------------------------ cliente de la cuenta

def _salida(fuente="none", limite="allowed", resultado=None):
    lineas = [{"type": "system", "subtype": "init", "apiKeySource": fuente},
              {"type": "rate_limit_event", "rate_limit_info": {"status": limite, "resetsAt": 1795212000}}]
    if resultado is not None:
        lineas.append({"type": "result", "is_error": False, "structured_output": resultado,
                       "usage": {"input_tokens": 10, "output_tokens": 5}})
    return NS(stdout="\n".join(json.dumps(x) for x in lineas), stderr="", returncode=0)


def test_cuenta_usa_claude_code_sin_la_clave_de_la_api(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prueba")
    monkeypatch.setattr("radar_vial.cuenta.ARCHIVO_USO", tmp_path / "uso.jsonl")
    llamadas = []

    def ejecutar(args, **kw):
        llamadas.append((args, kw))
        return _salida(resultado={"categoria": "siniestro"})

    c = ClaudeCuenta(ejecutable="claude", ejecutar=ejecutar)
    assert c.json("filtro", "claude-haiku-5-5", "Sistema", "Mensaje", {"type": "object"}) == {"categoria": "siniestro"}
    args, kw = llamadas[0]
    assert "ANTHROPIC_API_KEY" not in kw["env"]                       # nunca factura la API
    assert kw["input"] == "Mensaje" and "--no-session-persistence" in args and "--json-schema" in args
    assert c.uso["filtro|claude-haiku-5-5|llamadas"] == 1
    c.guardar_uso()
    assert json.loads((tmp_path / "uso.jsonl").read_text(encoding="utf-8"))["fuente"] == "cuenta"


def test_cuenta_se_frena_con_clave_de_api_o_con_el_limite():
    con_clave = ClaudeCuenta(ejecutable="claude", ejecutar=lambda a, **k: _salida(fuente="ANTHROPIC_API_KEY", resultado={}))
    with pytest.raises(AutenticacionNoEsCuenta):
        con_clave.json("filtro", "m", "s", "x", {})
    al_limite = ClaudeCuenta(ejecutable="claude", ejecutar=lambda a, **k: _salida(limite="rejected"))
    with pytest.raises(LimiteCuenta) as exc:
        al_limite.json("filtro", "m", "s", "x", {})
    assert exc.value.reinicio == datetime.fromtimestamp(1795212000, tz=timezone.utc)
    with pytest.raises(LimiteCuenta):            # una vez en el límite, no vuelve a llamar
        al_limite.json("filtro", "m", "s", "x", {})


# ------------------------------------------------------------------ procesar, cortar y retomar

class _CuentaFalsa:
    def __init__(self, limite_tras=None):
        self.extracciones, self.limite_tras = 0, limite_tras

    def json(self, etapa, modelo, sistema, mensaje, schema, esfuerzo="low", max_tokens=0):
        if etapa == "filtro":
            notas = [{"n": int(linea.split(". ", 1)[0]), "argentina": True, "categoria": "siniestro"}
                     for linea in mensaje.splitlines() if linea[:1].isdigit() and ". " in linea]
            return {"notas": notas}
        if self.limite_tras is not None and self.extracciones >= self.limite_tras:
            raise LimiteCuenta("límite", None)
        self.extracciones += 1
        return {"categoria": "siniestro", "siniestros": [dict(FICHA)], "contexto": None}

    def guardar_uso(self, extra=None):
        return {}


def _items(n):
    return {f"n_{i}": {"id": f"n_{i}", "titulo": f"Volcó un camión en la Ruta 40 cerca de Cafayate, caso {i}",
                       "bajada": "", "url": f"https://news.google.com/rss/articles/G{i}", "gn_id": f"G{i}", "clave": None,
                       "hash_titulo": f"h{i}", "medio": "Medio", "sitio": "medio.com.ar", "provincia_medio": "66",
                       "nivel_medio": None, "publicada": f"2026-11-{10 + i % 5:02d}T12:00:00+00:00",
                       "tipo_busqueda": "siniestro", "titulo_provisional": False,
                       "origenes": [{"tipo": "google_news", "consulta": "q", "provincia": "66", "termino": "vuelco"}]}
            for i in range(n)}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(historico, "DIR", tmp_path / "historico")
    monkeypatch.setattr(historico, "DIR_PRIVADO", tmp_path / "privado")
    monkeypatch.setattr(historico, "ARCHIVO_ITEMS", tmp_path / "privado" / "items.json.gz")
    monkeypatch.setattr(historico, "LOTE", 4)
    textos = {}

    def preparar(red, resolvedor, robots, it):
        it["texto"] = textos.setdefault(it["id"], "Texto de la nota del vuelco del camión en la RN 40.")

    monkeypatch.setattr(historico, "_preparar", preparar)
    monkeypatch.setattr(historico, "Resolvedor", lambda red: None)
    monkeypatch.setattr(historico, "Robots", lambda red: None)
    historico.guardar_items(_items(10))
    return tmp_path


def test_procesar_se_frena_en_el_limite_y_retoma_sin_repetir(entorno):
    silencio = lambda *a: None  # noqa: E731
    r1 = historico.procesar_historico(log=silencio, claude=_CuentaFalsa(limite_tras=6), red=object())
    assert r1["limite"] == "desconocido" and r1["conteo"]["siniestro"] == 6 and r1["faltan"] == 4
    assert len(historico._notas().por_id) == 6                              # lo hecho quedó guardado
    segunda = _CuentaFalsa()
    r2 = historico.procesar_historico(log=silencio, claude=segunda, red=object())
    assert r2["limite"] is None and segunda.extracciones == 4 and r2["faltan"] == 0
    notas = historico._notas().por_id
    assert len(notas) == 10 and all(n["origen"] == "historico" for n in notas.values())
    # las fichas no guardan títulos (pueden traer nombres)
    assert "Volcó un camión" not in (entorno / "historico" / "notas.jsonl").read_text(encoding="utf-8")


def test_cuenta_reintenta_los_cortes_de_red(monkeypatch):
    respuestas = [NS(stdout="", stderr="API Error: Unable to connect to API (ENOTFOUND)", returncode=1),
                  _salida(resultado={"categoria": "siniestro"})]
    c = ClaudeCuenta(ejecutable="claude", ejecutar=lambda a, **k: respuestas.pop(0))
    esperas = []
    c.dormir = esperas.append
    assert c.json("filtro", "m", "s", "x", {}) == {"categoria": "siniestro"} and esperas == [30]
    # un error que no es de red no se reintenta
    error = {"type": "result", "is_error": True, "result": "Invalid model"}
    c2 = ClaudeCuenta(ejecutable="claude", ejecutar=lambda a, **k: NS(stdout=json.dumps(error), stderr="", returncode=1))
    c2.dormir = esperas.append
    from radar_vial.claude import ErrorClaude
    with pytest.raises(ErrorClaude):
        c2.json("filtro", "m", "s", "x", {})
    assert esperas == [30]
