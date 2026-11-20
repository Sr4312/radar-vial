"""Normalización geográfica con la API Georef (datos.gob.ar): ids oficiales y centroide de cada ficha.

Para cada ficha de siniestro se busca, en este orden:
1. la localidad dentro de su provincia ("la capital" se traduce a la capital de la provincia);
2. si no aparece, el nombre como departamento (las notas a veces nombran el departamento: "Guaymallén");
3. el departamento que informa la nota;
4. si nada aparece, el centroide de la provincia (nivel "provincia").
Si la nota no dice la provincia pero sí la localidad, y Georef la encuentra en una sola provincia (o en la del
medio), la provincia se completa y queda marcada `provincia_inferida`.
Las respuestas de Georef se guardan en data/cache/georef.json (no cambian de un día para otro).
"""
from __future__ import annotations

import json
import re
import threading

from . import config
from .texto import normalizar

ARCHIVO = config.DIR_CACHE / "georef.json"
BASE = "https://apis.datos.gob.ar/georef/api"
_CAMPOS_LOC = "id,nombre,departamento.id,departamento.nombre,provincia.id,provincia.nombre,centroide"

_CAPITAL = re.compile(r"^(la\s+)?(ciudad\s+)?capital(\s+\w+)?$")
_PREFIJOS = re.compile(r"^(la\s+)?(ciudad|localidad|paraje|pueblo|zona|barrio)\s+(de\s+)?", re.I)


class Georef:
    def __init__(self, red=None, archivo=ARCHIVO):
        self.archivo = archivo
        self.red = red
        self._cache: dict[str, list] = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}
        self._lock = threading.Lock()
        self.consultas = 0

    def _consultar(self, recurso: str, **params) -> list[dict]:
        clave = recurso + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        with self._lock:
            if clave in self._cache:
                return self._cache[clave]
        if self.red is None:
            from .red import Red

            self.red = Red(pausa=0.2)
        try:
            r = self.red.get(f"{BASE}/{recurso}", params=params)
            datos = r.json().get(recurso, []) if r.ok else None
        except Exception:  # noqa: BLE001 - sin Georef la ficha queda sin normalizar, no se cae la corrida
            datos = None
        if datos is None:
            return []
        with self._lock:
            self._cache[clave] = datos
            self.consultas += 1
        return datos

    def guardar(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(json.dumps(self._cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    # ------------------------------------------------------------------ búsquedas

    @staticmethod
    def _mejor(resultados: list[dict], nombre: str) -> dict | None:
        """Prefiere el nombre exacto (sin acentos) y, a igualdad, el id más corto (localidad, no barrio)."""
        if not resultados:
            return None
        n = normalizar(nombre)
        return sorted(resultados, key=lambda x: (normalizar(x["nombre"]) != n, len(x["id"])))[0]

    def localidad(self, nombre: str, provincia_id: str | None) -> dict | None:
        params = {"nombre": nombre, "campos": _CAMPOS_LOC, "max": 10}
        if provincia_id:
            params["provincia"] = provincia_id
        return self._mejor(self._consultar("localidades", **params), nombre) if provincia_id else None

    def localidades_en_todo_el_pais(self, nombre: str) -> list[dict]:
        return self._consultar("localidades", nombre=nombre, campos=_CAMPOS_LOC, max=10)

    def departamento(self, nombre: str, provincia_id: str) -> dict | None:
        res = self._consultar("departamentos", nombre=nombre, provincia=provincia_id,
                              campos="id,nombre,provincia.id,provincia.nombre,centroide", max=5)
        return self._mejor(res, nombre)

    def provincia(self, provincia_id: str) -> dict | None:
        res = self._consultar("provincias", id=provincia_id, campos="id,nombre,centroide", max=1)
        return res[0] if res else None


def _limpiar_lugar(texto: str | None) -> str:
    t = (texto or "").strip()
    t = re.split(r"[,;(]", t)[0].strip()        # "Las Catitas, Santa Rosa" -> "Las Catitas"
    return _PREFIJOS.sub("", t).strip()


def _desde_localidad(loc: dict, nivel: str = "localidad", inferida: bool = False) -> dict:
    return {"provincia_id": loc["provincia"]["id"], "provincia": loc["provincia"]["nombre"],
            "departamento_id": loc["departamento"]["id"], "departamento": loc["departamento"]["nombre"],
            "localidad_id": loc["id"], "localidad": loc["nombre"],
            "lat": round(loc["centroide"]["lat"], 5), "lon": round(loc["centroide"]["lon"], 5),
            "nivel": nivel, "provincia_inferida": inferida}


def _desde_provincia(prov_id: str, georef: Georef, nivel="provincia", depto: dict | None = None) -> dict | None:
    p = config.provincia_por_id(prov_id)
    if p is None:
        return None
    if depto:
        lat, lon = depto["centroide"]["lat"], depto["centroide"]["lon"]
    elif p.get("centro"):  # Tierra del Fuego: el centroide oficial cae en la Antártida
        lat, lon = p["centro"]["lat"], p["centro"]["lon"]
    else:
        g = georef.provincia(prov_id)
        if g is None:
            return {"provincia_id": prov_id, "provincia": p["nombre"], "departamento_id": None, "departamento": None,
                    "localidad_id": None, "localidad": None, "lat": None, "lon": None, "nivel": "provincia",
                    "provincia_inferida": False}
        lat, lon = g["centroide"]["lat"], g["centroide"]["lon"]
    return {"provincia_id": prov_id, "provincia": p["nombre"],
            "departamento_id": depto["id"] if depto else None, "departamento": depto["nombre"] if depto else None,
            "localidad_id": None, "localidad": None, "lat": round(lat, 5), "lon": round(lon, 5),
            "nivel": nivel, "provincia_inferida": False}


def _provincia_por_pistas(georef: Georef, provincia_medio: str | None, provincias_busqueda) -> dict | None:
    """Última opción, si la nota no dice la provincia: la del medio (si las búsquedas no la contradicen) o la
    única provincia por cuyas búsquedas de Google News llegó la nota. Queda marcada como inferida."""
    busqueda = set(provincias_busqueda or [])
    elegida, origen = None, None
    if provincia_medio and (not busqueda or provincia_medio in busqueda):
        elegida, origen = provincia_medio, "medio"
    elif not provincia_medio and len(busqueda) == 1:   # si el medio dice otra provincia, no se adivina
        elegida, origen = next(iter(busqueda)), "busqueda"
    if not elegida:
        return None
    geo = _desde_provincia(elegida, georef)
    if geo:
        geo.update(provincia_inferida=True, inferida_de=origen)
    return geo


def normalizar_ficha(f: dict, georef: Georef, provincia_medio: str | None = None, provincias_busqueda=None) -> dict:
    """Devuelve el bloque `geo` de una ficha. Nivel: localidad, departamento, provincia o ninguno."""
    prov_id = f.get("provincia_id")
    lugar = _limpiar_lugar(f.get("localidad"))
    if prov_id and lugar and _CAPITAL.match(normalizar(lugar)):
        lugar = config.provincia_por_id(prov_id).get("capital", lugar)

    if prov_id:
        if lugar:
            loc = georef.localidad(lugar, prov_id)
            if loc:
                return _desde_localidad(loc)
            depto = georef.departamento(lugar, prov_id)
            if depto:
                return _desde_provincia(prov_id, georef, "departamento", depto)
        if f.get("departamento"):
            depto = georef.departamento(_limpiar_lugar(f["departamento"]), prov_id)
            if depto:
                return _desde_provincia(prov_id, georef, "departamento", depto)
        return _desde_provincia(prov_id, georef)

    # Sin provincia: se infiere solo si la localidad no deja dudas
    if lugar and not _CAPITAL.match(normalizar(lugar)):
        candidatas = [x for x in georef.localidades_en_todo_el_pais(lugar) if normalizar(x["nombre"]) == normalizar(lugar)]
        provincias = {x["provincia"]["id"] for x in candidatas}
        if len(provincias) == 1:
            return _desde_localidad(georef._mejor(candidatas, lugar), inferida=True)
        if provincia_medio and provincia_medio in provincias:
            return _desde_localidad(georef._mejor([x for x in candidatas if x["provincia"]["id"] == provincia_medio], lugar),
                                    inferida=True)
    por_pistas = _provincia_por_pistas(georef, provincia_medio, provincias_busqueda)
    if por_pistas:
        return por_pistas
    return {"provincia_id": None, "provincia": None, "departamento_id": None, "departamento": None,
            "localidad_id": None, "localidad": None, "lat": None, "lon": None, "nivel": "ninguno",
            "provincia_inferida": False}


def completar_notas(notas, georef: Georef, forzar: bool = False) -> int:
    """Agrega `geo` a las fichas de siniestro que no lo tienen. Devuelve cuántas normalizó."""
    hechas = 0
    for n in notas.todas():
        for f in n.get("siniestros") or []:
            # las que quedaron sin lugar se reintentan (las respuestas de Georef están en caché)
            if forzar or "geo" not in f or f["geo"].get("nivel") == "ninguno":
                f["geo"] = normalizar_ficha(f, georef, n.get("provincia_medio"), n.get("provincias_busqueda"))
                hechas += 1
    return hechas
