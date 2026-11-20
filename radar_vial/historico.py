"""Recuperación histórica: siniestros de fechas anteriores al inicio del radar, procesados con la cuenta de Claude.

Etapas (cada una se puede cortar y retomar con el mismo comando):
1. `recolectar`: las mismas búsquedas de Google News del radar diario, pero por ventanas de dos días con
   `after:`/`before:` (Google devuelve más notas con ventanas cortas que con una semana entera: medido el
   20-11-2026). Los feeds y sitemaps de los medios no sirven: solo listan lo de los últimos días. Las búsquedas de
   contexto vial no se hacen.
2. `procesar`: filtro (Haiku) y extracción (Sonnet) con `claude -p` y la cuenta conectada, no con la API
   (`cuenta.ClaudeCuenta`). Primero lo más reciente. Si la cuenta llega a su límite, guarda y se frena.
3. `eventos`: Georef y agrupación en siniestros, con el desempate también por la cuenta.
4. `tablero`: el tablero con estos datos en salida/historico/ (para mirarlos, no se publica).

Todo queda aparte del radar diario: `data/historico/` (fichas, historial, siniestros: sin títulos ni nombres) y
`data/cache/historico/` (las notas recolectadas con sus títulos: fuera de git). La corrida de GitHub Actions no
los lee, así que no los reagrupa ni gasta API con ellos, y las comparaciones del tablero no los usan.

Calidad: menor que la del radar diario. Las notas viejas ya no están en los sitemaps ni en los feeds de los
medios, así que muchas quedan solo con el título, y Google News devuelve una muestra de lo publicado.
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone

from . import config
from .claude import ErrorClaude
from .cuenta import ClaudeCuenta, LimiteCuenta
from .extraer import extraer_nota
from .filtrar import filtrar
from .historial import Historial
from .notas import Notas
from .recolectar import _medios_por_sitio, armar_tareas, cargar_fuentes, compilar_prefiltro, fusionar, leer
from .red import Red
from .resolver import Resolvedor, Robots, cargar_texto, guardar_texto
from .texto import log as log_consola

ART = timezone(timedelta(hours=-3))
DIR = config.DIR_DATA / "historico"
DIR_PRIVADO = config.DIR_CACHE / "historico"
ARCHIVO_ITEMS = DIR_PRIVADO / "items.json.gz"
ARCHIVO_VENTANAS = DIR_PRIVADO / "ventanas.json"
DIAS_VENTANA = 2
LOTE = 40                 # notas que se bajan y extraen antes de guardar
EN_PARALELO = 4           # procesos de `claude -p` a la vez


# ------------------------------------------------------------------ archivos

def cargar_items() -> dict[str, dict]:
    if not ARCHIVO_ITEMS.exists():
        return {}
    with gzip.open(ARCHIVO_ITEMS, "rt", encoding="utf-8") as f:
        return {it["id"]: it for it in json.load(f)}


def guardar_items(items: dict[str, dict]) -> None:
    DIR_PRIVADO.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO_ITEMS.with_name(ARCHIVO_ITEMS.name + ".tmp")
    campos_fuera = ("texto",)   # el texto va a la caché de textos, no acá
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump([{k: v for k, v in it.items() if k not in campos_fuera} for it in items.values()], f, ensure_ascii=False)
    tmp.replace(ARCHIVO_ITEMS)


def _historial() -> Historial:
    return Historial(DIR / "historial.jsonl")


def _notas() -> Notas:
    return Notas(DIR / "notas.jsonl")


def fecha_art(it: dict) -> date:
    return datetime.fromisoformat(it["publicada"]).astimezone(ART).date()


# ------------------------------------------------------------------ 1. recolección

def ventanas(desde: date, hasta: date, dias: int = DIAS_VENTANA) -> list[tuple[date, date]]:
    """Ventanas de `dias` días (las fechas de cada una, inclusive), de la más reciente a la más vieja."""
    lista, inicio = [], desde
    while inicio <= hasta:
        fin = min(hasta, inicio + timedelta(days=dias - 1))
        lista.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return list(reversed(lista))


def url_ventana(url: str, inicio: date, fin: date) -> str:
    """La búsqueda del radar diario (`when:2d`) para unas fechas: un día de margen de cada lado (Google cuenta las
    fechas en otra zona horaria); después se filtra por la fecha de publicación en hora argentina."""
    rango = f"after:{(inicio - timedelta(days=1)).isoformat()}+before:{(fin + timedelta(days=1)).isoformat()}"
    assert "when:2d" in url, url
    return url.replace("when:2d", rango)


def recolectar_historico(desde: date, hasta: date, log=log_consola, red: Red | None = None, tareas=None) -> int:
    """Corre las búsquedas de Google News por ventanas y guarda las notas. Devuelve cuántas notas hay en total."""
    red = red or Red()
    fuentes = cargar_fuentes()
    medios = _medios_por_sitio(fuentes)
    prefiltro = compilar_prefiltro(config.cargar_yaml("consultas.yaml")["palabras_clave"])
    base = tareas if tareas is not None else [t for t in armar_tareas(fuentes=fuentes)
                                               if t.tipo == "google_news" and t.tipo_busqueda == "siniestro"]
    items = cargar_items()
    hechas = set(json.loads(ARCHIVO_VENTANAS.read_text(encoding="utf-8"))) if ARCHIVO_VENTANAS.exists() else set()
    for inicio, fin in ventanas(desde, hasta):
        clave = f"{inicio.isoformat()}_{fin.isoformat()}"
        if clave in hechas:
            continue
        piso = datetime.combine(inicio - timedelta(days=1), time(0), tzinfo=timezone.utc)
        recolectadas, errores, saturadas = [], 0, 0
        for t in base:
            res = leer(red, dataclasses.replace(t, url=url_ventana(t.url, inicio, fin)), piso, medios, prefiltro)
            if res.error:
                errores += 1
            elif res.saturada and fin > inicio:
                # llegó al tope de Google: se repite día por día para no perder notas
                saturadas += 1
                for d in (inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)):
                    recolectadas += leer(red, dataclasses.replace(t, url=url_ventana(t.url, d, d)), piso, medios, prefiltro).items
            recolectadas += res.items
        if errores * 2 > len(base):
            raise RuntimeError(f"Fallaron {errores} de {len(base)} búsquedas de la ventana {clave}: puede ser un "
                               "bloqueo de Google. Se guardó lo anterior; reintentar más tarde.")
        en_rango = [it for it in recolectadas if desde <= fecha_art(it) <= hasta]
        antes = len(items)
        items = {it["id"]: it for it in fusionar(list(items.values()) + en_rango)}
        guardar_items(items)
        hechas.add(clave)
        ARCHIVO_VENTANAS.write_text(json.dumps(sorted(hechas)), encoding="utf-8")
        log(f"Ventana {inicio:%d/%m}-{fin:%d/%m}: {len(en_rango)} notas en fecha, {len(items) - antes} nuevas "
            f"({errores} búsquedas con error, {saturadas} saturadas). Total: {len(items)}.")
    return len(items)


# ------------------------------------------------------------------ 2. filtro y extracción

def _preparar(red: Red, resolvedor: Resolvedor, robots: Robots, it: dict) -> None:
    """URL original y texto, desde la caché si ya se bajó en una corrida anterior."""
    from .pipeline import _datos_cache, resolver_y_bajar

    previo = cargar_texto(it["id"])
    if previo and previo.get("resuelta"):
        for campo in ("url_resuelta", "clave"):
            if previo.get(campo):
                it[campo] = previo[campo]
        it["texto"] = previo.get("texto") or None
        return
    resolver_y_bajar(red, resolvedor, robots, it)
    guardar_texto(it["id"], {**_datos_cache(it, it.get("texto")), "resuelta": True})


def procesar_historico(log=log_consola, tope: int | None = None, claude: ClaudeCuenta | None = None,
                       red: Red | None = None) -> dict:
    """Filtra lo que falta y extrae las notas de siniestros, de lo más reciente a lo más viejo."""
    from .pipeline import _ficha_nota

    conf = config.general()
    claude = claude or ClaudeCuenta("historico procesar")
    red = red or Red()
    items, historial, notas = cargar_items(), _historial(), _notas()
    conteo = {"filtradas": 0, "siniestro": 0, "descartar": 0, "contexto": 0, "solo_titulo": 0, "error": 0, "duplicada": 0}
    resumen = {"conteo": conteo, "limite": None}

    def guardar():
        notas.guardar()
        historial.guardar()
        guardar_items(items)

    def hecha(it: dict) -> bool:
        r = historial.buscar(it)
        # en el histórico una ficha de solo título no se reintenta: las notas viejas ya no aparecen en los sitemaps
        return r is not None and (historial.ya_procesada(it) or r.get("estado") == "solo_titulo")

    try:
        # 1. Filtro, de a lotes, guardando lo decidido
        sin_filtro = [it for it in items.values() if it.get("filtro") in (None, "sin_evaluar") and not hecha(it)]
        sin_filtro.sort(key=lambda it: it["publicada"], reverse=True)
        for i in range(0, len(sin_filtro), 400):
            lote = sin_filtro[i:i + 400]
            for it in lote:
                it.pop("filtro", None)
            filtrar(claude, lote, log=log)
            conteo["filtradas"] += sum(1 for it in lote if it.get("filtro") not in (None, "sin_evaluar"))
            guardar_items(items)
        for it in items.values():
            if it.get("filtro") == "descartar" and historial.buscar(it) is None:
                historial.registrar(it, "descartada")
        guardar()

        # 2. Extracción de las notas de siniestros (las de contexto vial no se procesan en el histórico)
        relevantes = sorted((it for it in items.values() if it.get("filtro") == "siniestro" and not hecha(it)),
                            key=lambda it: it["publicada"], reverse=True)
        if tope is not None:
            relevantes = relevantes[:tope]
        log(f"Notas de siniestros por extraer: {len(relevantes)}.")
        resolvedor, robots = Resolvedor(red), Robots(red)
        modelo = conf["modelos"]["extraccion"]
        vistas: set[str] = set()

        def extraer(it):
            try:
                return it, extraer_nota(claude, it, it.get("texto")), None
            except ErrorClaude as exc:
                return it, None, str(exc)

        for i in range(0, len(relevantes), LOTE):
            lote = relevantes[i:i + LOTE]
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(lambda it: _preparar(red, resolvedor, robots, it), lote))
            para_extraer = []
            for it in lote:
                otro = historial.buscar({"clave": it["clave"]}) if it.get("clave") else None
                # su propio registro (de una corrida anterior que falló) se busca por las claves de Google News
                propio = historial.buscar({"gn_id": it.get("gn_id"), "hash_titulo": it.get("hash_titulo")})
                ya_contada = (otro is not None and otro is not propio
                              and otro.get("estado") in ("siniestro", "solo_titulo", "descartada"))
                if it.get("clave") and (it["clave"] in vistas or ya_contada):
                    # la misma nota llegó por otro enlace de Google News: sus claves llevan a la que ya se procesó
                    if otro is not None:
                        historial.agregar_alias(otro, {"gn_id": it.get("gn_id"), "hash_titulo": it.get("hash_titulo")})
                    conteo["duplicada"] += 1
                    it["filtro"] = "duplicada"
                    continue
                if it.get("clave"):
                    vistas.add(it["clave"])
                para_extraer.append(it)
            with ThreadPoolExecutor(max_workers=EN_PARALELO) as ex:
                futuros = [ex.submit(extraer, it) for it in para_extraer]
                limite = None
                for fut in futuros:
                    try:
                        it, ext, error = fut.result()
                    except LimiteCuenta as exc:
                        limite = exc
                        continue
                    if error:
                        conteo["error"] += 1
                        log(f"  ! extracción {it['sitio']}: {error}")
                        historial.registrar(it, "pendiente")
                        continue
                    fuente = "completo" if it.get("texto") else "titulo"
                    if ext["categoria"] != "siniestro":
                        historial.registrar(it, "descartada")
                        notas.por_id.pop(it["id"], None)
                        conteo["descartar"] += 1
                        continue
                    notas.guardar_nota({**_ficha_nota(it, ext, fuente, modelo), "origen": "historico"})
                    conteo["siniestro"] += 1
                    if fuente == "titulo":
                        conteo["solo_titulo"] += 1
                        historial.registrar(it, "solo_titulo", id_nota=it["id"])
                    else:
                        historial.registrar(it, "siniestro", id_nota=it["id"])
                if limite is not None:
                    raise limite
            guardar()
            log(f"  {min(i + LOTE, len(relevantes))} de {len(relevantes)}: {conteo['siniestro']} con fichas "
                f"({conteo['solo_titulo']} solo con el título), {conteo['descartar']} descartadas, {conteo['error']} con error.")
    except LimiteCuenta as exc:
        resumen["limite"] = exc.reinicio.isoformat() if exc.reinicio else "desconocido"
        hora = exc.reinicio.astimezone(ART).strftime("%d/%m %H:%M") if exc.reinicio else "más tarde"
        log(f"La cuenta llegó a su límite de uso: se guardó lo hecho. Se puede retomar después de las {hora}.")
    finally:
        guardar()
        claude.guardar_uso({"etapa": "procesar", "conteo": conteo})
    faltan = sum(1 for it in items.values() if it.get("filtro") in (None, "sin_evaluar", "siniestro") and not hecha(it))
    resumen["faltan"] = faltan
    log(f"Quedan {faltan} notas por filtrar o extraer.")
    return resumen


# ------------------------------------------------------------------ 3. siniestros

class _SinFrenar:
    """Para el desempate: si la cuenta llega al límite, ese caso queda sin fusionar (se vuelve a preguntar la próxima
    vez) en lugar de cortar la agrupación entera."""

    def __init__(self, claude: ClaudeCuenta):
        self.claude = claude
        self.sin_decidir = 0

    def json(self, *a, **kw):
        try:
            return self.claude.json(*a, **kw)
        except LimiteCuenta as exc:
            self.sin_decidir += 1
            raise ErrorClaude("límite de la cuenta") from exc


def eventos_historico(log=log_consola, claude: ClaudeCuenta | None = None) -> list[dict]:
    from .eventos import armar_eventos
    from .geo import ARCHIVO as GEOREF_DIARIO
    from .geo import Georef, completar_notas
    from .pipeline import _TitulosEnCache

    notas = _notas()
    archivo_georef = DIR / "georef.json"
    if not archivo_georef.exists() and GEOREF_DIARIO.exists():
        shutil.copy(GEOREF_DIARIO, archivo_georef)   # se parte de lo ya consultado por el radar diario
    georef = Georef(archivo=archivo_georef)
    hechas = completar_notas(notas, georef)
    georef.guardar()
    notas.guardar()
    log(f"Georef: {hechas} fichas normalizadas ({georef.consultas} consultas nuevas).")
    cuenta = claude or ClaudeCuenta("historico eventos")
    envoltura = _SinFrenar(cuenta)
    eventos = armar_eventos(notas, envoltura, titulos=_TitulosEnCache(), log=log, archivo=DIR / "eventos.jsonl",
                            archivo_decisiones=DIR / "decisiones_eventos.json")
    cuenta.guardar_uso({"etapa": "eventos", "eventos": len(eventos), "sin_decidir": envoltura.sin_decidir})
    if envoltura.sin_decidir:
        log(f"{envoltura.sin_decidir} casos dudosos quedaron sin decidir por el límite de la cuenta: correr "
            "`historico eventos` otra vez más tarde.")
    return eventos


# ------------------------------------------------------------------ 4. tablero para mirar

def tablero_historico(desde: date, hasta: date, log=log_consola) -> str:
    """El tablero con los datos recuperados, en salida/historico/ (no se publica)."""
    from .agregados import copiar_sitio, generar
    from .eventos import cargar

    sitio = config.DIR_SALIDA / "historico"
    copiar_sitio(sitio)
    ahora = datetime.combine(hasta + timedelta(days=1), time(9), tzinfo=ART)
    generar(sitio / "data", ahora=ahora, eventos=cargar(DIR / "eventos.jsonl"), notas=_notas().todas(),
            inicio_cobertura=desde)
    log(f"Tablero con los datos recuperados en {sitio.relative_to(config.RAIZ)}.")
    return str(sitio)


def estado_historico(log=log_consola) -> dict:
    items, historial = cargar_items(), _historial()
    filtros: dict[str, int] = {}
    for it in items.values():
        filtros[it.get("filtro") or "sin filtrar"] = filtros.get(it.get("filtro") or "sin filtrar", 0) + 1
    estados: dict[str, int] = {}
    for r in historial.registros:
        estados[r["estado"]] = estados.get(r["estado"], 0) + 1
    ventanas_hechas = json.loads(ARCHIVO_VENTANAS.read_text(encoding="utf-8")) if ARCHIVO_VENTANAS.exists() else []
    datos = {"notas_recolectadas": len(items), "ventanas": len(ventanas_hechas), "filtro": filtros, "historial": estados,
             "fichas": len(_notas().por_id)}
    log(json.dumps(datos, ensure_ascii=False, indent=1))
    return datos
