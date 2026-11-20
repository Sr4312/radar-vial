"""Del link de Google News a la URL original, y descarga del texto de la nota.

Los links de Google News (news.google.com/rss/articles/...) no traen la URL original, y obtenerla de
Google exigiría usar un servicio interno no documentado. En su lugar se busca la misma nota en lo que
el propio medio publica para lectores automáticos: su sitemap de noticias y sus feeds RSS, comparando
títulos (ver dominios.py). Si no aparece, la nota queda `sin_resolver` y se reintenta en la próxima corrida.

La descarga respeta robots.txt del medio. El texto completo va a una caché temporal (data/cache/textos,
fuera de git, 14 días) porque trae nombres de personas; lo que se publica es la ficha propia.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib import robotparser
from urllib.parse import urlparse

import trafilatura

from . import config
from .dominios import Directorio, Entrada, dominio_de
from .historial import canonizar_url, clave_url
from .red import Red
from .texto import normalizar

_VACIAS = set("el la los las un una unos unas de del al a en y o que con por para se lo su".split())


def _tokens(texto: str) -> set[str]:
    return {w for w in normalizar(texto).split() if w not in _VACIAS and len(w) > 1}


def similitud(titulo: str, otro: str) -> float:
    """Parecido entre dos títulos (0 a 1): el mayor entre la secuencia de caracteres y el solapamiento de palabras."""
    a, b = normalizar(titulo), normalizar(otro)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    solapamiento = len(ta & tb) / max(len(ta | tb), 1)
    return max(SequenceMatcher(None, a, b).ratio(), solapamiento)


def similitud_con_slug(titulo: str, url: str) -> float:
    """Para sitemaps sin título: qué parte de las palabras del título aparece en el slug de la URL."""
    from .recolectar import titulo_desde_url

    ta, ts = _tokens(titulo), _tokens(titulo_desde_url(url))
    return len(ta & ts) / max(len(ta), 1) if ta and ts else 0.0


def buscar_en_entradas(titulo: str, entradas: list[Entrada], minimo: float) -> tuple[str | None, float]:
    mejor_url, mejor = None, 0.0
    for e in entradas:
        s = similitud(titulo, e.titulo) if e.titulo else similitud_con_slug(titulo, e.url) * 0.98
        if s > mejor:
            mejor_url, mejor = e.url, s
    return (mejor_url, mejor) if mejor >= minimo else (None, mejor)


BING_NOTICIAS = "https://www.bing.com/news/search?q={q}&format=rss&setlang=es-AR&cc=AR"


class Resolvedor:
    """Encuentra la URL original de una nota llegada por Google News.

    1. En lo que el medio publica para lectores automáticos (sitemap de noticias y RSS), por título.
    2. Si no aparece: búsqueda del título exacto en el RSS público de Bing Noticias, que trae la URL
       original dentro de su link. Solo se acepta un resultado del mismo dominio y con el mismo título.
    """

    def __init__(self, red: Red, directorio: Directorio | None = None):
        self.red = red
        self.directorio = directorio or Directorio(red)
        conf = config.general()["resolucion"]
        self.minimo = conf["similitud_minima"]
        self.usar_bing = conf.get("bing", True)

    def resolver(self, item: dict) -> str | None:
        return self.resolver_con_metodo(item)[0]

    def resolver_con_metodo(self, item: dict) -> tuple[str | None, str | None]:
        """(URL original o None, cómo se encontró: directa | medio | bing)."""
        if not item.get("gn_id") or item.get("clave"):
            return item["url"], "directa"
        if not item.get("sitio"):
            return None, None
        url, _ = buscar_en_entradas(item["titulo"], self.directorio.entradas(item["sitio"]), self.minimo)
        if url:
            return url, "medio"
        if self.usar_bing:
            url = self._buscar_en_bing(item["titulo"], item["sitio"])
            if url:
                return url, "bing"
        return None, None

    def _buscar_en_bing(self, titulo: str, sitio: str) -> str | None:
        import feedparser
        from urllib.parse import parse_qs, quote_plus

        for q in (f'"{titulo}"', f"{titulo} site:{sitio}"):
            try:
                r = self.red.get(BING_NOTICIAS.format(q=quote_plus(q)))
            except Exception:  # noqa: BLE001
                return None
            if not r.ok:
                return None
            for e in feedparser.parse(r.content).entries:
                real = parse_qs(urlparse(e.get("link", "")).query).get("url", [e.get("link", "")])[0]
                if real.startswith("http") and dominio_de(real) == sitio and similitud(titulo, e.get("title", "")) >= self.minimo:
                    return real
        return None

    def guardar(self) -> None:
        self.directorio.guardar()


# --------------------------------------------------------------------------- robots.txt

class Robots:
    """robots.txt de cada dominio, leído una vez por corrida. Sin robots.txt legible, se permite."""

    def __init__(self, red: Red):
        self.red = red
        self.agente = config.general()["recoleccion"]["user_agent"].split("/")[0]
        self._cache: dict[str, robotparser.RobotFileParser | None] = {}

    def permite(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._cache:
            rp = robotparser.RobotFileParser()
            try:
                r = self.red.get(base + "/robots.txt")
                if r.ok:
                    rp.parse(r.text.splitlines())
                    self._cache[base] = rp
                else:
                    self._cache[base] = None
            except Exception:  # noqa: BLE001
                self._cache[base] = None
        rp = self._cache[base]
        return True if rp is None else rp.can_fetch(self.agente, url)


# --------------------------------------------------------------------------- descarga del texto

def _canonica_html(html: str, url: str) -> str:
    for patron in (r'<link[^>]+rel=["\']canonical["\'][^>]*>', r'<meta[^>]+property=["\']og:url["\'][^>]*>'):
        m = re.search(patron, html[:300_000], re.I)
        if m:
            href = re.search(r'(?:href|content)=["\']([^"\']+)', m.group(0), re.I)
            if href and href.group(1).startswith("http") and dominio_de(href.group(1)) == dominio_de(url):
                return href.group(1)
    return url


def bajar_nota(red: Red, robots: Robots, url: str) -> dict:
    """Descarga y extrae el texto principal de una nota.

    Devuelve {url_final, url_canonica, clave, titulo, texto, fecha, error}. Nunca lanza excepciones.
    """
    res = {"url_final": url, "url_canonica": canonizar_url(url), "clave": clave_url(url),
           "titulo": "", "texto": "", "fecha": None, "error": None}
    if not robots.permite(url):
        res["error"] = "robots.txt no permite leer esta página"
        return res
    try:
        r = red.get(url)
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return res
    if not r.ok:
        res["error"] = f"HTTP {r.status_code}"
        return res
    if "html" not in r.headers.get("content-type", "html"):
        res["error"] = f"no es una página HTML ({r.headers.get('content-type')})"
        return res
    html = r.text
    canonica = _canonica_html(html, r.url)
    res.update(url_final=r.url, url_canonica=canonizar_url(canonica), clave=clave_url(canonica))
    try:
        doc = trafilatura.bare_extraction(html, url=r.url, with_metadata=True, include_comments=False,
                                          include_tables=False, favor_precision=True)
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"no se pudo extraer el texto ({type(exc).__name__})"
        return res
    datos = doc.as_dict() if hasattr(doc, "as_dict") else (doc or {})
    res["titulo"] = (datos.get("title") or "").strip()
    res["texto"] = (datos.get("text") or "").strip()
    res["fecha"] = datos.get("date")
    if len(res["texto"]) < config.general()["descarga"]["min_caracteres"]:
        res["error"] = "la página no tiene texto suficiente"
    return res


# --------------------------------------------------------------------------- caché temporal de textos

def _ruta_texto(id_nota: str):
    return config.DIR_TEXTOS / f"{id_nota}.json.gz"


def guardar_texto(id_nota: str, datos: dict) -> None:
    config.DIR_TEXTOS.mkdir(parents=True, exist_ok=True)
    datos = {**datos, "guardado": datetime.now(timezone.utc).isoformat()}
    with gzip.open(_ruta_texto(id_nota), "wt", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def cargar_texto(id_nota: str) -> dict | None:
    ruta = _ruta_texto(id_nota)
    if not ruta.exists():
        return None
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        return json.load(f)


def podar_textos(dias: int | None = None) -> int:
    """Borra los textos más viejos que `dias_cache_textos`. Devuelve cuántos borró."""
    dias = dias or config.general()["descarga"]["dias_cache_textos"]
    if not config.DIR_TEXTOS.exists():
        return 0
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    borrados = 0
    for ruta in config.DIR_TEXTOS.glob("*.json.gz"):
        if datetime.fromtimestamp(ruta.stat().st_mtime, tz=timezone.utc) < limite:
            ruta.unlink()
            borrados += 1
    return borrados
