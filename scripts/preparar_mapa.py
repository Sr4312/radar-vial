"""Genera docs/data/provincias.geojson (liviano) a partir de la cartografía oficial del IGN.

Uso: python scripts/preparar_mapa.py   (se corre una sola vez; el resultado se sube al repo)

- Fuente: servicio WFS del Instituto Geográfico Nacional, capa ign:provincia (incluye Islas Malvinas e islas
  del Atlántico Sur en Tierra del Fuego).
- Se simplifican los contornos (unos 2 km de tolerancia) y se redondean las coordenadas: alcanza para un mapa
  de provincias y baja el archivo de más de 100 MB a unos cientos de KB.
- El sector antártico de Tierra del Fuego no se dibuja: la proyección de los mapas web no puede mostrar el
  polo. El tablero lo aclara en una nota junto al mapa.
Necesita shapely (pip install shapely).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar_vial import config  # noqa: E402

WFS = ("https://wms.ign.gob.ar/geoserver/ign/ows?service=WFS&version=1.0.0&request=GetFeature"
       "&typeName=ign:provincia&outputFormat=application/json")
TOLERANCIA = 0.02        # grados (unos 2 km)
AREA_MINIMA = 0.0005     # grados cuadrados: islotes más chicos no se dibujan (salvo en Tierra del Fuego)
LIMITE_SUR = -60.0       # todo lo que esté al sur es sector antártico


def _poligonos(geom):
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]


def _redondear(obj, decimales=3):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(obj[0], decimales), round(obj[1], decimales)]
        return [_redondear(x, decimales) for x in obj]
    return obj


def main() -> None:
    rec = config.general()["recoleccion"]
    r = requests.get(WFS, headers={"User-Agent": rec["user_agent"]}, timeout=300)
    r.raise_for_status()
    datos = r.json()
    provincias = {p["id"]: p for p in config.provincias()}
    salida = []
    for f in datos["features"]:
        pid = f["properties"]["in1"]
        geom = shape(f["geometry"])
        partes = []
        for pol in _poligonos(geom):
            if pid == "94" and pol.bounds[3] < LIMITE_SUR:   # sector antártico
                continue
            if pol.area < AREA_MINIMA and pid != "94":
                continue
            simple = pol.simplify(TOLERANCIA, preserve_topology=True)
            if not simple.is_empty:
                partes.append(simple)
        geom = MultiPolygon([p for g in partes for p in _poligonos(g) if isinstance(p, Polygon)])
        salida.append({"type": "Feature",
                       "properties": {"id": pid, "nombre": provincias[pid]["corto"]},
                       "geometry": {"type": mapping(geom)["type"], "coordinates": _redondear(mapping(geom)["coordinates"])}})
    salida.sort(key=lambda f: f["properties"]["id"])
    destino = config.DIR_DOCS_DATA / "provincias.geojson"
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps({"type": "FeatureCollection",
                        "fuente": "Instituto Geográfico Nacional (IGN), capa ign:provincia, simplificada",
                        "features": salida}, ensure_ascii=False, separators=(",", ":"))
    destino.write_text(texto, encoding="utf-8")
    print(f"{len(salida)} provincias -> {destino.relative_to(config.RAIZ)} ({len(texto) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
