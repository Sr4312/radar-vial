"""Historial de notas ya vistas (90 días): evita bajar, filtrar o extraer dos veces la misma nota.

Una nota se reconoce por:
- su URL canónica (sin parámetros de seguimiento, sin versión AMP ni móvil, sin barra final);
- el id del artículo en Google News (antes de conocer la URL original);
- el hash de su título normalizado junto con el sitio del medio, solo si el título es distintivo (los títulos
  genéricos como "Murió un motociclista en un choque" se repiten entre notas distintas y no sirven para
  deduplicar) y solo durante `DIAS_HASH_TITULO` días: otro medio, o el mismo medio semanas después, puede
  titular igual un siniestro distinto.

Cada registro es de una sola nota. Las otras claves por las que llega esa misma nota (otro id de Google News,
la URL del link cuando la canónica es distinta) se guardan como `alias` del registro, sin cambiarle el estado.

El historial no guarda títulos ni textos (pueden traer nombres de personas): solo claves y estado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from . import config
from .texto import normalizar

ARCHIVO = config.DIR_DATA / "historial.jsonl"

# Estados finales: la nota no se vuelve a procesar.
FINALES = {"descartada", "siniestro", "contexto", "sin_texto", "duplicada"}
# Estados que se reintentan en la próxima corrida (hasta MAX_INTENTOS). `solo_titulo`: ya tiene ficha hecha con
# el título; si una corrida posterior encuentra la URL original, la ficha se rehace con el texto completo.
REINTENTABLES = {"sin_resolver", "error_descarga", "pendiente", "solo_titulo"}
MAX_INTENTOS = 3

_PARAMS_SEGUIMIENTO = re.compile(
    r"^(utm_.*|fbclid|gclid|gclsrc|dclid|mc_cid|mc_eid|ref|ref_src|ref_url|igshid|ocid|cmpid|ito|_gl|spm|"
    r"outputtype|amp|output|share|via|src|source|from|origen|s_src|wt\..*|__twitter_impression)$",
    re.I,
)
# Palabras que no distinguen una nota de otra al decidir si un título es "genérico"
_VACIAS = set(
    "el la los las un una unos unas de del al a en y o que con por para tras sobre su sus se lo le es fue "
    "murio muere muerto murieron herido heridos grave choque accidente ruta tras "
    "motociclista ciclista peaton conductor hombre mujer joven persona personas auto moto camion camioneta "
    "chocar choco chocaron contra vuelco volco atropello fatal tragedia siniestro vial".split()
)
MIN_PALABRAS_DISTINTIVAS = 5
DIAS_HASH_TITULO = 7
_CAMPOS = ("clave", "gn_id", "hash_titulo")


def canonizar_url(url: str) -> str:
    """URL comparable: https, sin www/m/amp, sin parámetros de seguimiento ni fragmento, sin barra final."""
    url = (url or "").strip()
    if not url:
        return ""
    p = urlparse(url if "//" in url else "https://" + url)
    host = p.netloc.lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    host = host.split(":")[0] if host.endswith((":80", ":443")) else host
    for prefijo in ("www.", "amp.", "m."):
        if host.startswith(prefijo):
            host = host[len(prefijo):]
    ruta = re.sub(r"/{2,}", "/", p.path or "/")
    ruta = re.sub(r"\.amp(\.html?)?$", r"\1", ruta)          # nota.amp.html -> nota.html
    ruta = re.sub(r"/amp/?$", "", ruta)                       # /nota/amp -> /nota
    ruta = re.sub(r"^/amp/", "/", ruta)                       # /amp/nota -> /nota
    if len(ruta) > 1:
        ruta = ruta.rstrip("/")
    params = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not _PARAMS_SEGUIMIENTO.match(k))
    return urlunparse(("https", host, ruta, "", urlencode(params), ""))


def _hash(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]


def clave_url(url: str) -> str:
    return _hash(canonizar_url(url))


def quitar_medio(titulo: str, medio: str | None) -> str:
    """Google News agrega " - Medio" al final del título: se saca solo si coincide con el medio informado."""
    titulo = (titulo or "").strip()
    if medio:
        for sep in (" - ", " | "):
            sufijo = sep + medio.strip()
            if titulo.lower().endswith(sufijo.lower()):
                return titulo[: -len(sufijo)].strip()
    return titulo


def titulo_distintivo(titulo: str) -> bool:
    palabras = [w for w in normalizar(titulo).split() if w not in _VACIAS and len(w) > 2]
    return len(palabras) >= MIN_PALABRAS_DISTINTIVAS


def hash_titulo(titulo: str, sitio: str | None = None) -> str | None:
    """Hash del título normalizado y el sitio, o None si el título es demasiado genérico para deduplicar."""
    return _hash(f"{sitio or ''}|{normalizar(titulo)}") if titulo_distintivo(titulo) else None


def escribir_lineas(archivo, lineas) -> None:
    """Escribe a un archivo temporal y lo renombra: una corrida cortada no deja el archivo por la mitad."""
    archivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = archivo.with_name(archivo.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for linea in lineas:
            f.write(linea + "\n")
    os.replace(tmp, archivo)


class Historial:
    def __init__(self, archivo=ARCHIVO):
        self.archivo = archivo
        self.registros: list[dict] = []
        if archivo.exists():
            with open(archivo, encoding="utf-8") as f:
                self.registros = [json.loads(linea) for linea in f if linea.strip()]
        self._indexar()

    def _indexar(self) -> None:
        self._por_clave: dict[str, dict] = {}
        for r in self.registros:
            for alias in r.get("alias") or []:
                self._por_clave[alias] = r
        for r in self.registros:   # las claves propias ganan a los alias
            for campo in _CAMPOS:
                if r.get(campo):
                    self._por_clave[f"{campo}:{r[campo]}"] = r

    @staticmethod
    def _reciente(r: dict) -> bool:
        limite = datetime.now(timezone.utc) - timedelta(days=DIAS_HASH_TITULO)
        return datetime.fromisoformat(r.get("visto") or r["actualizado"]) >= limite

    def buscar(self, item: dict) -> dict | None:
        for campo in _CAMPOS:
            valor = item.get(campo)
            r = self._por_clave.get(f"{campo}:{valor}") if valor else None
            if r is not None and (campo != "hash_titulo" or self._reciente(r)):
                return r
        return None

    def agregar_alias(self, r: dict, item: dict) -> None:
        """La misma nota llegó por otra vía: sus claves llevan al registro `r`, que no cambia de estado."""
        for campo in _CAMPOS:
            valor = item.get(campo)
            if valor and r.get(campo) != valor:
                alias = f"{campo}:{valor}"
                if alias not in r.setdefault("alias", []):
                    r["alias"].append(alias)
                self._por_clave.setdefault(alias, r)

    def ya_procesada(self, item: dict) -> bool:
        """True si la nota llegó a un estado final o agotó sus reintentos."""
        r = self.buscar(item)
        if not r:
            return False
        return r["estado"] in FINALES or r.get("intentos", 0) >= MAX_INTENTOS

    def registrar(self, item: dict, estado: str, id_nota: str | None = None) -> dict:
        r = self.buscar(item)
        ahora = datetime.now(timezone.utc).isoformat()
        if r is None:
            r = {"visto": ahora, "intentos": 0}
            self.registros.append(r)
        for campo in _CAMPOS:
            if item.get(campo):
                if r.get(campo) and r[campo] != item[campo]:   # la clave anterior sigue llevando a este registro
                    alias = r.setdefault("alias", [])
                    if f"{campo}:{r[campo]}" not in alias:
                        alias.append(f"{campo}:{r[campo]}")
                    if f"{campo}:{item[campo]}" in alias:
                        alias.remove(f"{campo}:{item[campo]}")
                r[campo] = item[campo]
        r["estado"] = estado
        r["actualizado"] = ahora
        if estado in REINTENTABLES:
            r["intentos"] = r.get("intentos", 0) + 1
        if id_nota:
            r["id_nota"] = id_nota
        for campo in _CAMPOS:
            if r.get(campo):
                self._por_clave[f"{campo}:{r[campo]}"] = r
        return r

    def podar(self, dias: int | None = None) -> int:
        dias = dias or config.general()["historial"]["dias"]
        limite = datetime.now(timezone.utc) - timedelta(days=dias)
        antes = len(self.registros)
        self.registros = [r for r in self.registros if datetime.fromisoformat(r["visto"]) >= limite]
        self._indexar()
        return antes - len(self.registros)

    def guardar(self) -> None:
        escribir_lineas(self.archivo, (json.dumps(r, ensure_ascii=False, sort_keys=True) for r in self.registros))
