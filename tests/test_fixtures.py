"""Las notas anotadas usan valores válidos, y la comparación de medir_extraccion.py funciona (sin red ni API)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from medir_extraccion import cargar_anotadas, coincide, evaluar  # noqa: E402

from radar_vial import extraer  # noqa: E402

VALIDOS = {
    "hora_franja": extraer.FRANJAS, "tipo_via": extraer.TIPOS_VIA, "tipo_siniestro": extraer.TIPOS_SINIESTRO,
    "vehiculos": extraer.VEHICULOS, "grupos_etarios": extraer.GRUPOS_ETARIOS, "factores": extraer.FACTORES,
}


def _opciones(v):
    return v["uno_de"] if isinstance(v, dict) and "uno_de" in v else [v]


def test_veinte_notas_con_valores_validos():
    notas = cargar_anotadas()
    assert len(notas) == 20 and len({n["id"] for n in notas}) == 20
    for n in notas:
        assert "titulo" not in n and "texto" not in n  # no se guardan textos de terceros ni nombres
        for f in n.get("siniestros") or []:
            for campo, valores in VALIDOS.items():
                if campo not in f:
                    continue
                for v in _opciones(f[campo]):
                    for x in (v if isinstance(v, list) else [v]):
                        assert x in valores, f"{n['id']} {campo}: {x}"


def test_comparacion():
    assert coincide("tipo_siniestro", "vuelco", {"uno_de": ["despiste", "vuelco"]})
    assert coincide("vehiculos", ["moto", "auto"], ["auto", "moto"])
    assert coincide("localidad", "Banda del Río Salí", "banda del rio sali")
    assert coincide("via_contiene", "RN 11 km 1140", ["11", "1140"])
    assert not coincide("via_contiene", "RN 12", ["11"])
    assert coincide("provincia", "06", "Buenos Aires")


def test_evaluar_cuenta_aciertos_y_detecta_nombres():
    anotadas = [{"id": "x", "categoria": "siniestro", "siniestros": [{"fallecidos": 1, "vehiculos": ["auto"]}]}]
    resp = {"x": {"categoria": "siniestro", "contexto": None,
                  "siniestros": [{"fallecidos": 1, "vehiculos": ["auto", "moto"], "resumen": "Murió Juan Pérez."}]}}
    res = evaluar(anotadas, resp, {"x": "La víctima fue identificada como Juan Pérez, de 30 años."})
    assert res["aciertos"]["fallecidos"] == 1 and res["aciertos"]["vehiculos"] == 0
    assert any("PRIVACIDAD" in a for a in res["alertas"])
