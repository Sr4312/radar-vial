"""Controles de privacidad sobre las fichas, después de la extracción (segunda red de seguridad).

La consigna del modelo ya prohíbe nombres, edades exactas y datos identificatorios. Acá se comprueba:
- que ningún nombre de persona del texto original aparezca en la ficha (se detectan con los patrones con los
  que la prensa presenta a las personas: "Nombre Apellido, de 34 años", "identificado como...", "Nombre (34)");
- que el resumen no tenga edades exactas.
Si un nombre se coló en el resumen, el resumen se reemplaza por uno armado con los campos de la ficha; si se
coló en otro campo de texto, ese campo queda null.
"""
from __future__ import annotations

import re

_MAY = "A-ZÁÉÍÓÚÑÜ"
_MIN = "a-záéíóúñü"
_PALABRA = rf"[{_MAY}][{_MIN}]+"
_NOMBRE = rf"{_PALABRA}(?:\s+(?:de\s+|del\s+|de\s+la\s+)?{_PALABRA}){{1,3}}"

_PATRONES_NOMBRE = [
    re.compile(rf"({_NOMBRE}),?\s+de\s+\d{{1,3}}\s+años"),                      # Juan Pérez, de 34 años
    re.compile(rf"({_NOMBRE})\s*\(\d{{1,3}}\)"),                                   # Juan Pérez (34)
    re.compile(rf"(?:identificad[oa]s?\s+como|llamad[oa]s?|de\s+nombre|se\s+trata\s+de|respond[ií]a\s+al\s+nombre\s+de)\s+({_NOMBRE})"),
]
# Palabras con mayúscula que no son nombres de personas (lugares, vías, instituciones)
_NO_PERSONA = set("""Ruta Nacional Provincial Avenida Calle Autopista Autovía Río Villa San Santa Santo General Barrio
Policía Hospital Fiscalía Juzgado Bomberos Municipalidad Provincia Ciudad Argentina Buenos Aires Córdoba Rosario Mendoza
Tucumán Salta Jujuy Chaco Misiones Corrientes Neuquén Chubut Entre Ríos Formosa Catamarca Pampa Rioja Juan Luis Cruz Fe
Estero Fuego Tierra Negro Gobierno Ministerio Agencia Seguridad Vial Hospital Sanatorio Comisaría Unidad Regional
Departamento Partido Norte Sur Este Oeste Centro Puerto Parque Plaza Terminal Puente Paso Nivel Km Kilómetro""".split())


def nombres_en_texto(texto: str) -> set[str]:
    """Nombres de personas que el texto presenta con los patrones habituales de la prensa."""
    nombres = set()
    for patron in _PATRONES_NOMBRE:
        for m in patron.finditer(texto or ""):
            candidato = re.sub(r"\s+", " ", m.group(1)).strip()
            palabras = [p for p in candidato.split() if p.lower() not in ("de", "del", "la")]
            if len(palabras) >= 2 and not all(p in _NO_PERSONA for p in palabras):
                nombres.add(candidato)
    return nombres


_VERBOS = ("sufrió|tuvo|protagonizó|murió|falleció|chocó|volcó|resultó|fue|quedó|habló|contó|relató|denunció|"
           "perdió|salió|viajaba|manejaba|conducía|atropelló")
_PATRON_PROBABLE = re.compile(rf"(?:^|[.!?:]\s+|\n)\s*({_NOMBRE})\s+(?:{_VERBOS})\b")


def nombres_probables(texto: str) -> set[str]:
    """Nombres que abren una oración seguidos de un verbo ("Fulano Mengano sufrió un accidente...").

    Es un patrón más débil: también lo cumplen lugares con nombre de persona (Carlos Casares, Marcos Paz).
    Por eso solo se usa para proteger el resumen, no para borrar la localidad o la vía.
    """
    nombres = set()
    for m in _PATRON_PROBABLE.finditer(texto or ""):
        candidato = re.sub(r"\s+", " ", m.group(1)).strip()
        palabras = [p for p in candidato.split() if p.lower() not in ("de", "del", "la")]
        if len(palabras) >= 2 and not all(p in _NO_PERSONA for p in palabras):
            nombres.add(candidato)
    return nombres


def _contiene_nombre(valor: str, nombres: set[str]) -> bool:
    v = (valor or "").lower()
    for n in nombres:
        palabras = [p for p in n.split() if p.lower() not in ("de", "del", "la")]
        if n.lower() in v or (len(palabras) >= 2 and f"{palabras[0]} {palabras[-1]}".lower() in v):
            return True
    return False


_EDAD = re.compile(r",?\s*de\s+\d{1,3}\s+años(?:\s+de\s+edad)?|\s*\(\d{1,3}\)", re.I)


def quitar_edades(texto: str) -> str:
    return re.sub(r"\s{2,}", " ", _EDAD.sub("", texto or "")).strip()


_TIPOS = {"choque_frontal": "Choque frontal", "choque_por_alcance": "Choque por alcance", "choque_lateral": "Choque",
          "choque_sin_detalle": "Choque",
          "vuelco": "Vuelco", "atropello": "Atropello", "despiste": "Despiste", "caida": "Caída", "tren": "Siniestro con un tren",
          "multiple": "Choque múltiple", "otro": "Siniestro vial"}


def resumen_generico(f: dict) -> str:
    """Resumen armado solo con los campos de la ficha (cuando el del modelo no se puede usar)."""
    lugar = ", ".join(x for x in (f.get("via"), f.get("localidad"), f.get("provincia")) if x)
    victimas = []
    if f.get("fallecidos"):
        victimas.append(f"{f['fallecidos']} persona{'s' if f['fallecidos'] != 1 else ''} fallecida{'s' if f['fallecidos'] != 1 else ''}")
    heridos = sum(f.get(c) or 0 for c in ("heridos_graves", "heridos_leves", "heridos_sin_detalle"))
    if heridos:
        victimas.append(f"{heridos} persona{'s' if heridos != 1 else ''} herida{'s' if heridos != 1 else ''}")
    texto = _TIPOS.get(f.get("tipo_siniestro"), "Siniestro vial")
    if lugar:
        texto += f" en {lugar}"
    if victimas:
        texto += ": " + " y ".join(victimas)
    return texto + "."


_CAMPOS_TEXTO = ("localidad", "departamento", "via", "organismo", "dato_clave")

# Ocupaciones y vínculos: junto con fecha y lugar pueden identificar a alguien. La consigna los prohíbe; si
# igual aparecen, la ficha queda marcada para revisión (no se reemplaza: "un padre y su hijo" a veces es el
# único modo de contar el hecho, y la decisión es del equipo).
_DATO_SENSIBLE = re.compile(
    r"\b(polic[ií]as?|gendarmes?|militar(es)?|docentes?|maestr[oa]s?|enfermer[oa]s?|"
    r"chofer de (uber|aplicaci[oó]n|app)|hij[oa]s?|padre|madre|herman[oa]s?|espos[oa]|pareja|novi[oa]|abuel[oa])\b",
    re.I,
)


def limpiar_ficha(f: dict, nombres: set[str], probables: set[str] = frozenset()) -> dict:
    """Saca edades del resumen y verifica que ningún nombre de persona se haya colado en la ficha.

    `nombres`: detectados con patrones fuertes (se buscan en todos los campos de texto).
    `probables`: detectados con el patrón débil (solo se buscan en el resumen).
    """
    f["privacidad"] = []
    resumen = quitar_edades(f.get("resumen", ""))
    if resumen != f.get("resumen"):
        f["privacidad"].append("edad quitada del resumen")
    if _contiene_nombre(resumen, set(nombres) | set(probables)):
        resumen = resumen_generico(f) if "tipo_siniestro" in f else "Novedad de contexto vial."
        f["privacidad"].append("resumen reemplazado: tenía un nombre")
    f["resumen"] = resumen
    if _DATO_SENSIBLE.search(resumen):
        f["privacidad"].append("revisar: el resumen menciona una ocupación o un vínculo")
    for campo in _CAMPOS_TEXTO:
        if f.get(campo) and _contiene_nombre(f[campo], nombres):
            f[campo] = None
            f["privacidad"].append(f"{campo} borrado: tenía un nombre")
    return f
