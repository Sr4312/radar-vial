"""Arma (o amplía) el catálogo de medios: descubre feeds RSS y sitemaps de noticias de cada dominio.

Uso:
  python scripts/descubrir_fuentes.py                 # recorre CANDIDATOS y escribe config/fuentes.yaml
  python scripts/descubrir_fuentes.py medio.com.ar    # solo muestra qué encontró para esos dominios

Lo que responde con notas queda `activo: true, verificar: false`. Lo que no se pudo confirmar queda
`activo: false, verificar: true` para revisarlo a mano (puede que el medio no tenga feed o bloquee lectores).
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar_vial import config  # noqa: E402
from radar_vial.dominios import descubrir, leer_feed_entradas, leer_sitemap  # noqa: E402
from radar_vial.red import Red  # noqa: E402
from radar_vial.texto import log  # noqa: E402

# (dominio, nombre, provincia id o None para nacionales, nivel)
CANDIDATOS = [
    # Nacionales
    ("infobae.com", "Infobae", None, "nacional"),
    ("lanacion.com.ar", "La Nación", None, "nacional"),
    ("clarin.com", "Clarín", None, "nacional"),
    ("pagina12.com.ar", "Página/12", None, "nacional"),
    ("perfil.com", "Perfil", None, "nacional"),
    ("tn.com.ar", "TN", None, "nacional"),
    ("noticiasargentinas.com", "Noticias Argentinas (agencia)", None, "nacional"),
    ("telam.com.ar", "Télam (cerrada como agencia de noticias)", None, "nacional"),
    ("ambito.com", "Ámbito", None, "nacional"),
    ("minutouno.com", "MinutoUno", None, "nacional"),
    ("cronica.com.ar", "Crónica", None, "nacional"),
    # CABA (la cubren sobre todo los nacionales)
    ("buenosaires.gob.ar", "Gobierno de la Ciudad (noticias)", "02", "oficial"),
    # Buenos Aires
    ("eldia.com", "El Día (La Plata)", "06", "provincial"),
    ("lacapitalmdp.com", "La Capital (Mar del Plata)", "06", "provincial"),
    ("lanueva.com", "La Nueva (Bahía Blanca)", "06", "provincial"),
    ("0223.com.ar", "0223 (Mar del Plata)", "06", "local"),
    ("infocielo.com", "Infocielo", "06", "provincial"),
    # Catamarca
    ("elancasti.com.ar", "El Ancasti", "10", "provincial"),
    ("elesquiu.com", "El Esquiú", "10", "provincial"),
    ("catamarcaactual.com.ar", "Catamarca Actual", "10", "provincial"),
    # Córdoba
    ("lavoz.com.ar", "La Voz del Interior", "14", "provincial"),
    ("cadena3.com", "Cadena 3", "14", "provincial"),
    ("eldoce.tv", "El Doce", "14", "provincial"),
    ("cba24n.com.ar", "Cba24n", "14", "provincial"),
    ("puntal.com.ar", "Puntal (Río Cuarto)", "14", "local"),
    # Corrientes
    ("ellitoral.com.ar", "El Litoral (Corrientes)", "18", "provincial"),
    ("diarioepoca.com", "Época", "18", "provincial"),
    ("radiosudamericana.com", "Radio Sudamericana", "18", "provincial"),
    # Chaco
    ("diarionorte.com", "Norte", "22", "provincial"),
    ("chacodiapordia.com", "Chaco Día por Día", "22", "provincial"),
    ("datachaco.com", "Data Chaco", "22", "provincial"),
    # Chubut
    ("elchubut.com.ar", "El Chubut", "26", "provincial"),
    ("diariojornada.com.ar", "Jornada", "26", "provincial"),
    ("adnsur.com.ar", "ADNSUR", "26", "provincial"),
    # Entre Ríos
    ("unoentrerios.com.ar", "Uno Entre Ríos", "30", "provincial"),
    ("elonce.com", "Elonce", "30", "provincial"),
    ("analisisdigital.com.ar", "Análisis Digital", "30", "provincial"),
    # Formosa
    ("lamananaonline.com.ar", "La Mañana (Formosa)", "34", "provincial"),
    ("elcomercial.com.ar", "El Comercial", "34", "provincial"),
    ("expresoformosa.com", "Expreso Formosa", "34", "provincial"),
    ("agenfor.com.ar", "Agenfor (agencia de noticias de Formosa)", "34", "oficial"),
    # Jujuy
    ("todojujuy.com", "Todo Jujuy", "38", "provincial"),
    ("jujuyalmomento.com", "Jujuy al Momento", "38", "provincial"),
    ("eltribuno.com", "El Tribuno (Salta y Jujuy)", "66", "provincial"),
    # La Pampa
    ("laarena.com.ar", "La Arena", "42", "provincial"),
    ("eldiariodelapampa.com.ar", "El Diario de La Pampa", "42", "provincial"),
    # La Rioja
    ("nuevarioja.com.ar", "Nueva Rioja", "46", "provincial"),
    ("riojavirtual.com.ar", "Rioja Virtual", "46", "provincial"),
    ("elindependiente.com.ar", "El Independiente", "46", "provincial"),
    # Mendoza
    ("losandes.com.ar", "Los Andes", "50", "provincial"),
    ("mdzol.com", "MDZ", "50", "provincial"),
    ("elsol.com.ar", "El Sol", "50", "provincial"),
    ("diariouno.com.ar", "Diario Uno", "50", "provincial"),
    # Misiones
    ("elterritorio.com.ar", "El Territorio", "54", "provincial"),
    ("misionesonline.net", "Misiones Online", "54", "provincial"),
    ("primeraedicion.com.ar", "Primera Edición", "54", "provincial"),
    # Neuquén
    ("lmneuquen.com", "LM Neuquén", "58", "provincial"),
    ("neuquenhoy.com.ar", "Neuquén Hoy", "58", "provincial"),
    # Río Negro
    ("rionegro.com.ar", "Río Negro", "62", "provincial"),
    ("elcordillerano.com.ar", "El Cordillerano (Bariloche)", "62", "local"),
    ("anbariloche.com.ar", "ANB (Bariloche)", "62", "local"),
    # Salta
    ("quepasasalta.com.ar", "Qué Pasa Salta", "66", "provincial"),
    ("informatesalta.com.ar", "Informate Salta", "66", "provincial"),
    # San Juan
    ("diariodecuyo.com.ar", "Diario de Cuyo", "70", "provincial"),
    ("tiempodesanjuan.com", "Tiempo de San Juan", "70", "provincial"),
    ("diariohuarpe.com", "Diario Huarpe", "70", "provincial"),
    # San Luis
    ("eldiariodelarepublica.com", "El Diario de la República", "74", "provincial"),
    ("elchorrillero.com", "El Chorrillero", "74", "provincial"),
    ("agenciasanluis.com", "Agencia de Noticias San Luis", "74", "oficial"),
    # Santa Cruz
    ("laopinionaustral.com.ar", "La Opinión Austral", "78", "provincial"),
    ("tiemposur.com.ar", "TiempoSur", "78", "provincial"),
    ("nuevodiaweb.com.ar", "Nuevo Día (Santa Cruz)", "78", "provincial"),
    # Santa Fe
    ("lacapital.com.ar", "La Capital (Rosario)", "82", "provincial"),
    ("ellitoral.com", "El Litoral (Santa Fe)", "82", "provincial"),
    ("rosario3.com", "Rosario3", "82", "provincial"),
    ("airedesantafe.com.ar", "Aire de Santa Fe", "82", "provincial"),
    # Santiago del Estero
    ("elliberal.com.ar", "El Liberal", "86", "provincial"),
    ("nuevodiarioweb.com.ar", "Nuevo Diario (Santiago del Estero)", "86", "provincial"),
    ("diariopanorama.com", "Diario Panorama", "86", "provincial"),
    # Tucumán
    ("lagaceta.com.ar", "La Gaceta", "90", "provincial"),
    ("eltucumano.com", "El Tucumano", "90", "provincial"),
    ("contextotucuman.com", "Contexto Tucumán", "90", "provincial"),
    ("tucumanalas7.com.ar", "Tucumán a las 7", "90", "provincial"),
    # Tierra del Fuego
    ("sur54.com", "Sur54", "94", "provincial"),
    ("eldiariodelfindelmundo.com", "El Diario del Fin del Mundo", "94", "provincial"),
    ("infofueguina.com", "Infofueguina", "94", "provincial"),
    ("tiempofueguino.com", "Tiempo Fueguino", "94", "provincial"),
    ("actualidadtdf.com.ar", "Actualidad TDF", "94", "provincial"),
]

# Feeds de sección (más notas de sociedad y policiales que el feed general), verificados a mano.
FEEDS_SECCION = {
    "clarin.com": ["https://www.clarin.com/rss/policiales/", "https://www.clarin.com/rss/sociedad/"],
    "infobae.com": ["https://www.infobae.com/arc/outboundfeeds/rss/category/sociedad/"],
    "lanacion.com.ar": ["https://www.lanacion.com.ar/arc/outboundfeeds/rss/category/sociedad/?outputType=xml"],
    "tn.com.ar": ["https://tn.com.ar/arc/outboundfeeds/rss/category/policiales/?outputType=xml",
                  "https://tn.com.ar/arc/outboundfeeds/rss/category/sociedad/?outputType=xml"],
}

# Fuentes oficiales y ONG: referencia para comparar órdenes de magnitud. No se cuentan como siniestros.
OFICIALES = [
    ("argentina.gob.ar/seguridadvial", "Agencia Nacional de Seguridad Vial (ANSV)", None),
    ("luchemosporlavida.org.ar", "Luchemos por la Vida", None),
    ("gba.gob.ar/seguridadvial", "Provincia de Buenos Aires · Seguridad Vial", "06"),
    ("santafe.gob.ar/seguridadvial", "Santa Fe · Agencia Provincial de Seguridad Vial", "82"),
    ("buenosaires.gob.ar/movilidad", "Ciudad de Buenos Aires · Movilidad y Seguridad Vial", "02"),
]


def _q(texto: str) -> str:
    return '"' + texto.replace('"', '\\"') + '"'


def revisar(red: Red, cand):
    """Devuelve (candidato, info, feeds que respondieron con notas, notas en el sitemap)."""
    dominio, nombre, prov, nivel = cand
    info = descubrir(red, dominio)
    feeds_ok = []
    for url in FEEDS_SECCION.get(dominio) or info.feeds[:1]:
        try:
            if leer_feed_entradas(red, url):
                feeds_ok.append(url)
        except Exception:  # noqa: BLE001
            continue
    notas_sitemap = 0
    if info.sitemaps_noticias:
        try:
            notas_sitemap = len(leer_sitemap(red, info.sitemaps_noticias[0], max_hijos=1))
        except Exception:  # noqa: BLE001
            notas_sitemap = 0
    return cand, info, feeds_ok, notas_sitemap


def revisar_oficial(red: Red, of):
    ruta, nombre, prov = of
    try:
        r = red.get("https://www." + ruta)
        return of, r.status_code, r.url
    except Exception as exc:  # noqa: BLE001
        return of, None, f"{type(exc).__name__}"


def escribir_yaml(resultados, oficiales, ruta: Path) -> None:
    lineas = [
        "# Catálogo de medios del Radar Vial (se edita acá, sin tocar código).",
        "# Generado por scripts/descubrir_fuentes.py el " + __import__("datetime").date.today().isoformat() + " y revisable a mano.",
        "#",
        "# - sitio: dominio del medio (sirve también para reconocerlo cuando llega por Google News)",
        "# - feeds: RSS que se leen directo en cada corrida",
        "# - sitemap: sitemap de noticias del medio. Si el medio no tiene feed, se lee el sitemap en su lugar;",
        "#   además lo usa el resolvedor para encontrar la URL original de los links de Google News",
        "# - provincia: id de config/provincias.yaml (vacío = nacional)",
        "# - nivel: nacional, provincial, local u oficial",
        "# - activo: si se lee en cada corrida (por feed o, si no tiene, por sitemap)",
        "# - verificar: true = no se pudo confirmar que el feed o el sitemap respondan con notas; revisarlo a mano",
        "#   (el medio igual puede llegar por Google News)",
        "",
        "medios:",
    ]
    for cand, info, feeds_ok, notas_sitemap in resultados:
        dominio, nombre, prov, nivel = cand
        sitemap = info.sitemaps_noticias[0] if info.sitemaps_noticias and notas_sitemap else ""
        ok = bool(feeds_ok) or bool(sitemap)
        lineas += [
            f"  - nombre: {_q(nombre)}",
            f"    sitio: {dominio}",
            "    feeds: [" + ", ".join(_q(f) for f in feeds_ok) + "]",
            f"    sitemap: {_q(sitemap) if sitemap else 'null'}",
            f"    provincia: {_q(prov) if prov else 'null'}",
            f"    nivel: {nivel}",
            f"    activo: {'true' if ok else 'false'}",
            f"    verificar: {'false' if ok else 'true'}",
        ]
        if not ok:
            motivo = info.error or "sin feed ni sitemap de noticias que respondan a lectores automáticos"
            lineas.append(f"    # {motivo[:150]}")
    lineas += [
        "",
        "# Referencias oficiales y ONG: para comparar órdenes de magnitud en el dashboard.",
        "# No se recolectan como notas ni se suman a los conteos.",
        "oficiales:",
    ]
    for of, estado, final in oficiales:
        ruta_, nombre, prov = of
        ok = estado == 200
        lineas += [
            f"  - nombre: {_q(nombre)}",
            f"    url: {_q(final if ok else 'https://www.' + ruta_)}",
            f"    provincia: {_q(prov) if prov else 'null'}",
            f"    verificar: {'false' if ok else 'true'}",
        ]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main(argv: list[str]) -> None:
    red = Red(timeout=20, reintentos=1, pausa=0.5)
    if argv:
        for dominio in argv:
            info = descubrir(red, dominio)
            log(dominio, "| feeds:", info.feeds, "| sitemaps:", info.sitemaps_noticias, "| error:", info.error)
        return
    with ThreadPoolExecutor(max_workers=10) as ex:
        resultados = list(ex.map(lambda c: revisar(red, c), CANDIDATOS))
        oficiales = list(ex.map(lambda o: revisar_oficial(red, o), OFICIALES))
    for cand, info, feeds_ok, notas_sitemap in resultados:
        log(f"{cand[0]:28} feeds_ok={len(feeds_ok)} sitemap={notas_sitemap:4} {(info.error or '')[:80]}")
    for of, estado, final in oficiales:
        log(f"OFICIAL {of[0]:32} {estado} {final}")
    escribir_yaml(resultados, oficiales, config.DIR_CONFIG / "fuentes.yaml")
    log("Escrito config/fuentes.yaml")


if __name__ == "__main__":
    main(sys.argv[1:])
