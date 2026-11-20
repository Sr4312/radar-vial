"""Rutas del proyecto y carga de la configuración (config/*.yaml y .env)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"
DIR_DATA = RAIZ / "data"
DIR_CACHE = DIR_DATA / "cache"
DIR_TEXTOS = DIR_CACHE / "textos"   # texto completo de las notas: temporal y fuera de git
DIR_DOCS = RAIZ / "docs"
DIR_DOCS_DATA = DIR_DOCS / "data"
DIR_SALIDA = RAIZ / "salida"        # vistas previas y reportes locales (fuera de git)
DIR_TESTS = RAIZ / "tests"


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Carga variables de un .env local (ignorado por git), sin pisar las que ya existen en el entorno.

    Formato: una `CLAVE=valor` por línea; se aceptan comentarios con `#` y comillas alrededor del valor.
    """
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor


cargar_env()


def secreto(nombre: str) -> str:
    """Variable de entorno sin espacios ni saltos de línea (al pegar un secreto suele colarse un Enter)."""
    return (os.environ.get(nombre) or "").strip()


def cargar_yaml(nombre: str) -> dict:
    with open(DIR_CONFIG / nombre, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def general() -> dict:
    """config/config.yaml: modelos, límites, ventanas y parámetros de red."""
    return cargar_yaml("config.yaml")


@lru_cache(maxsize=1)
def provincias() -> list[dict]:
    """Las 24 jurisdicciones (config/provincias.yaml), con id INDEC/Georef, nombre y término de búsqueda."""
    return cargar_yaml("provincias.yaml")["provincias"]


def provincia_por_id(id_prov: str) -> dict | None:
    return next((p for p in provincias() if p["id"] == id_prov), None)
