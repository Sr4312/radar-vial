"""Agrupación de fichas en eventos: la unidad de análisis es el siniestro, no la nota.

Cada ficha de siniestro (una nota puede tener varias) se compara con los eventos ya armados:
- candidatos: misma provincia (o provincia desconocida en una de las dos), fecha del hecho a un día o menos
  (dos si alguna fecha es aproximada), y ninguna contradicción dura (rutas distintas, kilómetros muy separados);
- puntaje: localidad, ruta y kilómetro, calle, vehículos, tipo de siniestro, franja horaria, víctimas;
- puntaje alto y sin rival cercano: se fusiona sola; dudoso (o la ficha es solo de título): decide Claude con
  las fichas a la vista; bajo: evento nuevo.
La agrupación se rehace entera en cada corrida (en orden de publicación, determinística) y los ids de evento se
conservan: cada evento nuevo hereda el id del evento anterior con el que comparte más fichas. Las decisiones de
Claude se guardan en data/cache/decisiones_eventos.json para no volver a preguntar lo mismo.

Al fusionar: se queda el dato más completo (notas con texto completo y mayor confianza primero) y, para las
fallecidos, la cifra más alta de las notas completas (salvo que la dé una sola nota y la desmientan las notas
posteriores: ver _fallecidos); para los heridos, la de la nota más reciente.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from datetime import date

from . import config
from .texto import normalizar

ARCHIVO = config.DIR_DATA / "eventos.jsonl"
ARCHIVO_DECISIONES = config.DIR_CACHE / "decisiones_eventos.json"

UMBRAL_FUSION = 4.0       # puntaje desde el que se fusiona sin preguntar
UMBRAL_CONSULTA = 1.5     # puntaje desde el que se pregunta a Claude (fichas con texto completo)
MARGEN = 1.0              # ventaja mínima sobre el segundo candidato para fusionar sin preguntar
MAX_CANDIDATOS = 6
# Una nota de seguimiento ("murió días después", "detuvieron al conductor") o de solo título no dice cuándo fue
# el hecho: su fecha es la de publicación (aproximada). Puede ser el mismo siniestro hasta estos días después,
# pero solo con coincidencia fuerte y nunca sin preguntar (medido el 20-11-2026: 5 siniestros duplicados así).
DIAS_SEGUIMIENTO = 14
PUNTAJE_SEGUIMIENTO = 3.0

FAMILIAS = {
    "choque_frontal": "choque", "choque_por_alcance": "choque", "choque_lateral": "choque",
    "choque_sin_detalle": "choque", "multiple": "choque", "vuelco": "salida", "despiste": "salida",
    "atropello": "atropello", "caida": "caida", "tren": "tren", "otro": "otro",
}
_GENERICOS = {"choque_sin_detalle", "otro"}
# Palabras de una vía que no la distinguen de otra (en Villa María, "bulevar" hizo fusionar dos choques en
# bulevares distintos el 20-11-2026)
_VACIAS_VIA = set("av avda avenida calle calles ruta rn rp nacional provincial km kilometro y e de del la el los las "
                  "altura esquina interseccion cruce acceso colectora bulevar boulevard bv bvar bvard rotonda diagonal "
                  "pasaje camino autopista autovia puente tramo zona barrio centro microcentro frente entre "
                  "ingreso salida norte sur este oeste lado".split())


# ------------------------------------------------------------------ utilidades sobre fichas

def clave_ficha(id_nota: str, i: int) -> str:
    return f"{id_nota}#{i}"


def ruta_y_km(via: str | None) -> tuple[str | None, int | None, int | None]:
    """("RN"|"RP"|"R", número, km) a partir de la vía extraída ("RN 9 km 320", "Ruta 153", "ruta provincial 2")."""
    v = normalizar(via or "")
    m = re.search(r"\b(rn|rp|ruta nacional|ruta provincial|ruta|autopista|autovia)\s*n?\s*(\d{1,4})\b", v)
    tipo = num = None
    if m:
        tipo = {"rn": "RN", "ruta nacional": "RN", "rp": "RP", "ruta provincial": "RP"}.get(m.group(1), "R")
        num = int(m.group(2))
    k = re.search(r"\bkm\s*(\d{1,4})", v)
    return tipo, num, int(k.group(1)) if k else None


def palabras_via(via: str | None, localidad: str | None = None) -> set[str]:
    """Palabras que distinguen una vía (sin genéricas ni el nombre de la propia localidad).

    Los números cuentan solo si la vía no es una ruta: en General Pico o La Plata las calles se llaman por
    número ("Calles 19 y 46"), y sin ellos dos esquinas distintas se fusionaban solas.
    """
    propias = set(normalizar(localidad or "").split())
    con_numeros = ruta_y_km(via)[1] is None
    return {w for w in normalizar(via or "").split()
            if w not in _VACIAS_VIA and w not in propias
            and ((con_numeros and len(w) <= 4) if w.isdigit() else len(w) > 2)}


def _comparten_calle(wa: set[str], wb: set[str]) -> bool:
    """Alguna palabra en común, tolerando errores de tipeo ("Chabacuco" por "Chacabuco")."""
    from difflib import SequenceMatcher

    return bool(wa & wb) or any(len(x) >= 5 and len(y) >= 5 and SequenceMatcher(None, x, y).ratio() >= 0.8
                                for x in wa for y in wb)


def _dias(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _heridos(f: dict) -> int | None:
    partes = [f.get(c) for c in ("heridos_graves", "heridos_leves", "heridos_sin_detalle")]
    return None if all(p is None for p in partes) else sum(p or 0 for p in partes)


def _prov(f: dict) -> str | None:
    return (f.get("geo") or {}).get("provincia_id") or f.get("provincia_id")


def _prov_segura(f: dict) -> str | None:
    """La provincia, salvo que sea inferida (del medio o de la búsqueda): esa es una pista, no un dato, y no
    alcanza para decir que dos fichas son de siniestros distintos (el choque de Canals, Córdoba, quedó además
    como un siniestro de La Pampa el 20-11-2026)."""
    return None if (f.get("geo") or {}).get("provincia_inferida") else _prov(f)


# ------------------------------------------------------------------ comparación

def comparar(a: dict, b: dict) -> tuple[bool, float]:
    """(compatibles, puntaje) entre dos fichas. Incompatibles: nunca son el mismo siniestro."""
    ok, puntaje, _ = comparar_detalle(a, b)
    return ok, puntaje


ABSOLUTA, TOLERABLE, NEUTRA = "absoluta", "tolerable", "neutra"


def comparar_detalle(a: dict, b: dict) -> tuple[bool, float, str | None]:
    """(compatibles, puntaje, tipo de contradicción).

    - absoluta: provincias distintas, fechas fuera de la ventana, rutas con distinto número. Ninguna otra
      ficha del evento la compensa.
    - tolerable: dos esquinas distintas. Dentro de un evento puede ser un dato mal de una sola nota, así que
      solo impide sumar la ficha si contradice a la mayoría (Evento.evaluar).
    - neutra: una nota de seguimiento lejana en días y sin coincidencia fuerte. No suma ni contradice.
    """
    pa, pb = _prov_segura(a), _prov_segura(b)
    if pa and pb and pa != pb:
        return False, 0.0, ABSOLUTA
    # provincias distintas y alguna inferida: puede ser el mismo siniestro, pero solo con coincidencia fuerte
    otra_provincia = bool(_prov(a) and _prov(b) and _prov(a) != _prov(b))
    aprox_a, aprox_b = bool(a.get("fecha_aproximada")), bool(b.get("fecha_aproximada"))
    dias = _dias(a["fecha_hecho"], b["fecha_hecho"])
    seguimiento = False
    if dias > (2 if (aprox_a or aprox_b) else 1):
        # solo si la fecha aproximada (la de publicación) es la posterior: el hecho no pudo pasar después
        posterior_aprox = aprox_a if a["fecha_hecho"] > b["fecha_hecho"] else aprox_b
        if not posterior_aprox or dias > DIAS_SEGUIMIENTO:
            return False, 0.0, ABSOLUTA
        seguimiento = True
    puntaje = 0.0
    ga, gb = a.get("geo") or {}, b.get("geo") or {}
    misma_localidad = bool(ga.get("localidad_id")) and ga.get("localidad_id") == gb.get("localidad_id")
    if not misma_localidad and not (ga.get("localidad_id") and gb.get("localidad_id")) and a.get("localidad") and b.get("localidad"):
        # una de las dos no se pudo ubicar ("entre Canals y La Carlota"): vale el nombre contenido en el otro
        la, lb = normalizar(a["localidad"]), normalizar(b["localidad"])
        misma_localidad = bool(la and lb) and (la in lb or lb in la)
    # Lugar
    if ga.get("localidad_id") and gb.get("localidad_id"):
        if misma_localidad:
            puntaje += 3
        elif ga.get("departamento_id") and ga.get("departamento_id") == gb.get("departamento_id"):
            puntaje += 1
        else:
            puntaje -= 2
    elif a.get("localidad") and b.get("localidad"):
        la, lb = normalizar(a["localidad"]), normalizar(b["localidad"])
        puntaje += 2 if (la in lb or lb in la) else -1
    elif ga.get("departamento_id") and ga.get("departamento_id") == gb.get("departamento_id"):
        puntaje += 1
    # Ruta y kilómetro
    ta, na, ka = ruta_y_km(a.get("via"))
    tb, nb, kb = ruta_y_km(b.get("via"))
    if na is not None and nb is not None:
        if na != nb:
            return False, 0.0, ABSOLUTA
        puntaje += 2
        if ka is not None and kb is not None:
            if abs(ka - kb) > 30:
                # En la misma localidad suele ser un error de un medio (pasa: "km 172" y "km 473" para el
                # mismo choque en Canals, 20-11-2026); en lugares distintos son siniestros distintos.
                if not misma_localidad:
                    return False, 0.0, ABSOLUTA
                puntaje -= 1
            else:
                puntaje += 1 if abs(ka - kb) <= 10 else 0
    else:
        wa = palabras_via(a.get("via"), a.get("localidad") or ga.get("localidad"))
        wb = palabras_via(b.get("via"), b.get("localidad") or gb.get("localidad"))
        if wa and wb:
            if _comparten_calle(wa, wb):
                puntaje += 2
            elif len(wa) >= 2 and len(wb) >= 2:
                # dos esquinas distintas, cada una con sus dos calles: siniestros distintos
                return False, 0.0, TOLERABLE
            else:
                puntaje -= 3
    # Vehículos
    va, vb = set(a.get("vehiculos") or []), set(b.get("vehiculos") or [])
    if va and vb:
        comun = va & vb
        puntaje += 2 * len(comun) / len(va | vb) if comun else -2
    # Tipo de siniestro
    fa, fb = FAMILIAS.get(a.get("tipo_siniestro")), FAMILIAS.get(b.get("tipo_siniestro"))
    if fa and fb and "otro" not in (fa, fb):
        puntaje += 1 if fa == fb else -1
    # Franja horaria
    ha, hb = a.get("hora_franja"), b.get("hora_franja")
    if ha and hb and "desconocida" not in (ha, hb):
        puntaje += 1 if ha == hb else -1.5
    # Víctimas fatales
    ma, mb = a.get("fallecidos"), b.get("fallecidos")
    if ma is not None and mb is not None:
        if ma > 0 and mb > 0:
            puntaje += 1
        elif (ma > 0) != (mb > 0):
            puntaje -= 0.5  # puede ser una cifra que se actualizó
    # Grupos etarios
    if set(a.get("grupos_etarios") or []) & set(b.get("grupos_etarios") or []):
        puntaje += 0.5
    if seguimiento or otra_provincia:
        if puntaje < PUNTAJE_SEGUIMIENTO:
            return False, 0.0, NEUTRA
        puntaje = min(puntaje, UMBRAL_FUSION - 0.5)   # nunca se fusiona sola: decide el desempate
    return True, puntaje, None


def _debil(f: dict) -> bool:
    """Ficha con poca información (solo título o confianza baja): casi nunca alcanza el puntaje por sí sola."""
    return f.get("_fuente_texto") == "titulo" or f.get("confianza") == "baja"


# ------------------------------------------------------------------ eventos

class Evento:
    def __init__(self, ficha: dict):
        self.fichas = [ficha]

    @property
    def claves(self) -> set[str]:
        return {f["_clave"] for f in self.fichas}

    @property
    def notas(self) -> set[str]:
        return {f["_id_nota"] for f in self.fichas}

    def evaluar(self, ficha: dict) -> tuple[bool, float]:
        """Máximo puntaje contra sus fichas, menos 1 por cada ficha que contradice.

        Una contradicción absoluta con cualquier ficha (provincia, fecha, número de ruta) la deja afuera. Una
        tolerable (dos esquinas distintas) solo si contradice a la mayoría: una nota con una calle equivocada no
        impide sumar las demás.
        """
        if ficha["_id_nota"] in self.notas:  # dos siniestros de una misma nota son siniestros distintos
            return False, 0.0
        puntajes, contradicciones = [], 0
        for f in self.fichas:
            ok, p, tipo = comparar_detalle(ficha, f)
            if ok:
                puntajes.append(p)
            elif tipo == ABSOLUTA:
                return False, 0.0
            elif tipo == TOLERABLE:
                contradicciones += 1
        if not puntajes or contradicciones * 2 > len(self.fichas):
            return False, 0.0
        return True, max(puntajes) - contradicciones


def _calidad(f: dict) -> tuple:
    return (f.get("_fuente_texto") == "completo", {"alta": 2, "media": 1, "baja": 0}.get(f.get("confianza"), 0), f["_publicada"])


DESMIENTEN_FALLECIDOS = 3   # notas completas posteriores con una cifra menor que dejan afuera la de una sola nota


def _fallecidos(fichas: list[dict]) -> int | None:
    """La cifra de fallecidos más alta, salvo que la dé una sola nota y la desmientan las posteriores.

    Las muertes no bajan: una nota posterior que no las menciona, o que dice 0, no borra una ya informada (alguien
    puede morir días después). Pero si la cifra sale de una sola nota y al menos DESMIENTEN_FALLECIDOS notas
    publicadas después dan una menor, lo más probable es que esa nota hable de otro siniestro que se fusionó de más
    (por ejemplo, por una fecha mal leída): se descarta y se mira la cifra siguiente. Caso real: el choque con
    incendio en la Panamericana del 21-11-2026 le pasaba sus 3 muertes al choque sin víctimas fatales del 22-11.
    """
    informados = sorted((f["_publicada"], f["fallecidos"]) for f in fichas if f.get("fallecidos") is not None)
    cifras = sorted({c for _, c in informados}, reverse=True)
    for cifra in cifras:
        con = [p for p, c in informados if c >= cifra]
        if cifra == cifras[-1] or len(con) > 1:
            return cifra
        if sum(1 for p, c in informados if c < cifra and p > con[0]) < DESMIENTEN_FALLECIDOS:
            return cifra
    return None


def consolidar(ev: Evento, id_evento: str) -> dict:
    """Arma el registro publicable del evento a partir de sus fichas."""
    fichas = sorted(ev.fichas, key=lambda f: f["_publicada"])
    por_calidad = sorted(fichas, key=_calidad, reverse=True)
    completas = [f for f in fichas if f.get("_fuente_texto") == "completo"] or fichas

    def primero(campo, invalidos=(None, "", "desconocida")):
        return next((f[campo] for f in por_calidad if f.get(campo) not in invalidos), None)

    # Fecha: la más repetida entre las fichas con fecha clara; si no hay, la más temprana
    claras = [f["fecha_hecho"] for f in fichas if not f.get("fecha_aproximada")]
    fecha = Counter(claras).most_common(1)[0][0] if claras else min(f["fecha_hecho"] for f in fichas)
    # Tipo: el más repetido entre los específicos (no "choque_sin_detalle" ni "otro")
    tipos = [f["tipo_siniestro"] for f in completas if f.get("tipo_siniestro") not in _GENERICOS]
    tipo = Counter(tipos).most_common(1)[0][0] if tipos else primero("tipo_siniestro", (None, ""))
    # Fallecidos: la cifra más alta entre las notas de texto completo (si no hay, entre los titulares)
    fallecidos = _fallecidos(completas)
    # Heridos: de la nota más reciente que los informa (las cifras cambian con los días)
    con_heridos = next((f for f in reversed(completas) if _heridos(f) is not None), None)
    heridos = {c: (con_heridos or {}).get(c) for c in ("heridos_graves", "heridos_leves", "heridos_sin_detalle")}
    # Factores: unión; queda "presunto" salvo que todas las notas que lo mencionan lo den por comprobado
    factores: dict[str, bool] = {}
    for f in fichas:
        for x in f.get("factores_mencionados") or []:
            factores[x["factor"]] = factores.get(x["factor"], False) or x["presunto"]
    # una provincia confirmada por alguna nota pesa más que cualquier ubicación con provincia inferida
    geo = max((f.get("geo") or {} for f in fichas),
              key=lambda g: (bool(g.get("provincia_id")) and not g.get("provincia_inferida"),
                             {"localidad": 3, "departamento": 2, "provincia": 1}.get(g.get("nivel"), 0)))
    mejor = por_calidad[0]
    fuentes, vistas = [], set()
    for f in fichas:
        if f["_url"] in vistas:
            continue
        vistas.add(f["_url"])
        fuentes.append({"medio": f["_medio"], "url": f["_url"], "publicada": f["_publicada"], "texto": f["_fuente_texto"]})
    return {
        "id_evento": id_evento,
        "fecha_hecho": fecha,
        "fecha_aproximada": not claras,
        "hora_franja": primero("hora_franja") or "desconocida",
        "provincia_id": geo.get("provincia_id") or _prov(mejor),
        "provincia": geo.get("provincia") or mejor.get("provincia"),
        "departamento": geo.get("departamento"),
        "localidad": geo.get("localidad") or primero("localidad"),
        "lat": geo.get("lat"), "lon": geo.get("lon"), "nivel_geo": geo.get("nivel", "ninguno"),
        "provincia_inferida": bool(geo.get("provincia_inferida")),
        "via": primero("via"),
        "tipo_via": primero("tipo_via") or "desconocida",
        "tipo_siniestro": tipo,
        "vehiculos": sorted({v for f in completas for v in f.get("vehiculos") or []}),
        "fallecidos": fallecidos,
        **heridos,
        "heridos_total": _heridos(heridos),
        "factores_mencionados": [{"factor": k, "presunto": v} for k, v in sorted(factores.items())],
        "grupos_etarios": sorted({g for f in completas for g in f.get("grupos_etarios") or []}),
        "resumen": mejor.get("resumen"),
        "confianza": max((f.get("confianza") for f in fichas), key=lambda c: {"alta": 2, "media": 1, "baja": 0}.get(c, 0)),
        "solo_titulos": all(f.get("_fuente_texto") == "titulo" for f in fichas),
        "n_fuentes": len(fuentes),
        "fuentes": fuentes,
        "fichas": sorted(ev.claves),
        "primera_publicacion": fichas[0]["_publicada"],
        "ultima_publicacion": fichas[-1]["_publicada"],
    }


def fichas_de(notas) -> list[dict]:
    """Fichas de siniestro de todas las notas, con los datos de la nota que hacen falta para agrupar."""
    fichas = []
    for n in notas.todas():
        if n.get("categoria") != "siniestro":
            continue
        for i, f in enumerate(n.get("siniestros") or []):
            fichas.append({**f, "_clave": clave_ficha(n["id_nota"], i), "_id_nota": n["id_nota"], "_url": n["url"],
                           "_medio": n.get("medio") or n.get("sitio"), "_publicada": n["publicada"],
                           "_fuente_texto": n.get("fuente_texto")})
    return sorted(fichas, key=lambda f: (f["_publicada"], f["_clave"]))


# ------------------------------------------------------------------ desempate con Claude

class Desempate:
    """Pregunta a Claude si una ficha es el mismo siniestro que alguno de los eventos candidatos."""

    SISTEMA = """Sos analista del Radar Vial del Observatorio Humanitario de Cruz Roja Argentina. Varios medios cuentan el mismo siniestro vial; tu tarea es decidir si una ficha nueva describe el mismo siniestro que alguno de los eventos candidatos.
Compará lugar, ruta o calle, vehículos, tipo de siniestro, momento del día y víctimas. Las cifras de víctimas pueden cambiar entre notas (un herido que muere después) y los medios describen distinto el mismo hecho (camioneta o auto, choque o vuelco). Si los datos son compatibles y nada importante se contradice, es el mismo siniestro. Si hay una diferencia clara de lugar, de vehículos o de momento, son siniestros distintos.
Una fecha "(aproximada)" es la de publicación de la nota, no la del hecho: una nota de seguimiento (la persona murió días después, detuvieron al conductor, pedido de justicia) puede publicarse varios días más tarde y es el mismo siniestro si coinciden el lugar y las circunstancias. Una provincia entre paréntesis puede faltar o estar mal en notas con pocos datos: no alcanza por sí sola para descartar. Si la ficha nueva no trae lugar y solo coincide en datos comunes a muchos siniestros (los vehículos, el tipo, una persona herida), respondé null: hace falta un detalle distintivo en común (la calle o la ruta, una circunstancia particular, una lesión o un dato poco frecuente). Ante la duda, respondé null: es peor unir dos siniestros distintos que dejar uno repetido.
Respondé con el número del evento que es el mismo siniestro, o null si no es ninguno."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "mismo_evento": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "seguridad": {"type": "string", "enum": ["alta", "media", "baja"]},
        },
        "required": ["mismo_evento", "seguridad"],
        "additionalProperties": False,
    }

    def __init__(self, claude, titulos: dict[str, str] | None = None, archivo=ARCHIVO_DECISIONES):
        self.claude = claude
        self.titulos = titulos or {}
        self.archivo = archivo
        self.cache: dict[str, dict] = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}
        self.consultas = 0
        self._lock = threading.Lock()   # `preguntar` se puede llamar desde varios hilos (recuperación histórica)

    @staticmethod
    def _describir(f: dict, titulo: str | None) -> str:
        partes = [f"fecha {f['fecha_hecho']}{' (aproximada)' if f.get('fecha_aproximada') else ''}",
                  f"franja {f.get('hora_franja')}", f"lugar: {f.get('localidad') or '?'} ({f.get('provincia') or '?'})",
                  f"vía: {f.get('via') or '?'}", f"tipo: {f.get('tipo_siniestro')}",
                  f"vehículos: {', '.join(f.get('vehiculos') or []) or '?'}",
                  f"fallecidos: {f.get('fallecidos')}", f"heridos: {_heridos(f)}"]
        texto = "; ".join(partes) + f"\n   Resumen: {f.get('resumen')}"
        if titulo:
            texto += f"\n   Título de la nota: {titulo}"
        return texto

    def previa(self, ficha: dict, candidatos: list[Evento]) -> tuple[bool, Evento | None]:
        """(ya decidido, evento elegido) según las decisiones guardadas. Se busca por pertenencia: desde la decisión, el
        evento elegido (o los consultados) pudo sumar fichas y cambiar de ancla, y sigue siendo el mismo siniestro."""
        previa = self.cache.get(ficha["_clave"])
        if previa:
            if previa["elegido"] is not None:
                for ev in candidatos:
                    if previa["elegido"] in ev.claves:
                        return True, ev
            elif all(ev.claves & set(previa["consultados"]) for ev in candidatos):
                return True, None
        return False, None

    def decidir(self, ficha: dict, candidatos: list[Evento]) -> Evento | None:
        sabida, elegido = self.previa(ficha, candidatos)
        if sabida:
            return elegido
        if self.claude is None:  # sin API (pruebas o demo): no se fusiona lo dudoso
            return None
        return self.preguntar(ficha, candidatos)

    def preguntar(self, ficha: dict, candidatos: list[Evento]) -> Evento | None:
        """Pregunta a Claude y guarda la decisión (sin mirar las guardadas)."""
        anclas = [sorted(ev.claves)[0] for ev in candidatos]
        lineas = ["FICHA NUEVA:", "   " + self._describir(ficha, self.titulos.get(ficha["_id_nota"])), "", "EVENTOS CANDIDATOS:"]
        for i, ev in enumerate(candidatos, 1):
            lineas.append(f"{i}.")
            for f in ev.fichas[:3]:
                lineas.append("   - " + self._describir(f, self.titulos.get(f["_id_nota"])))
        conf = config.general()
        from .claude import ErrorClaude

        try:
            resp = self.claude.json("eventos", conf["modelos"]["eventos"], self.SISTEMA, "\n".join(lineas), self.SCHEMA,
                                    esfuerzo=conf["esfuerzo"]["eventos"], max_tokens=8000)
        except ErrorClaude:
            return None  # ante la duda y sin respuesta, evento aparte (se vuelve a preguntar en la próxima corrida)
        n = resp.get("mismo_evento")
        elegido = candidatos[n - 1] if isinstance(n, int) and 1 <= n <= len(candidatos) and resp.get("seguridad") in ("alta", "media") else None
        with self._lock:
            self.consultas += 1
            self.cache[ficha["_clave"]] = {"elegido": sorted(elegido.claves)[0] if elegido else None, "consultados": anclas,
                                           "seguridad": resp.get("seguridad")}
        return elegido

    def guardar(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            texto = json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True)
        self.archivo.write_text(texto, encoding="utf-8")


# ------------------------------------------------------------------ agrupación completa

def agrupar(fichas: list[dict], desempate: Desempate | None = None) -> list[Evento]:
    from datetime import timedelta

    eventos: list[Evento] = []
    por_fecha: dict[str, list[Evento]] = {}   # índice: solo se comparan eventos de fechas cercanas
    por_fecha_aprox: dict[str, list[Evento]] = {}   # eventos con alguna ficha de fecha aproximada en ese día

    def registrar(ev: Evento, ficha: dict) -> None:
        indices = [por_fecha, por_fecha_aprox] if ficha.get("fecha_aproximada") else [por_fecha]
        for indice in indices:
            lista = indice.setdefault(ficha["fecha_hecho"], [])
            if ev not in lista:
                lista.append(ev)

    for ficha in fichas:
        d = date.fromisoformat(ficha["fecha_hecho"])
        cercanos: list[Evento] = []
        # ±2 días siempre; una nota de seguimiento mira además hasta DIAS_SEGUIMIENTO hacia atrás, y una nota
        # con fecha clara mira hacia adelante solo los eventos que tienen notas de fecha aproximada
        vistas = [(por_fecha, delta) for delta in range(-2, 3)]
        if ficha.get("fecha_aproximada"):
            vistas += [(por_fecha, -delta) for delta in range(3, DIAS_SEGUIMIENTO + 1)]
        else:
            vistas += [(por_fecha_aprox, delta) for delta in range(3, DIAS_SEGUIMIENTO + 1)]
        for indice, delta in vistas:
            for ev in indice.get((d + timedelta(days=delta)).isoformat(), []):
                if ev not in cercanos:
                    cercanos.append(ev)
        evaluados = []
        for ev in cercanos:
            ok, p = ev.evaluar(ficha)
            if ok:
                evaluados.append((p, ev))
        evaluados.sort(key=lambda x: -x[0])
        elegido = None
        if evaluados:
            mejor, ev = evaluados[0]
            segundo = evaluados[1][0] if len(evaluados) > 1 else float("-inf")
            if mejor >= UMBRAL_FUSION and mejor - segundo >= MARGEN and not _debil(ficha):
                elegido = ev
            elif desempate is not None:
                minimo = 0.0 if _debil(ficha) else UMBRAL_CONSULTA
                candidatos = [e for p, e in evaluados if p >= minimo][:MAX_CANDIDATOS]
                if candidatos:
                    elegido = desempate.decidir(ficha, candidatos)
        if elegido:
            elegido.fichas.append(ficha)
        else:
            elegido = Evento(ficha)
            eventos.append(elegido)
        registrar(elegido, ficha)
    return eventos


def _id_nuevo(ev: Evento) -> str:
    primera = min(ev.fichas, key=lambda f: (f["_publicada"], f["_clave"]))
    prov = _prov(primera) or "00"
    return f"ev_{primera['fecha_hecho'].replace('-', '')}_{prov}_{hashlib.sha1(primera['_clave'].encode()).hexdigest()[:6]}"


def asignar_ids(eventos: list[Evento], anteriores: list[dict]) -> list[str]:
    """Cada evento hereda el id del evento anterior con el que comparte más fichas (sin repetir)."""
    por_ficha = {c: e["id_evento"] for e in anteriores for c in e["fichas"]}
    usados, ids = set(), []
    orden = sorted(range(len(eventos)), key=lambda i: -len(eventos[i].fichas))
    elegidos: dict[int, str] = {}
    for i in orden:
        votos = Counter(por_ficha[c] for c in eventos[i].claves if c in por_ficha)
        candidato = next((idv for idv, _ in votos.most_common() if idv not in usados), None)
        if candidato:
            usados.add(candidato)
            elegidos[i] = candidato
    for i, ev in enumerate(eventos):
        idv = elegidos.get(i) or _id_nuevo(ev)
        while idv in usados and i not in elegidos:
            idv += "x"
        usados.add(idv)
        ids.append(idv)
    return ids


def cargar(archivo=ARCHIVO) -> list[dict]:
    if not archivo.exists():
        return []
    with open(archivo, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def guardar(eventos: list[dict], archivo=ARCHIVO) -> None:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    with open(archivo, "w", encoding="utf-8") as f:
        for e in sorted(eventos, key=lambda e: (e["fecha_hecho"], e["id_evento"])):
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")


def armar_eventos(notas, claude=None, titulos: dict[str, str] | None = None, log=print,
                  archivo=ARCHIVO, archivo_decisiones=ARCHIVO_DECISIONES) -> list[dict]:
    """Rehace todos los eventos a partir de las fichas guardadas, conservando ids. Devuelve los eventos."""
    desempate = Desempate(claude, titulos, archivo_decisiones)
    fichas = fichas_de(notas)
    eventos = agrupar(fichas, desempate)
    anteriores = cargar(archivo)
    ids = asignar_ids(eventos, anteriores)
    registros = [consolidar(ev, idv) for ev, idv in zip(eventos, ids)]
    guardar(registros, archivo)
    desempate.guardar()
    multi = sum(1 for r in registros if r["n_fuentes"] > 1)
    log(f"Eventos: {len(registros)} siniestros a partir de {len(fichas)} fichas ({multi} con más de una fuente); "
        f"{desempate.consultas} desempates consultados a Claude.")
    return registros
