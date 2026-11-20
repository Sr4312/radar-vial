"""Extracción estructurada (Sonnet): la ficha de cada nota relevante.

Con el texto completo, el modelo confirma la categoría (siniestro, contexto o descartar) y completa una ficha
por cada siniestro que la nota describe (casi siempre uno). Regla de oro: lo que la nota no dice va `null`.
Preferimos subestimar a inventar. Las fichas no llevan nombres, edades exactas ni datos que identifiquen a
nadie (privacidad.py lo controla de nuevo al final).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import config
from .claude import Claude, ErrorClaude
from .privacidad import limpiar_ficha, nombres_en_texto, nombres_probables

ART = timezone(timedelta(hours=-3))

TIPOS_SINIESTRO = ["choque_frontal", "choque_por_alcance", "choque_lateral", "choque_sin_detalle", "vuelco", "atropello",
                   "despiste", "caida", "tren", "multiple", "otro"]
VEHICULOS = ["auto", "moto", "camion", "colectivo", "bicicleta", "peaton", "tren", "utilitario", "otro"]
TIPOS_VIA = ["ruta_nacional", "ruta_provincial", "autopista", "urbana", "rural", "desconocida"]
FRANJAS = ["madrugada", "manana", "tarde", "noche", "desconocida"]
FACTORES = ["alcohol", "velocidad", "celular", "clima", "estado_de_la_ruta", "fatiga", "sobrepaso", "sin_casco",
            "sin_cinturon", "animal_suelto", "semaforo_o_prioridad", "falla_mecanica", "otro"]
GRUPOS_ETARIOS = ["ninez", "adolescencia", "joven", "adulto", "persona_mayor"]
SUBTIPOS_CONTEXTO = ["control_alcoholemia", "normativa", "estadistica", "infraestructura_rutas", "campana", "otro"]
CONFIANZA = ["alta", "media", "baja"]

_ENTERO_O_NULO = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_TEXTO_O_NULO = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_FECHA_O_NULA = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}


def _enum(valores):
    return {"type": "string", "enum": valores}


FICHA_SINIESTRO = {
    "type": "object",
    "properties": {
        "fecha_hecho": _FECHA_O_NULA,
        "fecha_aproximada": {"type": "boolean"},
        "hora_franja": _enum(FRANJAS),
        "provincia": _TEXTO_O_NULO,
        "departamento": _TEXTO_O_NULO,
        "localidad": _TEXTO_O_NULO,
        "via": _TEXTO_O_NULO,
        "tipo_via": _enum(TIPOS_VIA),
        "tipo_siniestro": _enum(TIPOS_SINIESTRO),
        "vehiculos": {"type": "array", "items": _enum(VEHICULOS)},
        "fallecidos": _ENTERO_O_NULO,
        "heridos_graves": _ENTERO_O_NULO,
        "heridos_leves": _ENTERO_O_NULO,
        "heridos_sin_detalle": _ENTERO_O_NULO,
        "factores_mencionados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"factor": _enum(FACTORES), "presunto": {"type": "boolean"}},
                "required": ["factor", "presunto"],
                "additionalProperties": False,
            },
        },
        "grupos_etarios": {"type": "array", "items": _enum(GRUPOS_ETARIOS)},
        "resumen": {"type": "string"},
        "confianza": _enum(CONFIANZA),
    },
    "required": ["fecha_hecho", "fecha_aproximada", "hora_franja", "provincia", "departamento", "localidad", "via",
                 "tipo_via", "tipo_siniestro", "vehiculos", "fallecidos", "heridos_graves", "heridos_leves",
                 "heridos_sin_detalle", "factores_mencionados", "grupos_etarios", "resumen", "confianza"],
    "additionalProperties": False,
}

FICHA_CONTEXTO = {
    "type": "object",
    "properties": {
        "subtipo": _enum(SUBTIPOS_CONTEXTO),
        "ambito": _enum(["nacional", "provincial", "municipal"]),
        "provincia": _TEXTO_O_NULO,
        "fecha": _FECHA_O_NULA,
        "organismo": _TEXTO_O_NULO,
        "dato_clave": _TEXTO_O_NULO,
        "resumen": {"type": "string"},
        "confianza": _enum(CONFIANZA),
    },
    "required": ["subtipo", "ambito", "provincia", "fecha", "organismo", "dato_clave", "resumen", "confianza"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "categoria": _enum(["siniestro", "contexto", "descartar"]),
        "siniestros": {"type": "array", "items": FICHA_SINIESTRO},
        "contexto": {"anyOf": [FICHA_CONTEXTO, {"type": "null"}]},
    },
    "required": ["categoria", "siniestros", "contexto"],
    "additionalProperties": False,
}


def _sistema() -> str:
    provincias = ", ".join(p["corto"] if p["id"] != "94" else "Tierra del Fuego" for p in config.provincias())
    return f"""Sos analista del Radar Vial del Observatorio Humanitario de Cruz Roja Argentina. Leés una nota de prensa argentina y completás una ficha estructurada. La unidad de análisis es el siniestro, no la nota.

REGLA DE ORO: si la nota no dice un dato, va null (o "desconocida"). Nunca inventes ni deduzcas lo que no está escrito. Preferimos subestimar a inventar.

CATEGORÍA
- "siniestro": la nota informa uno o más siniestros viales concretos en Argentina (choque, vuelco, atropello, despiste, caída de moto o bicicleta, tren en paso a nivel, etc.), incluidas las notas de seguimiento de un siniestro reciente (murió una persona herida, se completó la cifra de víctimas). Completá una ficha en "siniestros" por cada siniestro distinto que la nota describe con su propio lugar o momento (casi siempre es uno). "contexto" va null.
- "contexto": seguridad vial en Argentina sin un siniestro concreto: controles y alcoholemia, normas, estadísticas oficiales o balances con cifras agregadas sin detalle de cada siniestro, estado de rutas e infraestructura, campañas. Completá "contexto"; "siniestros" va vacío.
- "descartar": no es un siniestro vial (accidente doméstico o laboral, "choque" figurado, deporte de motor en competencia, robo), ocurrió fuera de Argentina, o trata de un siniestro de hace más de 30 días (juicio, aniversario, condena) sin víctimas nuevas. "siniestros" vacío y "contexto" null.

FICHA DE SINIESTRO
- fecha_hecho: fecha del siniestro (AAAA-MM-DD), no la de la nota ni la de la muerte posterior de un herido. Resolvé "ayer", "el domingo", "esta madrugada" con la fecha de publicación que se indica. El año es el de la publicación salvo que la nota diga otro (si la nota dice "viernes 14" y el día de la semana no coincide, gana el número del día). Si la nota no permite saberla, poné la fecha de publicación y fecha_aproximada true; si la fecha es clara, fecha_aproximada false.
- hora_franja: madrugada (0 a 6 h), manana (6 a 12 h), tarde (12 a 19 h), noche (19 a 24 h) o desconocida.
- provincia: una de estas, escrita igual: {provincias}. null si no se sabe.
- departamento: departamento o partido, solo si la nota lo nombra. localidad: ciudad, pueblo, barrio o paraje tal como lo nombra la nota.
- via: la ruta o calle, abreviada: "RN 9 km 320", "RP 2", "Autopista Riccheri", "Av. Rivadavia y Nazca". tipo_via: ruta_nacional, ruta_provincial, autopista (incluye autovías), urbana (calles y avenidas de una ciudad o pueblo), rural (caminos rurales o de tierra) o desconocida.
- tipo_siniestro: choque_frontal; choque_por_alcance (un vehículo embiste a otro desde atrás); choque_lateral (incluye choques en esquinas o cruces); choque_sin_detalle (dos vehículos chocaron y la nota no dice cómo); vuelco; atropello (un vehículo embiste a un peatón, o a un ciclista cuando la nota lo describe como atropello); despiste (salida de la calzada o choque contra un objeto fijo, sin vuelco); caida (de moto o bicicleta sin otro vehículo); tren (un tren está involucrado); multiple (tres o más vehículos); otro.
- vehiculos: tipos involucrados, sin repetir: auto, moto, camion, colectivo, bicicleta, peaton, tren, utilitario (camioneta, pick-up, furgón, combi) u otro (tractor, maquinaria, carro).
- fallecidos: personas que murieron por el siniestro, incluidas las que murieron después si la nota lo dice. heridos_graves: descriptas como graves, en estado crítico o delicado, con pronóstico reservado o en terapia intensiva. heridos_leves: descriptas como leves o con lesiones menores. heridos_sin_detalle: heridas sin que se indique gravedad. Cada persona cuenta en un solo campo. Si dice "al menos dos", poné 2; si dice "varios" sin número, null. Si la nota dice que no hubo heridos o víctimas, poné 0.
- factores_mencionados: solo los que la nota menciona como posible causa o circunstancia del siniestro. Un control con resultado negativo (por ejemplo, alcoholemia negativa) no es un factor: no lo incluyas. presunto true si la nota lo presenta como hipótesis o investigación ("se investiga si", "habría", "según testigos", "presuntamente"); false si lo informa como un hecho comprobado (por ejemplo, el resultado de un test de alcoholemia). No atribuyas culpas ni deduzcas causas.
- grupos_etarios: de las personas involucradas, según edades o descripciones de la nota: ninez (0 a 12 años), adolescencia (13 a 17), joven (18 a 29), adulto (30 a 64), persona_mayor (65 o más). Sin repetir.
- resumen: UNA oración neutra, de hasta 35 palabras, en español rioplatense, con el tipo de siniestro, el lugar, los vehículos y las víctimas. Ejemplo: "Choque frontal entre un auto y una camioneta en la RN 34, cerca de Rafaela: una persona murió y dos resultaron heridas." Describe el siniestro, no la nota: no menciones la nota, el título ni qué datos faltan (si falta un dato, simplemente no lo incluyas).
- confianza: alta (datos claros y concretos), media (datos incompletos o vagos), baja (solo el título o datos contradictorios).

FICHA DE CONTEXTO
- subtipo: control_alcoholemia, normativa, estadistica, infraestructura_rutas, campana u otro. ambito: nacional, provincial o municipal. provincia: igual que arriba, o null si es nacional. fecha: la del hecho o anuncio. organismo: institución que informa o actúa (nunca una persona). dato_clave: la cifra o medida principal en pocas palabras, o null. resumen: una oración neutra. confianza: como arriba.

PRIVACIDAD (obligatorio, lo publica la Cruz Roja)
- Nunca escribas nombres ni apellidos de víctimas, conductores, testigos o familiares, ni apodos, edades exactas, patentes, domicilios, escuelas o lugares de trabajo.
- Tampoco ocupaciones, cargos, profesiones o pertenencia a una fuerza o institución (policía, docente, médico, chofer de aplicación), ni vínculos familiares entre las personas ("junto a su hijo"), ni nacionalidad u origen: junto con la fecha y el lugar pueden identificar a alguien. Nombrá a las personas solo por su rol en el siniestro: conductor, acompañante, motociclista, ciclista, peatón, una persona.
- Nunca identifiques a niñas, niños o adolescentes: a lo sumo "una persona menor de edad", "un niño" o "una adolescente", sin más datos.
- No atribuyas culpas ni uses palabras como "imprudente", "irresponsable" o "por culpa de"."""


def _mensaje(nota: dict, texto: str | None) -> str:
    publicada = datetime.fromisoformat(nota["publicada"]).astimezone(ART)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    prov_medio = config.provincia_por_id(nota.get("provincia_medio") or "")
    partes = [
        f"Fecha de publicación: {publicada.date().isoformat()} ({dias[publicada.weekday()]}), hora Argentina {publicada:%H:%M}",
        f"Medio: {nota.get('medio') or nota.get('sitio')}" + (f" (medio de {prov_medio['corto']})" if prov_medio else ""),
        f"Título: {nota['titulo']}",
    ]
    if nota.get("bajada"):
        partes.append(f"Bajada: {nota['bajada']}")
    if texto:
        partes.append("Texto de la nota:\n" + texto)
    else:
        partes.append("No se pudo leer el texto de la nota: solo hay título (y bajada si figura). Completá lo que "
                      "permitan, dejá el resto en null y poné confianza baja. El resumen cuenta el siniestro con lo "
                      "que dice el título, sin aclarar que es un título ni qué datos faltan.")
    return "\n".join(partes)


def _normalizar_provincia(nombre: str | None) -> str | None:
    """Devuelve el id de provincia (o None) a partir del nombre que escribió el modelo."""
    from .texto import normalizar

    if not nombre:
        return None
    n = normalizar(nombre)
    for p in config.provincias():
        opciones = [p["nombre"], p["corto"], *(p.get("alias") or [])]
        if any(normalizar(o) == n for o in opciones):
            return p["id"]
    return None


def _validar_siniestro(f: dict, publicada: date) -> dict:
    for campo in ("fallecidos", "heridos_graves", "heridos_leves", "heridos_sin_detalle"):
        if f.get(campo) is not None and f[campo] < 0:
            f[campo] = None
    f["vehiculos"] = sorted(set(f.get("vehiculos") or []), key=VEHICULOS.index)
    f["grupos_etarios"] = sorted(set(f.get("grupos_etarios") or []), key=GRUPOS_ETARIOS.index)
    vistos, factores = set(), []
    for x in f.get("factores_mencionados") or []:
        if x["factor"] not in vistos:
            vistos.add(x["factor"])
            factores.append(x)
    f["factores_mencionados"] = factores
    # Fecha: nunca posterior a la publicación; si falta, la de publicación marcada como aproximada.
    try:
        fh = date.fromisoformat(f["fecha_hecho"]) if f.get("fecha_hecho") else None
    except ValueError:
        fh = None
    if fh is None or fh > publicada:
        f["fecha_hecho"], f["fecha_aproximada"] = publicada.isoformat(), True
    else:
        f["fecha_hecho"] = corregir_anio(fh, publicada).isoformat()
    f["provincia_id"] = _normalizar_provincia(f.get("provincia"))
    return f


DIAS_MAXIMOS = 30


def corregir_anio(fh: date, publicada: date) -> date:
    """Si la fecha quedó a más de 30 días de la publicación pero con el año de la publicación cae dentro de esos
    30 días, el año estaba mal (pasó el 20-11-2026: "viernes 14 de noviembre" se leyó como 2025)."""
    if (publicada - fh).days <= DIAS_MAXIMOS:
        return fh
    for anio in (publicada.year, publicada.year - 1):
        try:
            candidata = fh.replace(year=anio)
        except ValueError:  # 29 de febrero
            continue
        if 0 <= (publicada - candidata).days <= DIAS_MAXIMOS:
            return candidata
    return fh


def es_viejo(f: dict, publicada: date) -> bool:
    """Siniestro de hace más de 30 días (juicios, aniversarios): no se cuenta."""
    return (publicada - date.fromisoformat(f["fecha_hecho"])).days > DIAS_MAXIMOS


def extraer_nota(claude: Claude, nota: dict, texto: str | None) -> dict:
    """Devuelve {categoria, siniestros, contexto} ya validado y revisado por privacidad. Lanza ErrorClaude."""
    conf = config.general()
    max_car = conf["limites"]["max_caracteres_texto"]
    recortado = bool(texto) and len(texto) > max_car
    resp = claude.json("extraccion", conf["modelos"]["extraccion"], _sistema(), _mensaje(nota, texto[:max_car] if texto else None),
                       SCHEMA, esfuerzo=conf["esfuerzo"]["extraccion"], max_tokens=16000)
    publicada = datetime.fromisoformat(nota["publicada"]).astimezone(ART).date()
    # Nombres de personas que aparecen en el texto (para comprobar que no se colaron en la ficha)
    fuente = f"{nota['titulo']}\n{texto or ''}"
    nombres, probables = nombres_en_texto(fuente), nombres_probables(fuente)
    siniestros = []
    if resp["categoria"] == "siniestro":
        for f in resp.get("siniestros") or []:
            f = _validar_siniestro(f, publicada)
            if es_viejo(f, publicada):
                continue
            siniestros.append(limpiar_ficha(f, nombres, probables))
        if not siniestros:  # dijo siniestro pero no completó ninguna ficha: no se cuenta
            resp["categoria"] = "descartar"
    contexto = None
    if resp["categoria"] == "contexto" and resp.get("contexto"):
        contexto = resp["contexto"]
        contexto["provincia_id"] = _normalizar_provincia(contexto.get("provincia"))
        contexto = limpiar_ficha(contexto, nombres, probables)
    if resp["categoria"] == "contexto" and contexto is None:
        resp["categoria"] = "descartar"
    return {"categoria": resp["categoria"], "siniestros": siniestros, "contexto": contexto, "texto_recortado": recortado}
