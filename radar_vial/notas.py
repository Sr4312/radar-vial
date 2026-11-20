"""Fichas de notas ya extraídas (data/notas.jsonl): una línea por nota, se reemplaza por id_nota.

No guarda títulos ni textos (pueden traer nombres): solo la URL, el medio, la fecha y la ficha propia.
"""
from __future__ import annotations

import json

from . import config

ARCHIVO = config.DIR_DATA / "notas.jsonl"


class Notas:
    def __init__(self, archivo=ARCHIVO):
        self.archivo = archivo
        self.por_id: dict[str, dict] = {}
        if archivo.exists():
            with open(archivo, encoding="utf-8") as f:
                for linea in f:
                    if linea.strip():
                        n = json.loads(linea)
                        self.por_id[n["id_nota"]] = n

    def guardar_nota(self, nota: dict) -> None:
        self.por_id[nota["id_nota"]] = nota

    def todas(self) -> list[dict]:
        return sorted(self.por_id.values(), key=lambda n: (n["publicada"], n["id_nota"]))

    def guardar(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        with open(self.archivo, "w", encoding="utf-8") as f:
            for n in self.todas():
                f.write(json.dumps(n, ensure_ascii=False, sort_keys=True) + "\n")
