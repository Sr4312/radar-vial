"""Registro de la última corrida diaria (data/estado.json).

GitHub Actions no es puntual con los horarios programados (en el Radar Humanitario llegaban horas tarde), así
que el workflow intenta varias veces por día y cada intento corre solo si hoy todavía no hubo una corrida
completa (`diario --si-no-corrio-hoy`). "Hoy" es el día en Argentina.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from . import config

ARCHIVO = config.DIR_DATA / "estado.json"
ART = timezone(timedelta(hours=-3))


def hoy() -> date:
    return datetime.now(ART).date()


def cargar(archivo=ARCHIVO) -> dict:
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}


def corrio_hoy(archivo=ARCHIVO) -> bool:
    return cargar(archivo).get("ultimo_diario") == hoy().isoformat()


def marcar_diario(resumen: dict, publicado: bool, archivo=ARCHIVO) -> None:
    estado = cargar(archivo)
    estado.update({
        "ultimo_diario": hoy().isoformat(),
        "hora": datetime.now(ART).isoformat(timespec="minutes"),
        "publicado": publicado,
        "resumen": {k: resumen.get(k) for k in ("recolectadas", "nuevas", "extraidas", "postergadas", "eventos", "duracion_min")},
    })
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
