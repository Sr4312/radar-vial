"""Modo demo: el tablero con datos de ejemplo, sin API ni red.

Genera unos 40 días de siniestros FICTICIOS (las localidades y sus coordenadas son reales; los hechos no),
los escribe en salida/demo/ junto con una copia del tablero y lo sirve en http://localhost:8000.
El tablero muestra un aviso fijo de "datos de ejemplo". Los enlaces van a example.org (dominio reservado).
"""
from __future__ import annotations

import functools
import http.server
import random
from datetime import datetime, timedelta, timezone

from . import config
from .agregados import copiar_sitio, generar

ART = timezone(timedelta(hours=-3))

# (localidad, provincia, lat, lon): lugares reales, tomados de Georef
LUGARES = [
    ("Parque Patricios", "02", -34.637, -58.405), ("Quilmes", "06", -34.719, -58.260), ("Morón", "06", -34.651, -58.622),
    ("Olavarría", "06", -36.894, -60.323), ("Dolores", "06", -36.315, -57.675), ("Chacabuco", "06", -34.642, -60.471),
    ("San Fernando del Valle de Catamarca", "10", -28.469, -65.779), ("Córdoba", "14", -31.417, -64.184),
    ("Villa María", "14", -32.413, -63.248), ("Río Cuarto", "14", -33.124, -64.349), ("Canals", "14", -33.562, -62.885),
    ("Corrientes", "18", -27.463, -58.839), ("Monte Caseros", "18", -30.249, -57.629), ("Resistencia", "22", -27.451, -58.986),
    ("Comodoro Rivadavia", "26", -45.865, -67.482), ("Puerto Madryn", "26", -42.767, -65.037), ("Paraná", "30", -31.740, -60.527),
    ("Concordia", "30", -31.392, -58.017), ("Tatané", "34", -26.398, -58.357), ("Palpalá", "38", -24.258, -65.213),
    ("San Salvador de Jujuy", "38", -24.186, -65.299), ("General Pico", "42", -35.659, -63.758), ("Chilecito", "46", -29.165, -67.495),
    ("San Rafael", "50", -34.613, -68.330), ("Las Heras", "50", -32.850, -68.841), ("Guaymallén", "50", -32.900, -68.788),
    ("Oberá", "54", -27.487, -55.120), ("Posadas", "54", -27.366, -55.894), ("Neuquén", "58", -38.952, -68.059),
    ("Plottier", "58", -38.952, -68.227), ("Cipolletti", "62", -38.939, -67.996), ("General Güemes", "66", -24.674, -65.047),
]
TIPOS = ["choque_frontal", "choque_lateral", "choque_por_alcance", "choque_sin_detalle", "vuelco", "atropello", "despiste", "caida"]
VEHICULOS = [["auto", "moto"], ["auto"], ["moto"], ["camion", "auto"], ["utilitario", "moto"], ["auto", "peaton"],
             ["colectivo", "auto"], ["moto", "bicicleta"], ["camion"]]
FACTORES = ["alcohol", "velocidad", "clima", "estado_de_la_ruta", "celular", "sobrepaso"]
FRANJAS = ["madrugada", "manana", "tarde", "noche", "desconocida"]


def eventos_de_ejemplo(hoy, dias: int = 40, semilla: int = 2026) -> list[dict]:
    rnd = random.Random(semilla)
    eventos = []
    for d in range(dias, -1, -1):
        dia = (hoy - timedelta(days=d)).isoformat()
        for i in range(rnd.randint(3, 12) if d > 1 else rnd.randint(1, 5)):
            loc, prov, lat, lon = rnd.choice(LUGARES)
            ruta = rnd.random() < 0.45
            num = rnd.choice([3, 5, 7, 8, 9, 14, 22, 33, 34, 40, 2, 6, 11])
            tipo = rnd.choice(TIPOS)
            fallecidos = rnd.choices([0, 1, 2], weights=[78, 18, 4])[0]
            heridos = rnd.choices([0, 1, 2, 3], weights=[20, 45, 25, 10])[0]
            n_fuentes = rnd.choices([1, 2, 3, 5], weights=[55, 25, 12, 8])[0]
            solo = rnd.random() < 0.15
            eventos.append({
                "id_evento": f"ev_demo_{dia.replace('-', '')}_{i}", "fecha_hecho": dia, "fecha_aproximada": rnd.random() < 0.1,
                "hora_franja": rnd.choice(FRANJAS), "provincia_id": prov, "localidad": loc, "departamento": None,
                "lat": lat, "lon": lon, "nivel_geo": "localidad", "provincia_inferida": False,
                "via": f"{'RN' if num < 30 else 'RP'} {num}" if ruta else "Av. de ejemplo y calle de ejemplo",
                "tipo_via": ("ruta_nacional" if num < 30 else "ruta_provincial") if ruta else "urbana",
                "tipo_siniestro": tipo, "vehiculos": rnd.choice(VEHICULOS), "fallecidos": fallecidos,
                "heridos_graves": None, "heridos_leves": None, "heridos_sin_detalle": heridos, "heridos_total": heridos,
                "factores_mencionados": [{"factor": f, "presunto": rnd.random() < 0.7} for f in rnd.sample(FACTORES, rnd.choice([0, 0, 1, 1, 2]))],
                "grupos_etarios": rnd.sample(["joven", "adulto", "persona_mayor"], rnd.choice([0, 1, 1, 2])),
                "resumen": f"Ejemplo: siniestro ficticio en {loc} para probar el tablero.", "confianza": "media",
                "solo_titulos": solo,
                "fuentes": [{"medio": f"Medio de ejemplo {k + 1}", "url": f"https://example.org/nota-{dia}-{i}-{k}",
                             "publicada": dia, "texto": "titulo" if solo else "completo"} for k in range(n_fuentes)],
                "fichas": [], "n_fuentes": n_fuentes,
            })
    return eventos


def contexto_de_ejemplo(hoy) -> list[dict]:
    items = [("control_alcoholemia", "14", "Ejemplo: operativo de control de alcoholemia en rutas de la provincia."),
             ("normativa", None, "Ejemplo: novedad normativa sobre licencias de conducir."),
             ("campana", "50", "Ejemplo: campaña de seguridad vial en escuelas secundarias."),
             ("infraestructura_rutas", "54", "Ejemplo: obras de repavimentación en una ruta nacional.")]
    notas = []
    for i, (sub, prov, res) in enumerate(items):
        dia = (hoy - timedelta(days=i * 2 + 1)).isoformat()
        notas.append({"id_nota": f"demo_ctx_{i}", "categoria": "contexto", "medio": "Medio de ejemplo",
                      "url": f"https://example.org/contexto-{i}", "publicada": f"{dia}T12:00:00+00:00",
                      "contexto": {"subtipo": sub, "ambito": "provincial" if prov else "nacional", "provincia_id": prov,
                                   "fecha": dia, "organismo": "Organismo de ejemplo", "dato_clave": None, "resumen": res}})
    return notas


def correr_demo(servir: bool = True, puerto: int = 8000, log=print) -> None:
    ahora = datetime.now(ART)
    sitio = config.DIR_SALIDA / "demo"
    copiar_sitio(sitio)
    eventos = eventos_de_ejemplo(ahora.date())
    generar(sitio / "data", ahora=ahora, eventos=eventos, notas=contexto_de_ejemplo(ahora.date()), demo=True,
            inicio_cobertura=ahora.date() - timedelta(days=40))
    log(f"Tablero de ejemplo armado en {sitio.relative_to(config.RAIZ)} ({len(eventos)} siniestros ficticios).")
    if not servir:
        return
    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(sitio))
    with http.server.ThreadingHTTPServer(("127.0.0.1", puerto), manejador) as servidor:
        log(f"Abrí http://localhost:{puerto} en el navegador. Para cortar, Ctrl+C.")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            log("Listo.")
