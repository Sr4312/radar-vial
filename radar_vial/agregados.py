"""Datos del dashboard (docs/data/*.json) a partir de los eventos y las notas.

- eventos.json: siniestros de los últimos `DIAS_EVENTOS` días (tabla, mapa y distribuciones del rango elegido).
- serie_diaria.json: todo el histórico contado por día y provincia (vista histórica y comparaciones).
- resumen_semana.json: indicadores de los últimos 7 días completos contra los 7 anteriores.
- contexto.json: notas de contexto vial, agrupadas cuando varios medios cuentan la misma novedad.
- meta.json: provincias (población Censo 2022), referencias oficiales, fecha de actualización.

"Días completos": el día de la corrida todavía no terminó, así que la semana termina ayer. Además, los dos
últimos días se marcan "en carga": las notas y las cifras de víctimas siguen llegando.
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, revision
from .eventos import cargar as cargar_eventos
from .eventos import ruta_y_km
from .notas import Notas
from .texto import mayuscula_inicial, nombre_medio, normalizar

ART = timezone(timedelta(hours=-3))
DIAS_EVENTOS = 31          # mínimo de días de siniestros con detalle; si el registro empezó antes, desde el inicio
ARCHIVO_HISTORICO = config.DIR_DATA / "historico" / "eventos.jsonl"
DIAS_CONTEXTO = 31
DIAS_EN_CARGA = 2


def cargar_todos(general: dict | None = None, diario: list[dict] | None = None,
                 historico: list[dict] | None = None) -> list[dict]:
    """Los siniestros del tablero: los recuperados (del inicio del registro hasta el día anterior a
    `inicio_diario`) y los del radar diario desde `inicio_diario`. Cada día sale de una sola de las dos fuentes, para
    no contar dos veces un mismo siniestro."""
    general = general or config.general()
    diario = cargar_eventos() if diario is None else diario
    corte = general.get("inicio_diario")
    if not corte:
        return diario
    if historico is None:
        historico = revision.aplicar(cargar_eventos(ARCHIVO_HISTORICO), revision.cargar())
    inicio = general.get("inicio_cobertura") or ""
    return ([e for e in historico if inicio <= e["fecha_hecho"] < corte] +
            [e for e in diario if e["fecha_hecho"] >= corte])


def etiqueta_ruta(via: str | None) -> str | None:
    tipo, num, _ = ruta_y_km(via)
    if num is None:
        return None
    return f"{tipo} {num}" if tipo in ("RN", "RP") else f"Ruta {num}"


MAX_FUENTES = 6    # las que muestra la lista del tablero; las demás se cuentan ("3 fuentes más")


def _evento_publicable(e: dict) -> dict:
    """Solo lo que muestra el tablero (sin claves internas de fichas ni campos vacíos, para que pese poco)."""
    fuentes = [{"medio": nombre_medio(f["medio"]), "url": f["url"]} for f in e.get("fuentes") or []]
    completo = {
        "id": e["id_evento"], "fecha": e["fecha_hecho"], "fecha_aproximada": e["fecha_aproximada"],
        "franja": e["hora_franja"], "provincia": e["provincia_id"], "localidad": mayuscula_inicial(e.get("localidad")),
        "departamento": mayuscula_inicial(e.get("departamento")), "lat": e.get("lat"), "lon": e.get("lon"), "nivel_geo": e.get("nivel_geo"),
        "via": mayuscula_inicial(e.get("via")), "ruta": etiqueta_ruta(e.get("via")), "tipo_via": e.get("tipo_via"),
        "tipo": e.get("tipo_siniestro"), "vehiculos": e.get("vehiculos") or [],
        "fallecidos": e.get("fallecidos"), "heridos_graves": e.get("heridos_graves"), "heridos_leves": e.get("heridos_leves"),
        "heridos_sin_detalle": e.get("heridos_sin_detalle"), "heridos": e.get("heridos_total"),
        "factores": e.get("factores_mencionados") or [], "grupos_etarios": e.get("grupos_etarios") or [],
        "resumen": mayuscula_inicial(e.get("resumen")), "confianza": e.get("confianza"), "solo_titulos": e.get("solo_titulos", False),
        "provincia_inferida": e.get("provincia_inferida", False),
        "fuentes": fuentes[:MAX_FUENTES], "n_fuentes": len(fuentes),
    }
    # se omiten null, false y listas vacías (el tablero completa los valores por defecto); 0 se conserva
    return {k: v for k, v in completo.items() if v is not None and v is not False and v != [] and v != ""}


def _serie(eventos: list[dict]) -> dict:
    """Por día, total y por provincia: siniestros, fallecidos, heridos y las mismas tres cifras solo de los
    siniestros conocidos por titulares (para que el tablero pueda excluirlos)."""
    dias: dict[str, dict] = defaultdict(lambda: {"total": [0] * 6, "provincias": defaultdict(lambda: [0] * 6)})
    for e in eventos:
        m, h = e.get("fallecidos") or 0, e.get("heridos_total") or 0
        solo = bool(e.get("solo_titulos"))
        fila = [1, m, h, int(solo), m if solo else 0, h if solo else 0]
        d = dias[e["fecha_hecho"]]
        d["total"] = [a + b for a, b in zip(d["total"], fila)]
        if e.get("provincia_id"):
            p = d["provincias"][e["provincia_id"]]
            d["provincias"][e["provincia_id"]] = [a + b for a, b in zip(p, fila)]
    return {"columnas": ["siniestros", "fallecidos", "heridos", "siniestros_solo_titulos", "fallecidos_solo_titulos",
                         "heridos_solo_titulos"],
            "dias": {k: {"total": v["total"], "provincias": dict(v["provincias"])} for k, v in sorted(dias.items())}}


def _sumar(serie: dict, desde: date, hasta: date) -> dict:
    tot = [0] * 6
    provincias = set()
    for dia, v in serie["dias"].items():
        if desde.isoformat() <= dia <= hasta.isoformat():
            tot = [a + b for a, b in zip(tot, v["total"])]
            provincias |= set(v["provincias"])
    return {"siniestros": tot[0], "fallecidos": tot[1], "heridos": tot[2], "siniestros_solo_titulos": tot[3],
            "provincias_con_casos": len(provincias)}


def _variacion(actual: int, previo: int) -> float | None:
    return None if previo == 0 else round(100 * (actual - previo) / previo, 1)


def resumen_semana(serie: dict, corte: date, inicio_cobertura: date | None = None) -> dict:
    """Últimos 7 días completos contra los 7 anteriores. Si el período anterior empieza antes de que el radar
    registrara (`inicio_cobertura`), no hay comparación: esos días solo tienen notas tardías sueltas."""
    desde = corte - timedelta(days=6)
    previo_hasta, previo_desde = desde - timedelta(days=1), desde - timedelta(days=7)
    actual, previo = _sumar(serie, desde, corte), _sumar(serie, previo_desde, previo_hasta)
    previo_completo = inicio_cobertura is None or previo_desde >= inicio_cobertura
    claves = ("siniestros", "fallecidos", "heridos", "provincias_con_casos")
    return {
        "desde": desde.isoformat(), "hasta": corte.isoformat(),
        "previo_desde": previo_desde.isoformat(), "previo_hasta": previo_hasta.isoformat(),
        "periodo_completo": inicio_cobertura is None or desde >= inicio_cobertura,
        "previo_completo": previo_completo,
        "dias_en_carga": [(corte - timedelta(days=i)).isoformat() for i in range(DIAS_EN_CARGA - 1, -1, -1)],
        "actual": actual, "previo": previo,
        "variacion": {k: (_variacion(actual[k], previo[k]) if previo_completo else None) for k in claves},
    }


def _palabras(texto: str) -> set[str]:
    return {w for w in normalizar(texto).split() if len(w) > 3}


def agrupar_contexto(notas: list[dict], desde: str) -> list[dict]:
    """Una novedad de contexto por grupo de notas que cuentan lo mismo (mismo subtipo y provincia, fechas
    cercanas y resúmenes parecidos). Muestra el resumen de la nota con más información y todas las fuentes."""
    grupos: list[dict] = []
    for n in sorted(notas, key=lambda n: n["publicada"]):
        c = n.get("contexto")
        if n.get("categoria") != "contexto" or not c or n["publicada"][:10] < desde:
            continue
        fecha = c.get("fecha") or n["publicada"][:10]
        palabras = _palabras(c.get("resumen", "") + " " + (c.get("dato_clave") or ""))
        destino = None
        for g in grupos:
            if g["subtipo"] != c.get("subtipo") or g["provincia"] != c.get("provincia_id"):
                continue
            if abs((date.fromisoformat(g["fecha"]) - date.fromisoformat(fecha)).days) > 3:
                continue
            union = g["_palabras"] | palabras
            # 0,25: medido el 20-11-2026 con 162 notas (0,35 dejaba duplicados; 0,20 mezclaba novedades distintas)
            if union and len(g["_palabras"] & palabras) / len(union) >= 0.25:
                destino = g
                break
        fuente = {"medio": nombre_medio(n.get("medio") or n.get("sitio")), "url": n["url"]}
        if destino:
            if fuente["url"] not in {f["url"] for f in destino["fuentes"]}:
                destino["fuentes"].append(fuente)
            destino["_palabras"] |= palabras
            continue
        grupos.append({"fecha": fecha, "subtipo": c.get("subtipo"), "ambito": c.get("ambito"),
                       "provincia": c.get("provincia_id"), "organismo": mayuscula_inicial(c.get("organismo")),
                       "dato_clave": mayuscula_inicial(c.get("dato_clave")),
                       "resumen": mayuscula_inicial(c.get("resumen")), "fuentes": [fuente],
                       "_palabras": palabras})
    for g in grupos:
        g.pop("_palabras")
    return sorted(grupos, key=lambda g: g["fecha"], reverse=True)


def generar(destino: Path, ahora: datetime | None = None, eventos: list[dict] | None = None,
            notas: list[dict] | None = None, demo: bool = False, inicio_cobertura: date | None = None) -> dict:
    """Escribe los JSON del tablero en `destino` (una carpeta data/). Devuelve el resumen de la semana."""
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(ART)
    corte = ahora.date() - timedelta(days=1)
    eventos = eventos if eventos is not None else cargar_todos()
    notas = notas if notas is not None else Notas().todas()
    serie = _serie(eventos)
    inicio = inicio_cobertura or date.fromisoformat(config.general()["inicio_cobertura"])
    resumen = resumen_semana(serie, corte, inicio)
    # con detalle: los últimos DIAS_EVENTOS días o, si el registro empezó antes, todo desde el inicio
    desde_ev = min(ahora.date() - timedelta(days=DIAS_EVENTOS), inicio).isoformat()
    dias_eventos = (corte - date.fromisoformat(desde_ev)).days + 1
    publicables = [_evento_publicable(e) for e in eventos if e["fecha_hecho"] >= desde_ev]
    # Los enlaces a las notas van aparte, un archivo por día del hecho (data/fuentes/AAAA-MM-DD.json): eran el 58%
    # de eventos.json y el 80% de lo que se descargaba (las direcciones de Google News no se comprimen), y solo
    # los usa la lista de siniestros, de a 20 filas. Medido el 26-11-2026: de 1,6 MB a 0,26 MB comprimido.
    fuentes_por_dia: dict[str, dict] = {}
    for e in publicables:
        fuentes = e.pop("fuentes", None)
        if fuentes:
            fuentes_por_dia.setdefault(e["fecha"], {})[e["id"]] = [[f["medio"], f["url"]] for f in fuentes]
    fuentes_cfg = config.cargar_yaml("fuentes.yaml")
    meta = {
        "generado": ahora.isoformat(timespec="minutes"), "corte": corte.isoformat(), "demo": demo,
        "inicio_cobertura": inicio.isoformat(),
        "dias_eventos": dias_eventos, "dias_en_carga": DIAS_EN_CARGA,
        "provincias": [{"id": p["id"], "nombre": p["corto"], "nombre_oficial": p["nombre"], "poblacion": p["poblacion"]}
                       for p in config.provincias()],
        "fuente_poblacion": "INDEC, Censo Nacional de Población, Hogares y Viviendas 2022. Resultados definitivos.",
        "oficiales": [o for o in fuentes_cfg.get("oficiales", []) if not o.get("verificar")],
        "medios_activos": sum(1 for m in fuentes_cfg.get("medios", []) if m.get("activo")),
    }
    destino.mkdir(parents=True, exist_ok=True)
    archivos = {
        "meta.json": meta,
        "eventos.json": sorted(publicables, key=lambda e: (e["fecha"], e["id"]), reverse=True),
        "serie_diaria.json": serie,
        "resumen_semana.json": resumen,
        "contexto.json": agrupar_contexto(notas, (ahora.date() - timedelta(days=DIAS_CONTEXTO)).isoformat()),
    }
    carpeta_fuentes = destino / "fuentes"
    carpeta_fuentes.mkdir(exist_ok=True)
    for viejo in carpeta_fuentes.glob("*.json"):
        if viejo.stem not in fuentes_por_dia:
            viejo.unlink()
    archivos.update({f"fuentes/{dia}.json": del_dia for dia, del_dia in fuentes_por_dia.items()})
    for nombre, datos in archivos.items():
        (destino / nombre).write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return resumen


def publicar(publicar_en_docs: bool = True, log=print, **kw) -> Path:
    """Genera los datos en docs/data/ o, con publicar_en_docs=False, una vista previa en salida/vista_previa/."""
    if publicar_en_docs:
        destino = config.DIR_DOCS_DATA
    else:
        sitio = config.DIR_SALIDA / "vista_previa"
        copiar_sitio(sitio)
        destino = sitio / "data"
    resumen = generar(destino, **kw)
    a = resumen["actual"]
    log(f"Tablero: {a['siniestros']} siniestros y {a['fallecidos']} personas fallecidas del {resumen['desde']} al "
        f"{resumen['hasta']} -> {destino.relative_to(config.RAIZ)}")
    return destino


def copiar_sitio(sitio: Path) -> None:
    """Copia el tablero (html, css, js, logos y mapa) a otra carpeta, para vistas previas y el modo demo."""
    if sitio.exists():
        shutil.rmtree(sitio)
    shutil.copytree(config.DIR_DOCS, sitio, ignore=shutil.ignore_patterns("data"))
    (sitio / "data").mkdir(parents=True, exist_ok=True)
    mapa = config.DIR_DOCS_DATA / "provincias.geojson"
    if mapa.exists():
        shutil.copy2(mapa, sitio / "data" / "provincias.geojson")
