"""Qué publica cada medio para lectores automáticos: feeds RSS y sitemaps de noticias.

Sirve para dos cosas:
- armar y verificar el catálogo de config/fuentes.yaml (scripts/descubrir_fuentes.py);
- resolver los links de Google News, que no traen la URL original: se busca el mismo título en el
  sitemap de noticias o en el RSS del medio (resolver.py).
Lo descubierto se guarda en data/cache/dominios.json y se revisa cada `dias_cache_dominios`.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import feedparser
from lxml import etree

from . import config
from .red import Red
from .texto import limpiar_html

ARCHIVO = config.DIR_CACHE / "dominios.json"

# Rutas habituales de feeds en medios argentinos (WordPress, Arc, Grupo Clarín, sitios propios).
RUTAS_FEED = [
    "/feed/", "/rss", "/rss/", "/rss.xml", "/feed",
    "/arc/outboundfeeds/rss/?outputType=xml",
    "/rss/portada.xml", "/rss/home.xml", "/rss/ultimas-noticias.xml",
]
RUTAS_SITEMAP_NOTICIAS = ["/sitemap-news.xml", "/news-sitemap.xml", "/sitemap_news.xml", "/sitemap/news.xml"]

# Parser XML que no resuelve entidades ni sale a la red (los sitemaps vienen de sitios de terceros).
_PARSER_XML = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)


def dominio_de(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


@dataclass
class Entrada:
    titulo: str
    url: str
    fecha: str | None = None


@dataclass
class InfoDominio:
    dominio: str
    base: str = ""                       # https://www.medio.com.ar (con o sin www, la que respondió)
    feeds: list[str] = field(default_factory=list)
    sitemaps_noticias: list[str] = field(default_factory=list)
    revisado: str = ""
    error: str | None = None


def _es_feed(contenido: bytes) -> bool:
    f = feedparser.parse(contenido)
    return bool(f.entries) and not (f.bozo and not f.entries)


def _xml(contenido: bytes):
    try:
        return etree.fromstring(contenido, parser=_PARSER_XML)
    except (etree.XMLSyntaxError, ValueError):
        return None


def _tag(nodo) -> str:
    return etree.QName(nodo).localname if isinstance(nodo.tag, str) else ""


def leer_sitemap(red: Red, url: str, max_hijos: int = 2, _profundidad: int = 0) -> list[Entrada]:
    """Entradas (título si lo hay, URL, fecha) de un sitemap de noticias o de un índice de sitemaps."""
    r = red.get(url)
    if not r.ok:
        return []
    raiz = _xml(r.content)
    if raiz is None:
        return []
    if _tag(raiz) == "sitemapindex":
        if _profundidad >= 1:
            return []
        hijos = [n.text.strip() for n in raiz.iter() if _tag(n) == "loc" and n.text]
        entradas: list[Entrada] = []
        for hijo in hijos[:max_hijos]:
            entradas.extend(leer_sitemap(red, hijo, max_hijos, _profundidad + 1))
        return entradas
    entradas = []
    for nodo_url in raiz:
        if _tag(nodo_url) != "url":
            continue
        loc, titulo, fecha = None, "", None
        for n in nodo_url.iter():
            t = _tag(n)
            if t == "loc" and n.text and loc is None:
                loc = n.text.strip()
            elif t == "title" and n.text:
                titulo = limpiar_html(n.text)
            elif t in ("publication_date", "lastmod") and n.text and not fecha:
                fecha = n.text.strip()
        if loc:
            entradas.append(Entrada(titulo, loc, fecha))
    return entradas


def leer_feed_entradas(red: Red, url: str) -> list[Entrada]:
    r = red.get(url)
    if not r.ok:
        return []
    f = feedparser.parse(r.content)
    return [Entrada(limpiar_html(e.get("title", "")), e.get("link", ""), e.get("published")) for e in f.entries if e.get("link")]


def descubrir(red: Red, dominio: str, probar_rutas: bool = True) -> InfoDominio:
    """Busca feeds (autodescubrimiento en la portada y rutas habituales) y sitemaps de noticias (robots.txt)."""
    info = InfoDominio(dominio=dominio, revisado=datetime.now(timezone.utc).isoformat())
    portada = None
    for base in (f"https://www.{dominio}", f"https://{dominio}"):
        try:
            r = red.get(base + "/")
            if r.ok:
                info.base, portada = base, r
                break
        except Exception as exc:  # noqa: BLE001 - un medio caído no frena el resto
            info.error = f"{type(exc).__name__}: {exc}"[:200]
    if not info.base:
        info.error = info.error or "la portada no responde"
        return info
    info.error = None

    # 1) Feeds declarados en la portada (<link rel="alternate" type="application/rss+xml">)
    candidatos = []
    for m in re.finditer(r"<link[^>]+>", portada.text[:200_000], flags=re.I):
        etiqueta = m.group(0)
        if re.search(r"application/(rss|atom)\+xml", etiqueta, re.I):
            href = re.search(r'href=["\']([^"\']+)', etiqueta, re.I)
            if href:
                candidatos.append(urljoin(info.base + "/", href.group(1).strip()))
    if probar_rutas:
        candidatos += [info.base + ruta for ruta in RUTAS_FEED]
    vistos = set()
    for url in candidatos:
        if url in vistos or len(info.feeds) >= 3:
            continue
        vistos.add(url)
        try:
            r = red.get(url)
            final = r.url or url
            if r.ok and final not in info.feeds and _es_feed(r.content):
                info.feeds.append(final)
            vistos.add(final)
        except Exception:  # noqa: BLE001
            continue

    # 2) Sitemaps de noticias declarados en robots.txt (o rutas habituales)
    sitemaps: list[str] = []
    try:
        r = red.get(info.base + "/robots.txt")
        if r.ok:
            sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    except Exception:  # noqa: BLE001
        pass
    noticias = [u for u in sitemaps if re.search(r"news|noticia", u, re.I)]
    if not noticias and probar_rutas:
        noticias = [info.base + ruta for ruta in RUTAS_SITEMAP_NOTICIAS]
    for url in noticias:
        if len(info.sitemaps_noticias) >= 2:
            break
        try:
            if leer_sitemap(red, url, max_hijos=1):
                info.sitemaps_noticias.append(url)
        except Exception:  # noqa: BLE001
            continue
    return info


class Directorio:
    """Caché de InfoDominio por dominio, con vencimiento."""

    def __init__(self, red: Red, archivo=ARCHIVO):
        self.red = red
        self.archivo = archivo
        self.dias = config.general()["resolucion"]["dias_cache_dominios"]
        self._datos: dict[str, dict] = {}
        if archivo.exists():
            self._datos = json.loads(archivo.read_text(encoding="utf-8"))
        self._entradas: dict[str, list[Entrada]] = {}   # memoria de la corrida

    def info(self, dominio: str) -> InfoDominio:
        d = self._datos.get(dominio)
        if d:
            revisado = datetime.fromisoformat(d["revisado"])
            if datetime.now(timezone.utc) - revisado < timedelta(days=self.dias):
                return InfoDominio(**d)
        info = descubrir(self.red, dominio)
        self._datos[dominio] = asdict(info)
        return info

    def entradas(self, dominio: str) -> list[Entrada]:
        """Notas recientes del medio (sitemap de noticias + feeds), leídas una sola vez por corrida."""
        if dominio not in self._entradas:
            info = self.info(dominio)
            entradas: list[Entrada] = []
            for url in info.sitemaps_noticias:
                try:
                    entradas += leer_sitemap(self.red, url)
                except Exception:  # noqa: BLE001
                    continue
            for url in info.feeds:
                try:
                    entradas += leer_feed_entradas(self.red, url)
                except Exception:  # noqa: BLE001
                    continue
            self._entradas[dominio] = entradas
        return self._entradas[dominio]

    def guardar(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(json.dumps(self._datos, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
