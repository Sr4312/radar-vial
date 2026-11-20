"""Utilidades de texto: limpieza de HTML, normalización para comparar y salida segura por consola."""
from __future__ import annotations

import html
import re
import sys
import unicodedata


def limpiar_html(texto: str | None) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni signos, espacios simples: para comparar textos, no para mostrarlos."""
    t = sin_acentos((texto or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def log(*partes) -> None:
    """print que no falla en la consola de Windows (cp1252): reemplaza lo que no se puede mostrar."""
    texto = " ".join(str(p) for p in partes)
    codificacion = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(texto.encode(codificacion, errors="replace").decode(codificacion, errors="replace"), flush=True)
