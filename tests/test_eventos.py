"""Agrupación de fichas en eventos (sin red ni API)."""
from radar_vial.eventos import Desempate, agrupar, armar_eventos, asignar_ids, comparar, consolidar, ruta_y_km
from radar_vial.notas import Notas


def _geo(loc_id=None, loc=None, depto_id=None, prov="90"):
    return {"provincia_id": prov, "provincia": "Tucumán", "localidad_id": loc_id, "localidad": loc,
            "departamento_id": depto_id, "departamento": None, "lat": -26.8, "lon": -65.2,
            "nivel": "localidad" if loc_id else "provincia"}


BASE = {"fecha_hecho": "2026-11-18", "fecha_aproximada": False, "hora_franja": "madrugada", "provincia": "Tucumán",
        "provincia_id": "90", "departamento": None, "localidad": "Banda del Río Salí", "via": "RN 9 km 1290",
        "tipo_via": "ruta_nacional", "tipo_siniestro": "choque_frontal", "vehiculos": ["auto", "moto"], "fallecidos": 1,
        "heridos_graves": None, "heridos_leves": 2, "heridos_sin_detalle": None, "factores_mencionados": [],
        "grupos_etarios": ["joven"], "resumen": "Choque frontal entre un auto y una moto en la RN 9.", "confianza": "alta",
        "geo": _geo("90014020", "Banda del Río Salí", "90014")}


def _ficha(n, medio="Medio", hora="2026-11-18T10:00:00+00:00", fuente="completo", **cambios):
    f = {**BASE, **cambios}
    f.update({"_clave": f"n_{n}#0", "_id_nota": f"n_{n}", "_url": f"https://{medio.lower()}.com.ar/{n}",
              "_medio": medio, "_publicada": hora, "_fuente_texto": fuente})
    return f


# ------------------------------------------------------------------ casos pedidos

def test_misma_nota_en_cinco_medios_es_un_evento():
    medios = ["La Gaceta", "Contexto", "El Siglo", "Tucumán a las 7", "Infobae"]
    fichas = [_ficha(i, medio=m, hora=f"2026-11-18T1{i}:00:00+00:00",
                     # cada medio lo cuenta un poco distinto
                     tipo_siniestro="choque_sin_detalle" if i % 2 else "choque_frontal",
                     via="RN 9" if i == 3 else "RN 9 km 1290", hora_franja="desconocida" if i == 4 else "madrugada")
              for i, m in enumerate(medios)]
    eventos = agrupar(fichas)
    assert len(eventos) == 1
    r = consolidar(eventos[0], "ev_x")
    assert r["n_fuentes"] == 5 and len(r["fichas"]) == 5
    assert r["tipo_siniestro"] == "choque_frontal"  # el específico gana al "sin detalle"


def test_dos_choques_distintos_en_la_misma_ruta_el_mismo_dia():
    a = _ficha(1, via="RN 9 km 1290")
    b = _ficha(2, via="RN 9 km 1340", localidad="Las Cejas", vehiculos=["camion", "auto"], hora_franja="tarde",
               fallecidos=0, geo=_geo("90021010", "Las Cejas", "90021"))
    eventos = agrupar([a, b])
    assert len(eventos) == 2
    # aun sin kilómetro, otra localidad, otros vehículos y otro momento del día no alcanzan para fusionar
    b2 = {**b, "via": "RN 9"}
    assert len(agrupar([a, b2])) == 2


def test_cifra_de_fallecidos_que_se_actualiza_queda_la_mas_reciente():
    primera = _ficha(1, hora="2026-11-18T08:00:00+00:00", fallecidos=1, heridos_leves=None, heridos_graves=2)
    despues = _ficha(2, medio="Otro", hora="2026-11-19T09:00:00+00:00", fallecidos=2, heridos_leves=None, heridos_graves=1,
                     resumen="Choque frontal en la RN 9: murieron dos personas.")
    eventos = agrupar([primera, despues])
    assert len(eventos) == 1
    r = consolidar(eventos[0], "ev_x")
    assert r["fallecidos"] == 2 and r["heridos_graves"] == 1 and r["heridos_total"] == 1


# ------------------------------------------------------------------ más casos de borde

def test_dos_siniestros_de_una_misma_nota_no_se_fusionan():
    a = _ficha(1)
    b = {**_ficha(1), "_clave": "n_1#1"}
    assert len(agrupar([a, b])) == 2


def test_provincias_distintas_o_fechas_lejanas_nunca_se_fusionan():
    a = _ficha(1)
    otra_prov = _ficha(2, provincia_id="66", geo=_geo("66028050", "Salta", "66028", prov="66"))
    lejos = _ficha(3, fecha_hecho="2026-11-14")
    assert comparar(a, otra_prov)[0] is False
    assert comparar(a, lejos)[0] is False
    assert len(agrupar([a, otra_prov, lejos])) == 3


def test_rutas_distintas_son_contradiccion_dura():
    assert comparar(_ficha(1, via="RN 9"), _ficha(2, via="RN 38"))[0] is False
    assert ruta_y_km("Ruta Nacional 9, km 1.290") [1] == 9
    assert ruta_y_km("RP 2 km 45") == ("RP", 2, 45)


def test_vehiculos_que_no_coinciden_bajan_el_puntaje():
    ok_igual, p_igual = comparar(_ficha(1), _ficha(2))
    ok_otro, p_otro = comparar(_ficha(1), _ficha(2, vehiculos=["camion", "colectivo"]))
    assert ok_igual and ok_otro and p_otro < p_igual


class _ClaudeFalso:
    def __init__(self, respuesta):
        self.respuesta, self.llamadas = respuesta, 0

    def json(self, *a, **kw):
        self.llamadas += 1
        return self.respuesta


def test_ficha_de_solo_titulo_se_suma_solo_si_claude_lo_confirma(tmp_path):
    completa = _ficha(1)
    titulo = _ficha(2, fuente="titulo", confianza="baja", via=None, localidad=None, vehiculos=[], hora_franja="desconocida",
                    geo=_geo(prov="90"))
    assert len(agrupar([completa, titulo])) == 2  # sin desempate, lo dudoso queda aparte
    claude = _ClaudeFalso({"mismo_evento": 1, "seguridad": "media"})
    d = Desempate(claude, archivo=tmp_path / "dec.json")
    assert len(agrupar([completa, titulo], d)) == 1 and claude.llamadas == 1
    # la decisión queda guardada: no se vuelve a preguntar
    d.guardar()
    claude2 = _ClaudeFalso({"mismo_evento": None, "seguridad": "alta"})
    d2 = Desempate(claude2, archivo=tmp_path / "dec.json")
    assert len(agrupar([completa, titulo], d2)) == 1 and claude2.llamadas == 0


def test_claude_con_seguridad_baja_no_fusiona(tmp_path):
    completa = _ficha(1)
    # misma ruta y mismo tipo, pero otra localidad de otro departamento: dudoso, se consulta
    dudosa = _ficha(2, vehiculos=["auto", "camion"], via="RN 9", hora_franja="desconocida", localidad="Las Cejas",
                    geo=_geo("90021010", "Las Cejas", "90021"))
    claude = _ClaudeFalso({"mismo_evento": 1, "seguridad": "baja"})
    eventos = agrupar([completa, dudosa], Desempate(claude, archivo=tmp_path / "dec.json"))
    assert claude.llamadas == 1 and len(eventos) == 2   # Claude dijo "baja": no alcanza para fusionar
    claude_seguro = _ClaudeFalso({"mismo_evento": 1, "seguridad": "alta"})
    assert len(agrupar([completa, dudosa], Desempate(claude_seguro, archivo=tmp_path / "dec2.json"))) == 1


def test_ids_de_evento_se_conservan_al_rehacer():
    fichas = [_ficha(1), _ficha(2, medio="Otro")]
    ev1 = agrupar(fichas)
    ids1 = asignar_ids(ev1, [])
    anteriores = [consolidar(e, i) for e, i in zip(ev1, ids1)]
    # al día siguiente llega una nota más del mismo siniestro y otro siniestro distinto
    nuevo = _ficha(4, localidad="Las Cejas", via="RN 9 km 1340", vehiculos=["camion"], hora_franja="tarde",
                   geo=_geo("90021010", "Las Cejas", "90021"))
    ev2 = agrupar(fichas + [_ficha(3, medio="Tercero", hora="2026-11-19T10:00:00+00:00"), nuevo])
    ids2 = asignar_ids(ev2, anteriores)
    assert len(ev2) == 2
    grande = next(i for e, i in zip(ev2, ids2) if len(e.fichas) == 3)
    assert grande == ids1[0]
    assert len(set(ids2)) == 2


def test_factores_y_vehiculos_al_consolidar():
    a = _ficha(1, factores_mencionados=[{"factor": "alcohol", "presunto": True}], vehiculos=["auto"])
    b = _ficha(2, medio="Otro", factores_mencionados=[{"factor": "alcohol", "presunto": False},
                                                      {"factor": "velocidad", "presunto": False}], vehiculos=["auto", "moto"])
    r = consolidar(agrupar([a, b])[0], "ev")
    assert r["vehiculos"] == ["auto", "moto"]
    assert {"factor": "alcohol", "presunto": True} in r["factores_mencionados"]   # sigue presunto si alguna nota lo duda
    assert {"factor": "velocidad", "presunto": False} in r["factores_mencionados"]


def test_armar_eventos_desde_notas(tmp_path):
    notas = Notas(tmp_path / "notas.jsonl")
    for i, medio in enumerate(["A", "B"]):
        f = {k: v for k, v in BASE.items()}
        notas.guardar_nota({"id_nota": f"n_{i}", "url": f"https://{medio}.com.ar/{i}", "medio": medio, "sitio": f"{medio}.com.ar",
                            "publicada": f"2026-11-18T1{i}:00:00+00:00", "categoria": "siniestro", "fuente_texto": "completo",
                            "siniestros": [f], "contexto": None})
    eventos = armar_eventos(notas, log=lambda *a: None, archivo=tmp_path / "eventos.jsonl",
                            archivo_decisiones=tmp_path / "dec.json")
    assert len(eventos) == 1 and eventos[0]["n_fuentes"] == 2
    assert eventos[0]["id_evento"].startswith("ev_20261118_90_")
    # rehacer da el mismo id
    otra_vez = armar_eventos(notas, log=lambda *a: None, archivo=tmp_path / "eventos.jsonl",
                             archivo_decisiones=tmp_path / "dec.json")
    assert otra_vez[0]["id_evento"] == eventos[0]["id_evento"]


def test_kilometros_distintos_en_la_misma_localidad_no_impiden_fusionar():
    a = _ficha(1, via="RN 9 km 172")
    b = _ficha(2, medio="Otro", via="RN 9 km 473")
    ok, p = comparar(a, b)
    assert ok and p >= 4   # mismo lugar, ruta y vehículos: un medio informó mal el kilómetro
    lejos = _ficha(3, via="RN 9 km 473", localidad="Las Cejas", geo=_geo("90021010", "Las Cejas", "90021"))
    assert comparar(a, lejos)[0] is False


def test_calles_distintas_en_la_misma_localidad_separan_siniestros():
    a = _ficha(1, via="Rotonda de bulevar Sarmiento y Av. Universidad", vehiculos=["auto", "bicicleta"])
    b = _ficha(2, via="Bv. Alvear y Entre Ríos", vehiculos=["auto", "moto"])
    ok, p = comparar(a, b)
    assert not ok                 # dos esquinas distintas: contradicción dura
    mismo = _ficha(3, via="Bulevar Sarmiento y Universidad", vehiculos=["auto", "bicicleta"])
    assert comparar(a, mismo)[1] >= 4


def test_errores_de_tipeo_y_nombre_de_la_localidad_en_la_via():
    a = _ficha(1, via="Av. Chacabuco y acceso oeste", localidad="Posadas")
    b = _ficha(2, via="Rotonda de Av. Costanera y Av. Chabacuco", localidad="Posadas")
    assert comparar(a, b)[0] is True
    c = _ficha(3, via="Colectora de ingreso a Mocoretá", localidad="Mocoretá")
    d = _ficha(4, via="Colectora Este y calle Virgen de Itatí", localidad="Mocoretá")
    assert comparar(c, d)[0] is True


def test_una_nota_con_un_dato_mal_no_bloquea_al_evento():
    fichas = [_ficha(i, medio=f"M{i}", via="RN 9 km 1290") for i in range(3)]
    mal = _ficha(9, medio="Mal", via="RN 9 km 1600")             # contradice a una sola de las tres
    eventos = agrupar(fichas[:1] + [mal] + fichas[1:])
    assert len(eventos) == 1 and len(eventos[0].fichas) == 4


def test_contradiccion_absoluta_con_una_sola_ficha_deja_afuera():
    # evento con una ficha en la RN 9 y otra solo de título sin ruta: una ficha nueva en la RN 38 no entra
    a = _ficha(1, via="RN 9")
    b = _ficha(2, medio="Otro", via=None, fuente="titulo", confianza="baja")
    c = _ficha(3, medio="Tercero", via="RN 38")
    from radar_vial.eventos import Evento

    ev = Evento(a)
    ev.fichas.append(b)
    assert ev.evaluar(c)[0] is False
    # tampoco otra provincia, aunque una de las fichas no tenga provincia
    sin_prov = _ficha(4, provincia_id=None, geo={})
    ev2 = Evento(a)
    ev2.fichas.append(sin_prov)
    otra = _ficha(5, provincia_id="66", geo=_geo("66028050", "Salta", "66028", prov="66"))
    assert ev2.evaluar(otra)[0] is False


def test_esquina_distinta_en_una_sola_nota_es_tolerable():
    from radar_vial.eventos import Evento

    base = dict(via="Av. Libertador y calle Catamarca", localidad="San Juan")
    ev = Evento(_ficha(1, **base))
    for i in (2, 3):
        ev.fichas.append(_ficha(i, medio=f"M{i}", **base))
    mal = _ficha(9, medio="Mal", via="Av. Rioja y calle Laprida", localidad="San Juan")   # una sola la contradice
    assert ev.evaluar(_ficha(8, medio="Nueva", **base))[0] is True
    ev.fichas.append(mal)
    assert ev.evaluar(_ficha(7, medio="Otra", **base))[0] is True


# ------------------------------------------------------------------ casos de la revisión del 20-11-2026

def test_nota_de_seguimiento_dias_despues_se_une_solo_si_claude_lo_confirma(tmp_path):
    # Pampa Almirón: la nota del 19 (fecha aproximada = publicación) habla del despiste del 14
    original = _ficha(1, fecha_hecho="2026-11-14", hora="2026-11-14T12:00:00+00:00")
    seguimiento = _ficha(2, fecha_hecho="2026-11-19", fecha_aproximada=True, hora="2026-11-19T12:00:00+00:00")
    assert len(agrupar([original, seguimiento])) == 2            # con todo igual, tampoco se fusiona sola
    claude = _ClaudeFalso({"mismo_evento": 1, "seguridad": "alta"})
    eventos = agrupar([original, seguimiento], Desempate(claude, archivo=tmp_path / "d.json"))
    assert len(eventos) == 1 and claude.llamadas == 1
    registro = consolidar(eventos[0], "ev")
    assert registro["fecha_hecho"] == "2026-11-14" and registro["fallecidos"] == 1   # una muerte, no dos


def test_seguimiento_sin_coincidencia_fuerte_o_con_fecha_clara_no_se_consulta(tmp_path):
    original = _ficha(1, fecha_hecho="2026-11-14", hora="2026-11-14T12:00:00+00:00")
    claude = _ClaudeFalso({"mismo_evento": 1, "seguridad": "alta"})
    # otra localidad y otra calle: ni se pregunta
    flojo = _ficha(2, fecha_hecho="2026-11-19", fecha_aproximada=True, hora="2026-11-19T12:00:00+00:00",
                   localidad="Las Cejas", via="Av. Mitre", vehiculos=["camion"], geo=_geo("90021010", "Las Cejas", "90021"))
    assert len(agrupar([original, flojo], Desempate(claude, archivo=tmp_path / "a.json"))) == 2 and claude.llamadas == 0
    # fecha clara cinco días después: es otro siniestro aunque todo lo demás coincida
    otro = _ficha(3, fecha_hecho="2026-11-19", hora="2026-11-19T12:00:00+00:00")
    assert comparar(original, otro)[0] is False
    # la fecha aproximada es anterior a la clara: el hecho no pudo pasar después de publicarse
    previo = _ficha(4, fecha_hecho="2026-11-10", fecha_aproximada=True, hora="2026-11-10T12:00:00+00:00")
    assert comparar(original, previo)[0] is False


def test_provincia_inferida_no_separa_el_mismo_siniestro(tmp_path):
    # Canals (Córdoba): un titular sin lugar llegó por una búsqueda de La Pampa
    real = _ficha(1, via="RN 8 km 473", localidad="Canals", vehiculos=["camion"],
                  geo=_geo("14182040", "Canals", "14182", prov="14"))
    inferida = _ficha(2, fuente="titulo", via="RN 8", localidad=None, vehiculos=["camion"], hora_franja="desconocida",
                      geo={"provincia_id": "42", "provincia": "La Pampa", "nivel": "provincia",
                           "provincia_inferida": True, "inferida_de": "busqueda"})
    assert comparar(real, inferida)[0] is True
    claude = _ClaudeFalso({"mismo_evento": 1, "seguridad": "alta"})
    eventos = agrupar([real, inferida], Desempate(claude, archivo=tmp_path / "d.json"))
    assert len(eventos) == 1
    assert consolidar(eventos[0], "ev")["provincia_id"] == "14"      # gana la provincia confirmada
    confirmada = _ficha(3, geo=_geo(prov="42"))
    assert comparar(real, confirmada)[0] is False                    # dos provincias confirmadas: distintos


def test_calles_numeradas_son_esquinas_distintas():
    from radar_vial.eventos import palabras_via

    pico = dict(localidad="General Pico", geo=_geo("42021030", "General Pico", "42021", prov="42"))
    a, b = _ficha(1, via="Calles 19 y 46", **pico), _ficha(2, via="Calles 21 y 20", **pico)
    assert palabras_via("Calles 19 y 46") == {"19", "46"}
    assert comparar(a, b)[0] is False and len(agrupar([a, b])) == 2
    assert comparar(a, _ficha(3, via="calle 19 esquina 46", **pico))[0] is True
    assert palabras_via("RN 8 km 473") == set()                      # en una ruta los números no son calles


def test_km_lejanos_con_una_localidad_sin_ubicar_no_separan():
    ubicada = _ficha(1, via="RN 8 km 172", localidad="Canals", geo=_geo("14182040", "Canals", "14182", prov="14"))
    sin_ubicar = _ficha(2, via="RN 8 km 473", localidad="entre Canals y La Carlota", geo=_geo(prov="14"))
    assert comparar(ubicada, sin_ubicar)[0] is True


def test_una_nota_posterior_no_borra_una_muerte():
    from radar_vial.eventos import Evento

    ev = Evento(_ficha(1, fallecidos=1, hora="2026-11-18T10:00:00+00:00"))
    ev.fichas.append(_ficha(2, medio="Otro", fallecidos=0, hora="2026-11-18T15:00:00+00:00"))
    assert consolidar(ev, "ev")["fallecidos"] == 1
