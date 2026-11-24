"""Revisión manual de los siniestros recuperados (data/historico/revision.json).

La recuperación del 18-10 al 17-11-2026 se armó casi toda con titulares (las notas de más de dos semanas ya no se
pueden abrir), y con solo el titular el sistema no distingue bien un choque de otro ni sabe en qué país fue. La
revisión del 24-11-2026 miró uno por uno los siniestros con personas fallecidas y dejó, con su motivo:
- `excluir`: choques de otros países, notas de balance que suman muertes ya contadas, y notas que no son un
  siniestro de esa fecha (seguimiento judicial de un hecho anterior, o no fue un choque);
- `fusionar`: el mismo siniestro contado dos veces; las fuentes pasan al siniestro que queda.
Se aplica al publicar el tablero; el archivo de siniestros recuperados no se toca.
"""
from __future__ import annotations

import json

from . import config

ARCHIVO = config.DIR_DATA / "historico" / "revision.json"


def cargar(archivo=ARCHIVO) -> dict:
    if not archivo.exists():
        return {}
    return json.loads(archivo.read_text(encoding="utf-8"))


def aplicar(eventos: list[dict], revision: dict) -> list[dict]:
    """Los eventos sin los excluidos y con los duplicados sumados al que queda (fuentes y fallecidos)."""
    excluir = {x["id"] for x in revision.get("excluir", [])}
    destino = {x["id"]: x["en"] for x in revision.get("fusionar", [])}
    por_id = {e["id_evento"]: dict(e) for e in eventos}
    for origen, en in destino.items():
        while en in destino:          # por si el destino también se fusionó en otro
            en = destino[en]
        a, b = por_id.get(origen), por_id.get(en)
        if a is None or b is None or en in excluir:
            continue
        urls = {f["url"] for f in b.get("fuentes") or []}
        b["fuentes"] = (b.get("fuentes") or []) + [f for f in a.get("fuentes") or [] if f["url"] not in urls]
        b["n_fuentes"] = len(b["fuentes"])
        if a.get("fallecidos") is not None:
            b["fallecidos"] = max(b.get("fallecidos") or 0, a["fallecidos"])
        b["solo_titulos"] = bool(b.get("solo_titulos")) and bool(a.get("solo_titulos"))
    quitar = excluir | set(destino)
    return [por_id[e["id_evento"]] for e in eventos if e["id_evento"] not in quitar]
