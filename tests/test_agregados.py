"""Datos del dashboard (sin red ni API)."""
import json
from datetime import datetime, timedelta, timezone

from radar_vial.agregados import _serie, agrupar_contexto, etiqueta_ruta, generar, resumen_semana

ART = timezone(timedelta(hours=-3))


def _ev(i, fecha, prov="90", muertos=0, heridos=1, solo=False, via="RN 9 km 1290"):
    return {"id_evento": f"ev_{i}", "fecha_hecho": fecha, "fecha_aproximada": False, "hora_franja": "noche",
            "provincia_id": prov, "localidad": "X", "lat": -26.8, "lon": -65.2, "nivel_geo": "localidad", "via": via,
            "tipo_via": "ruta_nacional", "tipo_siniestro": "choque_frontal", "vehiculos": ["auto"], "fallecidos": muertos,
            "heridos_graves": None, "heridos_leves": heridos, "heridos_sin_detalle": None, "heridos_total": heridos,
            "factores_mencionados": [], "grupos_etarios": [], "resumen": "r", "confianza": "alta", "solo_titulos": solo,
            "fuentes": [{"medio": "M", "url": f"https://m.com.ar/{i}", "publicada": fecha, "texto": "completo"}],
            "fichas": [f"n_{i}#0"], "n_fuentes": 1}


def test_etiqueta_de_ruta():
    assert etiqueta_ruta("RN 9 km 1290") == "RN 9"
    assert etiqueta_ruta("Ruta Provincial 6") == "RP 6"
    assert etiqueta_ruta("Ruta 153") == "Ruta 153"
    assert etiqueta_ruta("Av. Rivadavia y Nazca") is None


def test_semana_completa_termina_ayer_y_compara_con_la_anterior():
    eventos = [_ev(1, "2026-11-19", muertos=2), _ev(2, "2026-11-13"), _ev(3, "2026-11-12", prov="66"),
               _ev(4, "2026-11-20"), _ev(5, "2026-11-10", solo=True)]
    r = resumen_semana(_serie(eventos), corte=datetime(2026, 11, 19).date())
    assert (r["desde"], r["hasta"]) == ("2026-11-13", "2026-11-19")
    assert r["actual"]["siniestros"] == 2 and r["actual"]["fallecidos"] == 2   # el del 20 (hoy) no entra
    assert r["previo"]["siniestros"] == 2 and r["previo"]["siniestros_solo_titulos"] == 1
    assert r["variacion"]["siniestros"] == 0.0 and r["variacion"]["fallecidos"] is None   # sin base no hay %
    assert r["dias_en_carga"] == ["2026-11-18", "2026-11-19"]


def test_serie_por_provincia_y_solo_titulos():
    s = _serie([_ev(1, "2026-11-19", muertos=1), _ev(2, "2026-11-19", prov="66", solo=True, muertos=1),
                {**_ev(3, "2026-11-19"), "provincia_id": None}])
    d = s["dias"]["2026-11-19"]
    assert d["total"] == [3, 2, 3, 1, 1, 1]
    assert d["provincias"]["66"] == [1, 1, 1, 1, 1, 1] and len(d["provincias"]) == 2   # sin provincia: solo el total


def test_contexto_de_varios_medios_se_agrupa():
    def nota(i, medio, resumen, subtipo="control_alcoholemia", prov="14", publicada="2026-11-19T10:00:00+00:00"):
        return {"id_nota": f"n{i}", "categoria": "contexto", "medio": medio, "url": f"https://{medio}/{i}",
                "publicada": publicada, "contexto": {"subtipo": subtipo, "ambito": "provincial", "provincia_id": prov,
                                                     "fecha": publicada[:10], "organismo": "Policía Caminera",
                                                     "dato_clave": "120 controles positivos", "resumen": resumen}}
    notas = [nota(1, "a.com", "La Policía Caminera de Córdoba informó 120 controles de alcoholemia positivos el fin de semana."),
             nota(2, "b.com", "Córdoba: la Caminera detectó 120 conductores con alcoholemia positiva durante el fin de semana."),
             nota(3, "c.com", "Comenzó la campaña de verano de seguridad vial en las rutas cordobesas.", subtipo="campana"),
             nota(4, "d.com", "La Caminera de Córdoba registró 120 casos de alcoholemia positiva.", prov="82")]
    grupos = agrupar_contexto(notas, "2026-11-01")
    assert len(grupos) == 3
    grande = next(g for g in grupos if len(g["fuentes"]) == 2)
    assert {f["medio"] for f in grande["fuentes"]} == {"a.com", "b.com"} and "_palabras" not in grande


def test_generar_escribe_los_archivos_sin_datos_internos(tmp_path):
    ahora = datetime(2026, 11, 20, 6, 17, tzinfo=ART)
    r = generar(tmp_path, ahora=ahora, eventos=[_ev(1, "2026-11-19"), _ev(2, "2026-09-01")], notas=[])
    assert r["hasta"] == "2026-11-19"
    for nombre in ("meta.json", "eventos.json", "serie_diaria.json", "resumen_semana.json", "contexto.json"):
        assert (tmp_path / nombre).exists()
    eventos = json.loads((tmp_path / "eventos.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in eventos] == ["ev_1"]          # solo los últimos 31 días
    assert "fichas" not in eventos[0] and eventos[0]["ruta"] == "RN 9" and eventos[0]["n_fuentes"] == 1
    assert "heridos_graves" not in eventos[0]          # los campos vacíos no se publican
    serie = json.loads((tmp_path / "serie_diaria.json").read_text(encoding="utf-8"))
    assert "2026-09-01" in serie["dias"]                    # el histórico es completo
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert sum(p["poblacion"] for p in meta["provincias"]) == 45892285


def test_sin_comparacion_si_el_periodo_anterior_es_previo_al_registro():
    from datetime import date

    eventos = [_ev(1, "2026-11-19"), _ev(2, "2026-11-18"), _ev(3, "2026-11-12")]   # el 12 es una nota tardía suelta
    r = resumen_semana(_serie(eventos), corte=date(2026, 11, 19), inicio_cobertura=date(2026, 11, 18))
    assert r["previo_completo"] is False and r["periodo_completo"] is False
    assert all(v is None for v in r["variacion"].values())
    r2 = resumen_semana(_serie(eventos), corte=date(2026, 12, 9), inicio_cobertura=date(2026, 11, 18))
    assert r2["previo_completo"] is True and r2["periodo_completo"] is True
