"""Filtro barato (Haiku, en lotes): ¿es Argentina? ¿siniestro vial, contexto vial o descartar?

Mira solo título, bajada y medio. Ante la duda deja pasar: después se lee la nota completa y la extracción
confirma la categoría. Una nota que el modelo no devuelve (o un lote que falla) queda `sin_evaluar` y se
reintenta en la próxima corrida.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import config
from .claude import Claude, ErrorClaude

CATEGORIAS = ("siniestro", "contexto", "descartar")

SISTEMA = """Sos parte del Radar Vial del Observatorio Humanitario de Cruz Roja Argentina, que cuenta los siniestros viales que publica la prensa argentina. Recibís una lista numerada de notas (título, bajada si hay, medio y la provincia por la que se la buscó). Para cada nota decidí:

argentina: true si el hecho ocurrió en Argentina o la nota trata de Argentina. Muchos lugares tienen homónimos en otros países (Córdoba en España o en Veracruz, Santa Cruz en Bolivia, San Juan en Puerto Rico, La Rioja en España, Mendoza en otros países): usá el medio y el contexto para decidir.

categoria:
- "siniestro": un siniestro vial concreto ocurrido en Argentina. Incluye choques, vuelcos, atropellos, despistes, caídas de moto o de bicicleta, trenes contra vehículos o peatones en pasos a nivel, siniestros con colectivos o camiones, y notas de seguimiento de un siniestro concreto (murió una persona herida, se conoció la identidad de la víctima, quedó detenido el conductor, se completó la cifra de víctimas).
- "contexto": seguridad vial en Argentina sin un siniestro concreto: controles y alcoholemia, cambios de normas (alcohol cero, licencias de conducir), estadísticas oficiales, estado de rutas e infraestructura vial, campañas de seguridad vial, balances con cifras agregadas (por ejemplo, las víctimas de un fin de semana largo en una provincia).
- "descartar": todo lo demás. Por ejemplo: accidentes que no son viales (domésticos, laborales fuera de la vía pública, aéreos, náuticos), "choque" en sentido figurado (política, deportes, peleas), hechos en otros países, deportes de motor en circuito o en competencia, robos de vehículos o persecuciones sin siniestro, notas sin un hecho vial concreto en Argentina.

Si el título no alcanza para decidir entre "siniestro" o "contexto" y "descartar", elegí "siniestro" o "contexto": después se lee la nota completa. Si la nota es de otro país, la categoría es "descartar".
Devolvé una entrada por cada número de la lista, con el mismo número."""

SCHEMA = {
    "type": "object",
    "properties": {
        "notas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "argentina": {"type": "boolean"},
                    "categoria": {"type": "string", "enum": list(CATEGORIAS)},
                },
                "required": ["n", "argentina", "categoria"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["notas"],
    "additionalProperties": False,
}


def _linea(n: int, it: dict) -> str:
    provincias = sorted({o["provincia"] for o in it.get("origenes", []) if o.get("provincia")})
    nombres = [p["corto"] for p in config.provincias() if p["id"] in provincias]
    partes = [f"{n}. {it['titulo']}"]
    if it.get("bajada"):
        partes.append(f"   Bajada: {it['bajada'][:300]}")
    partes.append(f"   Medio: {it.get('medio') or it.get('sitio')}" + (f" | Buscada por: {', '.join(nombres)}" if nombres else ""))
    return "\n".join(partes)


def filtrar(claude: Claude, items: list[dict], log=print) -> None:
    """Agrega a cada item `filtro` = siniestro | contexto | descartar | sin_evaluar (y `argentina`)."""
    conf = config.general()
    modelo = conf["modelos"]["filtro"]
    esfuerzo = conf["esfuerzo"]["filtro"]
    tam = conf["limites"]["notas_por_lote_filtro"]

    def filtrar_lote(inicio: int) -> None:
        lote = items[inicio:inicio + tam]
        mensaje = "Notas:\n\n" + "\n\n".join(_linea(i + 1, it) for i, it in enumerate(lote))
        try:
            resp = claude.json("filtro", modelo, SISTEMA, mensaje, SCHEMA, esfuerzo=esfuerzo, max_tokens=8000)
        except ErrorClaude as exc:
            log(f"  ! filtro, lote {inicio // tam + 1}: {exc}")
            for it in lote:
                it["filtro"] = "sin_evaluar"
            return
        por_n = {r["n"]: r for r in resp.get("notas", [])}
        for i, it in enumerate(lote):
            r = por_n.get(i + 1)
            if r is None or r.get("categoria") not in CATEGORIAS:
                it["filtro"] = "sin_evaluar"  # el modelo la salteó: se reintenta en la próxima corrida
                continue
            it["argentina"] = bool(r["argentina"])
            it["filtro"] = r["categoria"] if r["argentina"] else "descartar"

    # Los lotes no dependen entre sí: van de a varios (cada uno tarda unos 6 s; con 46 lotes eran casi 5 minutos).
    with ThreadPoolExecutor(max_workers=conf["limites"].get("filtros_en_paralelo", 4)) as ex:
        list(ex.map(filtrar_lote, range(0, len(items), tam)))
    cuenta = {c: sum(1 for it in items if it.get("filtro") == c) for c in (*CATEGORIAS, "sin_evaluar")}
    log(f"Filtro: {cuenta['siniestro']} siniestros, {cuenta['contexto']} de contexto, "
        f"{cuenta['descartar']} descartadas, {cuenta['sin_evaluar']} sin evaluar (de {len(items)}).")
