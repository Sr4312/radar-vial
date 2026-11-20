"""Deduplicación de URLs y títulos (sin red ni claves)."""
from radar_vial.historial import (
    Historial,
    canonizar_url,
    clave_url,
    hash_titulo,
    quitar_medio,
    titulo_distintivo,
)

NOTA = "https://www.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html"


def test_misma_nota_con_variantes_da_la_misma_clave():
    variantes = [
        NOTA,
        "http://www.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html",
        "https://lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html",
        "https://www.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html?utm_source=twitter&utm_medium=social",
        "https://www.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html?fbclid=IwAR0abc",
        "https://www.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html#comentarios",
        "https://m.lagaceta.com.ar/nota/1080001/actualidad/choque-ruta-9.html",
        "  https://www.lagaceta.com.ar//nota/1080001/actualidad/choque-ruta-9.html  ",
    ]
    claves = {clave_url(u) for u in variantes}
    assert len(claves) == 1


def test_versiones_amp_y_barra_final():
    base = "https://www.infobae.com/sociedad/2026/11/18/choque-en-la-ruta-2"
    assert canonizar_url(base + "/") == canonizar_url(base)
    assert canonizar_url(base + "/amp/") == canonizar_url(base)
    assert canonizar_url("https://www.infobae.com/amp/sociedad/2026/11/18/choque-en-la-ruta-2") == canonizar_url(base)
    assert canonizar_url(base + "?outputType=amp") == canonizar_url(base)
    assert canonizar_url("https://amp.medio.com.ar/nota-123.amp.html") == canonizar_url("https://medio.com.ar/nota-123.html")


def test_parametros_que_identifican_la_nota_se_conservan():
    a = "https://www.medio.com.ar/nota.php?id=123"
    b = "https://www.medio.com.ar/nota.php?id=456"
    assert clave_url(a) != clave_url(b)
    # el orden de los parámetros no importa
    assert canonizar_url("https://medio.com.ar/n?b=2&a=1") == canonizar_url("https://medio.com.ar/n?a=1&b=2")


def test_notas_distintas_del_mismo_medio_no_se_confunden():
    assert clave_url(NOTA) != clave_url(NOTA.replace("1080001", "1080002"))


def test_quitar_medio_solo_si_coincide():
    assert quitar_medio("Choque frontal en la RN 9 - La Gaceta", "La Gaceta") == "Choque frontal en la RN 9"
    # un guion que es parte del título no se toca
    assert quitar_medio("Choque en la RN 9 - dos heridos", "La Gaceta") == "Choque en la RN 9 - dos heridos"
    assert quitar_medio("Choque en la RN 9", None) == "Choque en la RN 9"


def test_titulos_genericos_no_se_usan_para_deduplicar():
    generico = "Murió un motociclista tras un choque"
    assert not titulo_distintivo(generico)
    assert hash_titulo(generico) is None
    distintivo = "Tragedia en la Ruta 40: un camión embistió a un auto cerca de Cafayate y hay tres heridos"
    assert titulo_distintivo(distintivo)
    # mayúsculas, acentos y signos no cambian el hash
    assert hash_titulo(distintivo) == hash_titulo(distintivo.upper().replace("ó", "o") + "!")


def test_historial_reconoce_por_cualquier_clave(tmp_path):
    h = Historial(tmp_path / "historial.jsonl")
    item_gn = {"gn_id": "CBMiAbc", "hash_titulo": "h1"}
    h.registrar(item_gn, "sin_resolver")
    assert h.buscar({"gn_id": "CBMiAbc"}) is not None
    assert not h.ya_procesada(item_gn)          # reintentable
    # la misma nota, ya resuelta, llega con su URL: se completa el mismo registro
    h.registrar({"gn_id": "CBMiAbc", "clave": clave_url(NOTA)}, "siniestro", id_nota="n_1")
    assert h.ya_procesada({"clave": clave_url(NOTA + "?utm_source=x")})
    assert len(h.registros) == 1


def test_reintentos_se_agotan(tmp_path):
    h = Historial(tmp_path / "historial.jsonl")
    item = {"clave": clave_url(NOTA)}
    for _ in range(3):
        assert not h.ya_procesada(item)
        h.registrar(item, "error_descarga")
    assert h.ya_procesada(item)


def test_historial_no_guarda_titulos_y_persiste(tmp_path):
    archivo = tmp_path / "historial.jsonl"
    h = Historial(archivo)
    h.registrar({"clave": "abc", "titulo": "Nombre Apellido murió en un choque"}, "siniestro")
    h.guardar()
    contenido = archivo.read_text(encoding="utf-8")
    assert "Apellido" not in contenido
    assert Historial(archivo).ya_procesada({"clave": "abc"})


def test_poda_de_registros_viejos(tmp_path):
    h = Historial(tmp_path / "historial.jsonl")
    h.registrar({"clave": "nuevo"}, "siniestro")
    viejo = h.registrar({"clave": "viejo"}, "siniestro")
    viejo["visto"] = "2026-01-01T00:00:00+00:00"
    assert h.podar(dias=90) == 1
    assert h.buscar({"clave": "viejo"}) is None
    assert h.buscar({"clave": "nuevo"}) is not None


def test_el_mismo_titulo_en_otro_medio_o_semanas_despues_es_otra_nota(tmp_path):
    from datetime import datetime, timedelta, timezone

    titulo = "Un colectivo de larga distancia volcó cerca de Cafayate y hay doce pasajeros lesionados"
    assert hash_titulo(titulo, "a.com.ar") != hash_titulo(titulo, "b.com.ar")
    h = Historial(tmp_path / "historial.jsonl")
    item = {"gn_id": "G1", "hash_titulo": hash_titulo(titulo, "a.com.ar")}
    r = h.registrar(item, "siniestro")
    assert h.ya_procesada({"gn_id": "G2", "hash_titulo": item["hash_titulo"]})          # misma nota, otro id
    assert not h.ya_procesada({"gn_id": "G3", "hash_titulo": hash_titulo(titulo, "b.com.ar")})
    r["visto"] = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    assert not h.ya_procesada({"gn_id": "G4", "hash_titulo": item["hash_titulo"]})      # 20 días después: otra nota
    assert h.ya_procesada({"gn_id": "G1"})                                              # por su id se la sigue reconociendo


def test_los_alias_persisten_y_no_cambian_el_estado(tmp_path):
    archivo = tmp_path / "historial.jsonl"
    h = Historial(archivo)
    r = h.registrar({"gn_id": "G1", "clave": "link"}, "solo_titulo", id_nota="n_1")
    h.registrar({"gn_id": "G1", "clave": "canonica"}, "siniestro", id_nota="n_1")       # la clave del link queda de alias
    h.agregar_alias(r, {"gn_id": "G2"})
    h.guardar()
    h2 = Historial(archivo)
    for item in ({"clave": "link"}, {"clave": "canonica"}, {"gn_id": "G2"}):
        assert h2.buscar(item)["estado"] == "siniestro"
    assert len(h2.registros) == 1 and not list(tmp_path.glob("*.tmp"))
