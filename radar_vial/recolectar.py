"""Recolección: Google News (términos x jurisdicción) y feeds RSS de medios, ventana de 48 horas.

Cada nota recolectada es un dict con:
  id, titulo, bajada, url, gn_id, clave, hash_titulo, medio, sitio, provincia_medio, nivel_medio,
  publicada (ISO, UTC), origenes [{tipo, consulta, provincia}], tipo_busqueda (siniestro|contexto)
Una fuente caída se informa y se saltea: nunca frena la corrida.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser

from . import config
from .dominios import dominio_de
from .historial import canonizar_url, clave_url, hash_titulo, quitar_medio
from .red import Red
from .texto import limpiar_html, normalizar


@dataclass
class Tarea:
    url: str
    nombre: str                     # cómo se muestra en los reportes
    tipo: str                       # google_news | rss
    tipo_busqueda: str = "siniestro"  # siniestro | contexto (qué se buscaba)
    provincia: str | None = None    # jurisdicción de la búsqueda o del medio
    medio: dict | None = None       # entrada de config/fuentes.yaml si es un feed de medio
    prefiltrar: bool = False        # feeds de medios: solo notas con palabras clave
    termino: str | None = None      # término de búsqueda (Google News), para medir cuánto aporta


@dataclass
class ResultadoTarea:
    tarea: Tarea
    total: int = 0                  # entradas del feed
    en_ventana: int = 0             # publicadas dentro de la ventana
    aceptadas: int = 0              # tras el prefiltro
    error: str | None = None
    items: list[dict] = field(default_factory=list)

    @property
    def saturada(self) -> bool:
        """Google News corta en 100 resultados: si llegó al tope, la búsqueda se quedó corta."""
        return self.tarea.tipo == "google_news" and self.total >= 95


def cargar_fuentes() -> dict:
    return config.cargar_yaml("fuentes.yaml")


def _medios_por_sitio(fuentes: dict) -> dict[str, dict]:
    return {m["sitio"].lower(): m for m in fuentes.get("medios", []) if m.get("sitio")}


def armar_tareas(consultas: dict | None = None, fuentes: dict | None = None) -> list[Tarea]:
    consultas = consultas or config.cargar_yaml("consultas.yaml")
    fuentes = fuentes if fuentes is not None else cargar_fuentes()
    plantilla = config.general()["recoleccion"]["google_news"]
    tareas: list[Tarea] = []
    # Una búsqueda por término y lugar: Google News devuelve menos notas si se combinan con OR.
    for prov in config.provincias():
        for termino in consultas["terminos"]:
            q = f"{termino} {prov['busqueda']}"
            tareas.append(Tarea(plantilla.format(q=quote_plus(q)), f"GN {termino} | {prov['corto']}",
                                "google_news", "siniestro", prov["id"], termino=termino))
        for ciudad in prov.get("ciudades") or []:
            for termino in consultas.get("terminos_ciudades", []):
                q = f"{termino} {ciudad}"
                tareas.append(Tarea(plantilla.format(q=quote_plus(q)), f"GN {termino} | {ciudad}",
                                    "google_news", "siniestro", prov["id"], termino=termino))
    for termino in consultas.get("contexto", []):
        tareas.append(Tarea(plantilla.format(q=quote_plus(termino)), f"GN contexto {termino}", "google_news", "contexto",
                            termino=termino))
    for medio in fuentes.get("medios", []):
        if not medio.get("activo"):
            continue
        feeds = medio.get("feeds") or []
        for url in feeds:
            tareas.append(Tarea(url, f"RSS {medio['nombre']}", "rss", "siniestro",
                                medio.get("provincia"), medio, prefiltrar=True))
        if not feeds and medio.get("sitemap"):
            # Medio sin feed: su sitemap de noticias trae lo mismo (título, URL y fecha de cada nota)
            tareas.append(Tarea(medio["sitemap"], f"Sitemap {medio['nombre']}", "sitemap", "siniestro",
                                medio.get("provincia"), medio, prefiltrar=True))
    return tareas


def _fecha(entry) -> datetime | None:
    for clave in ("published_parsed", "updated_parsed"):
        valor = entry.get(clave)
        if valor:
            # feedparser entrega la fecha en UTC: timegm (mktime la tomaría como hora local)
            return datetime.fromtimestamp(calendar.timegm(valor), tz=timezone.utc)
    return None


def _gn_id(url: str) -> str | None:
    p = urlparse(url)
    if p.netloc.endswith("news.google.com") and "/articles/" in p.path:
        return p.path.rsplit("/", 1)[-1]
    return None


def compilar_prefiltro(palabras: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(normalizar(p)) for p in palabras) + r")")


def _fecha_iso(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        f = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if f.tzinfo is None:  # fecha sin zona: se asume hora argentina
        f = f.replace(tzinfo=timezone(timedelta(hours=-3)))
    return f.astimezone(timezone.utc)


def titulo_desde_url(url: str) -> str:
    """Título aproximado a partir del slug de la URL (sitemaps sin título)."""
    partes = [p for p in urlparse(url).path.split("/") if p]
    slug = max(partes, key=len) if partes else ""
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    slug = re.sub(r"(^|-)n?\d{5,}($|-)", " ", slug)  # ids numéricos
    return re.sub(r"[-_]+", " ", slug).strip()


def _entradas_crudas(red: Red, tarea: Tarea) -> list[dict]:
    """Entradas de un feed o sitemap con la misma forma: titulo, link, fecha, bajada, fuente_titulo, fuente_href."""
    if tarea.tipo == "sitemap":
        from .dominios import leer_sitemap

        crudas = []
        for e in leer_sitemap(red, tarea.url, max_hijos=1):
            crudas.append({"titulo": e.titulo or titulo_desde_url(e.url), "provisional": not e.titulo,
                           "link": e.url, "fecha": _fecha_iso(e.fecha), "bajada": ""})
        return crudas
    r = red.get(tarea.url)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}")
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"no es un feed legible ({type(feed.bozo_exception).__name__})")
    crudas = []
    for e in feed.entries:
        fuente = e.get("source") or {}
        crudas.append({"titulo": limpiar_html(e.get("title", "")), "provisional": False, "link": e.get("link", ""),
                       "fecha": _fecha(e), "bajada": limpiar_html(e.get("summary", "")),
                       "fuente_titulo": (fuente.get("title") or "").strip(), "fuente_href": fuente.get("href") or ""})
    return crudas


def leer(red: Red, tarea: Tarea, desde: datetime, medios: dict[str, dict], prefiltro: re.Pattern) -> ResultadoTarea:
    res = ResultadoTarea(tarea)
    try:
        crudas = _entradas_crudas(red, tarea)
    except Exception as exc:  # noqa: BLE001 - una fuente caída no frena el resto
        res.error = f"{type(exc).__name__}: {exc}"[:200]
        return res

    res.total = len(crudas)
    for e in crudas:
        fecha = e["fecha"]
        if fecha is None or fecha < desde:
            continue
        res.en_ventana += 1
        link = e["link"]
        gn_id = _gn_id(link)
        if gn_id:
            medio_nombre = e.get("fuente_titulo", "")
            sitio = dominio_de(e.get("fuente_href", ""))
        else:
            medio_nombre = tarea.medio["nombre"] if tarea.medio else ""
            sitio = dominio_de(link)
        titulo = quitar_medio(e["titulo"], medio_nombre)
        # en Google News la bajada repite el título y el medio
        bajada = "" if gn_id else e["bajada"]
        if not titulo or not link:
            continue
        if tarea.prefiltrar and not prefiltro.search(normalizar(f"{titulo} {bajada}")):
            continue
        catalogo = medios.get(sitio)
        item = {
            "titulo": titulo,
            "bajada": bajada[:600],
            "url": link,
            "gn_id": gn_id,
            "clave": None if gn_id else clave_url(link),
            "hash_titulo": None if e.get("provisional") else hash_titulo(titulo, sitio),
            "titulo_provisional": bool(e.get("provisional")),
            "medio": (catalogo or {}).get("nombre") or medio_nombre or sitio,
            "sitio": sitio,
            "provincia_medio": (catalogo or {}).get("provincia"),
            "nivel_medio": (catalogo or {}).get("nivel"),
            "publicada": fecha.isoformat(),
            "tipo_busqueda": tarea.tipo_busqueda,
            "origenes": [{"tipo": tarea.tipo, "consulta": tarea.nombre, "provincia": tarea.provincia, "termino": tarea.termino}],
        }
        item["id"] = "n_" + (clave_url(link) if not gn_id else clave_url("gn:" + gn_id))
        res.items.append(item)
    res.aceptadas = len(res.items)
    return res


def fusionar(items: list[dict]) -> list[dict]:
    """Une la misma nota llegada por varias búsquedas o feeds (por gn_id, URL o título distintivo).

    Si una copia vino del RSS del medio (URL directa) y otra de Google News, queda la URL directa:
    así no hace falta resolver el link de Google News.
    """
    unicos: list[dict] = []
    indice: dict[str, dict] = {}
    for it in items:
        claves = [f"gn:{it['gn_id']}" if it.get("gn_id") else None,
                  f"url:{it['clave']}" if it.get("clave") else None,
                  f"tit:{it['hash_titulo']}" if it.get("hash_titulo") else None]
        claves = [c for c in claves if c]
        previo = next((indice[c] for c in claves if c in indice), None)
        if previo is None:
            unicos.append(it)
            previo = it
        else:
            vistos = {(o["tipo"], o["consulta"]) for o in previo["origenes"]}
            previo["origenes"] += [o for o in it["origenes"] if (o["tipo"], o["consulta"]) not in vistos]
            if previo.get("gn_id") and not previo.get("clave") and it.get("clave"):
                # la copia directa trae la URL original
                for campo in ("url", "clave", "id", "bajada", "medio", "provincia_medio", "nivel_medio"):
                    if it.get(campo):
                        previo[campo] = it[campo]
                previo.setdefault("gn_id_original", previo["gn_id"])
            if it.get("tipo_busqueda") == "siniestro":
                previo["tipo_busqueda"] = "siniestro"
            if it.get("filtro") and not previo.get("filtro"):   # la copia que venía de la cola ya pasó el filtro
                previo["filtro"] = it["filtro"]
            if not previo.get("provincia_medio") and it.get("provincia_medio"):
                previo["provincia_medio"] = it["provincia_medio"]
        for c in claves:
            indice.setdefault(c, previo)
        for campo, pref in (("gn_id", "gn"), ("clave", "url"), ("hash_titulo", "tit")):
            if previo.get(campo):
                indice.setdefault(f"{pref}:{previo[campo]}", previo)
    return unicos


def recolectar(red: Red | None = None, tareas: list[Tarea] | None = None, log=print) -> tuple[list[dict], list[ResultadoTarea]]:
    """Corre todas las búsquedas y feeds. Devuelve (notas únicas, resultado por tarea)."""
    red = red or Red()
    fuentes = cargar_fuentes()
    tareas = tareas if tareas is not None else armar_tareas(fuentes=fuentes)
    desde = datetime.now(timezone.utc) - timedelta(hours=config.general()["recoleccion"]["ventana_horas"])
    medios = _medios_por_sitio(fuentes)
    prefiltro = compilar_prefiltro(config.cargar_yaml("consultas.yaml")["palabras_clave"])

    # Google News se consulta en serie (un solo servidor, con pausa); los feeds de medios en paralelo.
    from concurrent.futures import ThreadPoolExecutor

    resultados: list[ResultadoTarea] = []
    gn = [t for t in tareas if t.tipo == "google_news"]
    rss = [t for t in tareas if t.tipo != "google_news"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros_rss = [ex.submit(leer, red, t, desde, medios, prefiltro) for t in rss]
        for t in gn:
            resultados.append(leer(red, t, desde, medios, prefiltro))
        resultados += [f.result() for f in futuros_rss]

    todos = [it for r in resultados for it in r.items]
    unicos = fusionar(todos)
    errores = sum(1 for r in resultados if r.error)
    log(f"Recolectadas {len(todos)} notas ({len(unicos)} únicas) de {len(tareas)} búsquedas y feeds; {errores} con error.")
    return unicos, resultados


def url_canonica(item: dict) -> str:
    return canonizar_url(item.get("url_resuelta") or item.get("url", ""))
