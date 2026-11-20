"""Muestra al azar de fichas para que el equipo las revise a mano (CSV que abre Excel).

Cada fila es un siniestro (o una nota de contexto) con el link a la nota original, lo que extrajo el radar y
tres columnas vacías para la revisión. La muestra sale de las notas publicadas en los últimos `dias`.
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta, timezone

from . import config
from .notas import Notas

COLUMNAS_REVISION = ["revision_categoria_ok (si/no)", "revision_datos_ok (si/no)", "revision_observaciones"]
ART = timezone(timedelta(hours=-3))


def _hora_ar(iso: str) -> str:
    """Fecha y hora de publicación en hora argentina (las notas se guardan en UTC)."""
    try:
        return datetime.fromisoformat(iso).astimezone(ART).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def _fila_siniestro(n: dict, i: int, f: dict) -> dict:
    return {
        "id_nota": n["id_nota"], "ficha": i + 1, "categoria": "siniestro", "medio": n.get("medio"), "url": n["url"],
        "publicada": _hora_ar(n["publicada"]), "fuente_texto": n.get("fuente_texto"), "fecha_hecho": f.get("fecha_hecho"),
        "fecha_aproximada": "si" if f.get("fecha_aproximada") else "no", "provincia": f.get("provincia"),
        "localidad": f.get("localidad"), "via": f.get("via"), "tipo_via": f.get("tipo_via"),
        "tipo": f.get("tipo_siniestro"), "vehiculos": ", ".join(f.get("vehiculos") or []),
        "fallecidos": f.get("fallecidos"), "heridos_graves": f.get("heridos_graves"), "heridos_leves": f.get("heridos_leves"),
        "heridos_sin_detalle": f.get("heridos_sin_detalle"),
        "factores": ", ".join(x["factor"] + (" (presunto)" if x["presunto"] else "") for x in f.get("factores_mencionados") or []),
        "grupos_etarios": ", ".join(f.get("grupos_etarios") or []), "resumen": f.get("resumen"), "confianza": f.get("confianza"),
    }


def _fila_contexto(n: dict, c: dict) -> dict:
    return {"id_nota": n["id_nota"], "ficha": 1, "categoria": "contexto", "medio": n.get("medio"), "url": n["url"],
            "publicada": _hora_ar(n["publicada"]), "fuente_texto": n.get("fuente_texto"), "fecha_hecho": c.get("fecha"),
            "provincia": c.get("provincia"), "tipo": c.get("subtipo"), "resumen": c.get("resumen"), "confianza": c.get("confianza")}


def generar_eventos(n: int = 15, dias: int = 7, semilla: int | None = None) -> tuple[str, int]:
    """Planilla de la agrupación: siniestros fusionados ("¿son el mismo?") y pares separados ("¿son distintos?").

    Pares separados: dos siniestros de la misma localidad, a un día o menos, con el mismo tipo de hecho.
    Escribe salida/auditoria_eventos_<fecha>.csv. Devuelve (ruta, filas).
    """
    from . import eventos as ev_mod

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).date().isoformat()
    eventos = [e for e in ev_mod.cargar() if e["fecha_hecho"] >= desde]
    rnd = random.Random(semilla if semilla is not None else date.today().toordinal())
    fusionados = rnd.sample([e for e in eventos if e["n_fuentes"] > 1], min(n, sum(e["n_fuentes"] > 1 for e in eventos)))
    pares = []
    for i, a in enumerate(eventos):
        for b in eventos[i + 1:]:
            if (a.get("localidad") and a.get("localidad") == b.get("localidad")
                    and abs((date.fromisoformat(a["fecha_hecho"]) - date.fromisoformat(b["fecha_hecho"])).days) <= 1
                    and ev_mod.FAMILIAS.get(a["tipo_siniestro"]) == ev_mod.FAMILIAS.get(b["tipo_siniestro"])):
                pares.append((a, b))
    pares = rnd.sample(pares, min(n, len(pares)))

    def fuentes(e):
        return " | ".join(f"{f['medio']}: {f['url']}" for f in e["fuentes"])

    columnas = ["pregunta", "evento", "fecha_hecho", "provincia", "localidad", "via", "tipo", "fallecidos",
                "heridos_total", "n_fuentes", "resumen", "fuentes", "otro_evento", "otro_resumen", "otras_fuentes",
                "respuesta (si/no)", "observaciones"]
    filas = []
    for e in fusionados:
        filas.append({"pregunta": "¿Todas las fuentes cuentan el mismo siniestro?", "evento": e["id_evento"],
                      "fecha_hecho": e["fecha_hecho"], "provincia": e.get("provincia"), "localidad": e.get("localidad"),
                      "via": e.get("via"), "tipo": e.get("tipo_siniestro"), "fallecidos": e.get("fallecidos"),
                      "heridos_total": e.get("heridos_total"), "n_fuentes": e["n_fuentes"], "resumen": e.get("resumen"),
                      "fuentes": fuentes(e)})
    for a, b in pares:
        filas.append({"pregunta": "¿Son dos siniestros distintos?", "evento": a["id_evento"], "fecha_hecho": a["fecha_hecho"],
                      "provincia": a.get("provincia"), "localidad": a.get("localidad"), "via": a.get("via"),
                      "tipo": a.get("tipo_siniestro"), "fallecidos": a.get("fallecidos"), "heridos_total": a.get("heridos_total"),
                      "n_fuentes": a["n_fuentes"], "resumen": a.get("resumen"), "fuentes": fuentes(a),
                      "otro_evento": b["id_evento"], "otro_resumen": b.get("resumen"), "otras_fuentes": fuentes(b)})
    config.DIR_SALIDA.mkdir(exist_ok=True)
    ruta = config.DIR_SALIDA / f"auditoria_eventos_{date.today().isoformat()}.csv"
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: ("" if fila.get(c) is None else fila.get(c)) for c in columnas})
    return str(ruta.relative_to(config.RAIZ)), len(filas)


def generar(n: int = 30, dias: int = 7, semilla: int | None = None) -> tuple[str, int]:
    """Escribe salida/auditoria_<fecha>.csv. Devuelve (ruta, cantidad de filas)."""
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    filas = []
    for nota in Notas().todas():
        if nota["publicada"] < desde:
            continue
        if nota["categoria"] == "siniestro":
            filas += [_fila_siniestro(nota, i, f) for i, f in enumerate(nota["siniestros"])]
        elif nota.get("contexto"):
            filas.append(_fila_contexto(nota, nota["contexto"]))
    rnd = random.Random(semilla if semilla is not None else date.today().toordinal())
    muestra = rnd.sample(filas, min(n, len(filas)))
    muestra.sort(key=lambda f: (f["categoria"], f["publicada"]))
    config.DIR_SALIDA.mkdir(exist_ok=True)
    ruta = config.DIR_SALIDA / f"auditoria_{date.today().isoformat()}.csv"
    columnas = list(_fila_siniestro({"id_nota": "", "url": "", "publicada": ""}, 0, {})) + COLUMNAS_REVISION
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:  # utf-8 con BOM: Excel muestra bien los acentos
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for fila in muestra:
            w.writerow({c: ("" if fila.get(c) is None else fila.get(c)) for c in columnas})
    return str(ruta.relative_to(config.RAIZ)), len(muestra)
