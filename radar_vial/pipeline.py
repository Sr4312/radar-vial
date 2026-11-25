"""Corrida diaria: recolectar, filtrar, resolver y bajar, extraer y guardar.

  recolectar -> historial (lo ya visto no se repite) -> filtro con Haiku (título y bajada)
  -> URL original y texto, solo de las relevantes -> deduplicar por URL canónica -> extracción con Sonnet
  -> data/notas.jsonl, data/historial.jsonl, data/costos.jsonl

Las etapas de eventos y dashboard se suman después de la extracción (eventos.py, agregados.py).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import config
from .claude import Claude, ErrorClaude, RegistroCostos
from .extraer import extraer_nota
from .filtrar import filtrar
from .historial import Historial
from .notas import Notas
from .recolectar import fusionar, recolectar
from .red import Red
from .resolver import Resolvedor, Robots, bajar_nota, cargar_texto, guardar_texto, podar_textos
from .texto import log as log_consola


def _ficha_nota(it: dict, extraccion: dict, fuente_texto: str, modelo: str) -> dict:
    return {
        "id_nota": it["id"],
        "url": it.get("url_resuelta") or it["url"],
        "url_google_news": it["url"] if it.get("gn_id") else None,
        "clave": it.get("clave"),
        "medio": it.get("medio"),
        "sitio": it.get("sitio"),
        "provincia_medio": it.get("provincia_medio"),
        "nivel_medio": it.get("nivel_medio"),
        # provincias de las búsquedas de Google News por las que llegó (pista si la nota no dice la provincia)
        "provincias_busqueda": sorted({o["provincia"] for o in it.get("origenes") or []
                                       if o.get("provincia") and o.get("tipo") == "google_news"}),
        "publicada": it["publicada"],
        "categoria": extraccion["categoria"],
        "fuente_texto": fuente_texto,          # completo | titulo
        "texto_recortado": extraccion.get("texto_recortado", False),
        "siniestros": extraccion["siniestros"],
        "contexto": extraccion["contexto"],
        "modelo": modelo,
        "procesada": datetime.now(timezone.utc).isoformat(),
    }


def _datos_cache(it: dict, texto: str | None) -> dict:
    """Lo que se guarda en la caché temporal para poder reprocesar sin volver a bajar."""
    campos = ("id", "titulo", "bajada", "url", "url_resuelta", "gn_id", "clave", "medio", "sitio",
              "provincia_medio", "nivel_medio", "publicada", "origenes")
    return {**{c: it.get(c) for c in campos}, "texto": texto or ""}


_COLA = "_pendientes"


def elegir_para_extraer(relevantes: list[dict], tope: int, cupo_contexto: int) -> tuple[list[dict], list[dict]]:
    """(a extraer, postergadas). `relevantes` viene ordenada (siniestros primero, lo más nuevo antes).

    El contexto tiene un cupo propio dentro del tope: si no, en días con muchos siniestros nunca entraría.
    Si sobra lugar, lo ocupan las que hayan quedado afuera, en el mismo orden.
    """
    siniestros = [it for it in relevantes if it["filtro"] == "siniestro"]
    contexto = [it for it in relevantes if it["filtro"] != "siniestro"]
    # el cupo nunca pasa de un tercio del tope: con un tope chico (pruebas) no desplaza a los siniestros
    cupo = min(len(contexto), cupo_contexto, tope // 3)
    elegidas = siniestros[:tope - cupo] + contexto[:cupo]
    ids = {it["id"] for it in elegidas}
    for it in relevantes:
        if len(elegidas) >= tope:
            break
        if it["id"] not in ids:
            elegidas.append(it)
            ids.add(it["id"])
    return elegidas, [it for it in relevantes if it["id"] not in ids]


class _TitulosEnCache:
    """Títulos originales de las notas, leídos de la caché temporal solo cuando el desempate los necesita."""

    def get(self, id_nota: str, defecto=None):
        datos = cargar_texto(id_nota)
        return (datos or {}).get("titulo") or defecto


def geo_y_eventos(notas: Notas, claude: Claude | None, log=log_consola) -> list[dict]:
    """Normaliza la geografía de las fichas nuevas y rehace los eventos (conservando ids)."""
    from .eventos import armar_eventos
    from .geo import Georef, completar_notas

    georef = Georef()
    hechas = completar_notas(notas, georef)
    georef.guardar()
    notas.guardar()
    if hechas:
        log(f"Georef: {hechas} fichas normalizadas ({georef.consultas} consultas nuevas a la API).")
    return armar_eventos(notas, claude, titulos=_TitulosEnCache(), log=log)


def guardar_pendientes(items: list[dict]) -> None:
    """Cola de notas relevantes que no entraron en el tope (en la caché temporal: tienen títulos)."""
    campos = ("id", "titulo", "bajada", "url", "gn_id", "clave", "hash_titulo", "medio", "sitio", "provincia_medio",
              "nivel_medio", "publicada", "tipo_busqueda", "origenes", "filtro", "argentina")
    guardar_texto(_COLA, {"items": [{c: it.get(c) for c in campos} for it in items]})


DIAS_EN_COLA = 7


def cargar_pendientes(log=None) -> list[dict]:
    """La cola, sin lo que lleva más de DIAS_EN_COLA días (no crece sin fin). Si no se puede leer, vacía.

    Con `log`, avisa cuántas vencieron sin procesarse: si pasa seguido, el tope no alcanza para el volumen."""
    try:
        datos = cargar_texto(_COLA)
    except Exception:  # noqa: BLE001 - un archivo de cola dañado no debe frenar todas las corridas
        return []
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_EN_COLA)
    items = (datos or {}).get("items", [])
    vigentes = [p for p in items if datetime.fromisoformat(p["publicada"]) >= limite]
    vencidas = [p for p in items if datetime.fromisoformat(p["publicada"]) < limite]
    if vencidas and log:
        siniestros = sum(1 for p in vencidas if p.get("filtro") == "siniestro")
        log(f"Cola: {len(vencidas)} notas vencieron sin procesarse tras {DIAS_EN_COLA} días "
            f"({siniestros} de siniestros).")
    return vigentes


def resolver_y_bajar(red: Red, resolvedor: Resolvedor, robots: Robots, it: dict) -> None:
    """Completa en el item: url_resuelta, metodo_resolucion, clave, texto, error_descarga."""
    url, metodo = resolvedor.resolver_con_metodo(it)
    it["metodo_resolucion"] = metodo
    it["texto"] = None
    if not url:
        it["error_descarga"] = "sin URL original"
        return
    nota = bajar_nota(red, robots, url)
    it["url_resuelta"] = nota["url_final"]
    it["clave"] = nota["clave"]  # clave de la URL canónica (rel=canonical de la página)
    it["error_descarga"] = nota["error"]
    if not nota["error"]:
        it["texto"] = nota["texto"]


def correr_diario(publicar: bool = True, log=log_consola, tope: int | None = None) -> dict:
    """`tope`: notas que pasan a la extracción en esta corrida (por defecto, el de config.yaml)."""
    conf = config.general()
    inicio = datetime.now(timezone.utc)
    registro = RegistroCostos("diario" + ("" if publicar else " --sin-publicar"))
    claude = Claude(registro)
    red = Red()
    historial = Historial()
    notas = Notas()
    podados = historial.podar()
    borrados = podar_textos()
    if podados or borrados:
        log(f"Historial: {podados} registros viejos podados; caché de textos: {borrados} textos vencidos borrados.")

    # 1. Recolectar (más las que quedaron en la cola por el tope de la corrida anterior)
    items, resultados = recolectar(red, log=log)
    pendientes = cargar_pendientes(log=log)
    if pendientes:
        recolectadas = {it["id"] for it in items}
        fuera = sum(1 for p in pendientes if p["id"] not in recolectadas)
        log(f"Cola de la corrida anterior: {len(pendientes)} notas ({fuera} ya fuera de la ventana de 48 h).")
        # la misma nota puede volver con otro id de Google News: se une a su copia de la cola, que conserva
        # lo que ya decidió el filtro
        items = fusionar(items + pendientes)
    # Una nota ya vista conserva su id: Google News la entrega con distintos ids de artículo y, si cambiara,
    # su ficha anterior quedaría suelta y se contaría dos veces.
    previos, unicos = {}, []
    for it in items:
        previo = historial.buscar(it)
        if previo is not None and previo.get("id_nota"):
            it["id"] = previo["id_nota"]
        if it["id"] in previos:
            continue
        previos[it["id"]] = previo
        unicos.append(it)
    items = unicos
    nuevos = [it for it in items if not historial.ya_procesada(it)]
    log(f"Nuevas o pendientes: {len(nuevos)} (ya procesadas antes: {len(items) - len(nuevos)}).")

    # 2. Filtro barato (las que ya pasaron el filtro en una corrida anterior no se vuelven a filtrar)
    for it in nuevos:
        previo = previos.get(it["id"])
        if not it.get("filtro") and previo and previo.get("estado") in ("solo_titulo", "pendiente", "sin_resolver"):
            it["filtro"] = previo.get("filtro", "siniestro")
    a_filtrar = [it for it in nuevos if not it.get("filtro")]
    if a_filtrar:
        filtrar(claude, a_filtrar, log=log)
    for it in nuevos:
        if it.get("filtro") == "descartar":
            historial.registrar(it, "descartada")
    relevantes = [it for it in nuevos if it.get("filtro") in ("siniestro", "contexto")]

    # 3. Tope de la etapa cara: primero siniestros, después lo más nuevo. El resto queda en la cola de
    #    pendientes (caché temporal) para la próxima corrida, aunque ya haya salido de la ventana de 48 h.
    relevantes.sort(key=lambda it: (it["filtro"] != "siniestro", -datetime.fromisoformat(it["publicada"]).timestamp()))
    tope = tope if tope is not None else conf["limites"]["max_extraccion_por_corrida"]
    # Las que ya tienen ficha de solo título se reintentan fuera del tope: solo vuelven a la extracción si esta vez
    # se consigue el texto. Dentro del tope dejaban afuera notas nuevas cuando dos corridas caían cerca (el
    # 25-11-2026, 146 de los 400 lugares se fueron en reintentos que siguieron sin texto).
    reintentos = [it for it in relevantes if (previos.get(it["id"]) or {}).get("estado") == "solo_titulo"]
    ids_reintento = {it["id"] for it in reintentos}
    a_procesar, postergadas = elegir_para_extraer([it for it in relevantes if it["id"] not in ids_reintento], tope,
                                                  conf["limites"].get("cupo_contexto", 50))
    a_procesar += reintentos
    # Hasta que termine la corrida, la cola incluye también lo que se va a procesar: si se corta, no se pierde.
    guardar_pendientes(postergadas + a_procesar)
    if reintentos:
        log(f"Reintentos de notas con ficha de solo título (fuera del tope): {len(reintentos)}.")
    if postergadas:
        siniestros = sum(1 for it in postergadas if it["filtro"] == "siniestro")
        log(f"Tope de extracción: {len(postergadas)} notas quedan en la cola para la próxima corrida "
            f"({siniestros} de siniestros).")

    # 4. URL original y texto (en paralelo: distintos medios)
    resolvedor, robots = Resolvedor(red), Robots(red)
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda it: resolver_y_bajar(red, resolvedor, robots, it), a_procesar))
    resolvedor.guardar()

    # 5. Deduplicar por URL canónica (la misma nota pudo llegar por dos vías que no se reconocieron antes)
    vistas: set[str] = set()
    para_extraer, duplicadas = [], []
    for it in a_procesar:
        previo = previos.get(it["id"])
        if it.get("clave"):
            otro = historial.buscar({"clave": it["clave"]})
            ya_contada = (otro is not None and otro is not previo and otro.get("id_nota") != it["id"]
                          and otro.get("estado") in ("siniestro", "contexto", "descartada"))
            if it["clave"] in vistas or ya_contada:
                # No se registra con `historial.registrar`: con la clave canónica encontraría el registro de la
                # nota original y lo pisaría (pasó: una nota de Bariloche se extrajo dos veces). Se anota al final.
                duplicadas.append((it, previo))
                # si en una corrida anterior se había hecho una ficha solo con el título, deja de contarse:
                # la misma nota ya está contada por la otra vía
                notas.por_id.pop(it["id"], None)
                continue
            vistas.add(it["clave"])
        # una nota que ya se extrajo solo con el título y sigue sin texto: no se vuelve a extraer
        if previo and previo.get("estado") == "solo_titulo" and not it.get("texto"):
            historial.registrar(it, "solo_titulo", id_nota=it["id"])
            continue
        para_extraer.append(it)

    # 6. Extracción (en paralelo, de a pocas llamadas)
    modelo = conf["modelos"]["extraccion"]

    def extraer(it):
        try:
            return it, extraer_nota(claude, it, it.get("texto")), None
        except ErrorClaude as exc:
            return it, None, str(exc)

    conteo = {"siniestro": 0, "contexto": 0, "descartar": 0, "error": 0, "solo_titulo": 0, "fichas_siniestro": 0}
    fallidas: list[dict] = []

    def guardar_avance(final: bool = False) -> None:
        """Fichas, historial y cola a disco. Se llama cada tanto y si la corrida se corta: lo ya extraído (y
        pagado) no se pierde, y lo que falta sigue en la cola."""
        for it in nuevos:  # lo que decidió el filtro, para no volver a filtrar
            r = historial.buscar(it)
            if r is not None and it.get("filtro") and it["filtro"] != "sin_evaluar":
                r["filtro"] = it["filtro"]
        notas.guardar()
        historial.guardar()
        if final:
            # vuelven a la cola: las postergadas, las que fallaron al extraer (hasta agotar sus intentos) y las
            # que el filtro no pudo evaluar (sin marca, para que se filtren de nuevo)
            cola = postergadas + [it for it in fallidas if not historial.ya_procesada(it)]
            cola += [{**it, "filtro": None} for it in nuevos if it.get("filtro") == "sin_evaluar"]
        else:
            cola = postergadas + [it for it in a_procesar if not historial.ya_procesada(it)]
        guardar_pendientes(cola)

    try:
        with ThreadPoolExecutor(max_workers=conf["limites"]["extracciones_en_paralelo"]) as ex:
            for hechas, (it, ext, error) in enumerate(ex.map(extraer, para_extraer), 1):
                if hechas % 25 == 0:
                    guardar_avance()
                if error:
                    conteo["error"] += 1
                    log(f"  ! extracción {it['sitio']}: {error}")
                    historial.registrar(it, "pendiente")
                    fallidas.append(it)
                    continue
                fuente = "completo" if it.get("texto") else "titulo"
                guardar_texto(it["id"], _datos_cache(it, it.get("texto")))
                conteo[ext["categoria"]] += 1
                if ext["categoria"] == "descartar":
                    historial.registrar(it, "descartada")
                    notas.por_id.pop(it["id"], None)  # si antes se había contado, deja de contarse
                    continue
                notas.guardar_nota(_ficha_nota(it, ext, fuente, modelo))
                conteo["fichas_siniestro"] += len(ext["siniestros"])
                if fuente == "titulo":
                    conteo["solo_titulo"] += 1
                    historial.registrar(it, "solo_titulo", id_nota=it["id"])  # se reintenta resolver
                else:
                    historial.registrar(it, ext["categoria"], id_nota=it["id"])
    except BaseException:
        guardar_avance()
        registro.guardar(extra={"notas": {"interrumpida": True, **conteo}})
        raise

    # Las duplicadas: su registro propio (si tenían una ficha de solo título) queda cerrado; si no, sus claves
    # pasan a ser alias de la nota original, que conserva su estado.
    for it, previo in duplicadas:
        original = historial.buscar({"clave": it["clave"]})
        if previo is not None and previo is not original:
            previo["estado"] = "duplicada"
            previo.pop("id_nota", None)
        elif original is not None:
            historial.agregar_alias(original, {"gn_id": it.get("gn_id"), "hash_titulo": it.get("hash_titulo")})

    guardar_avance(final=True)

    # 7. Geografía y eventos
    eventos = geo_y_eventos(notas, claude, log=log)

    # 8. Datos del tablero: docs/data/ (o salida/vista_previa/ con --sin-publicar)
    from .agregados import publicar as publicar_tablero

    publicar_tablero(publicar_en_docs=publicar, log=log)

    # Salud de la corrida: si falló más de la mitad de una etapa (API caída, sin crédito, Google News bloqueado),
    # la corrida no cuenta como hecha y el próximo intento del día la repite.
    problemas = []
    sin_evaluar = sum(1 for it in nuevos if it.get("filtro") == "sin_evaluar")
    errores_recoleccion = sum(1 for r in resultados if r.error)
    if resultados and errores_recoleccion * 2 > len(resultados):
        problemas.append(f"fallaron {errores_recoleccion} de {len(resultados)} búsquedas y feeds")
    if a_filtrar and sin_evaluar * 2 > len(a_filtrar):
        problemas.append(f"el filtro no pudo evaluar {sin_evaluar} de {len(a_filtrar)} notas")
    if para_extraer and conteo["error"] * 2 > len(para_extraer):
        problemas.append(f"falló la extracción de {conteo['error']} de {len(para_extraer)} notas")
    resumen = {
        "recolectadas": len(items), "nuevas": len(nuevos), "relevantes_filtro": len(relevantes),
        "extraidas": len(para_extraer), "postergadas": len(postergadas), "reintentos": len(reintentos),
        **conteo, "eventos": len(eventos),
        "sin_evaluar": sin_evaluar, "incompleta": "; ".join(problemas) or None,
        "duracion_min": round((datetime.now(timezone.utc) - inicio).total_seconds() / 60, 1),
    }
    costos = registro.guardar(extra={"notas": resumen})
    log(f"Extracción: {conteo['siniestro']} notas de siniestros ({conteo['fichas_siniestro']} fichas), "
        f"{conteo['contexto']} de contexto, {conteo['descartar']} descartadas al leerlas, {conteo['error']} con error; "
        f"{conteo['solo_titulo']} solo con el título.")
    log(f"Costo estimado de la corrida: USD {costos['costo_total_usd']:.2f} (detalle en data/costos.jsonl).")
    return resumen


def reprocesar(desde: str, log=log_consola, publicar: bool = True) -> dict:
    """Rehace la extracción de las notas publicadas desde `desde` usando la caché de textos (sin volver a bajar).

    Las notas cuyo texto ya venció en la caché (más de `dias_cache_textos`) conservan su ficha anterior.
    """
    conf = config.general()
    registro = RegistroCostos(f"reprocesar --desde {desde}")
    claude = Claude(registro)
    notas = Notas()
    historial = Historial()
    candidatas = [n for n in notas.todas() if n["publicada"][:10] >= desde]
    con_texto, sin_cache = [], 0
    for n in candidatas:
        datos = cargar_texto(n["id_nota"])
        if datos is None:
            sin_cache += 1
            continue
        con_texto.append((n, datos))
    log(f"Reprocesar desde {desde}: {len(candidatas)} notas; {len(con_texto)} con texto en caché, {sin_cache} sin caché (se conservan).")
    modelo = conf["modelos"]["extraccion"]

    def extraer(par):
        n, datos = par
        try:
            return n, datos, extraer_nota(claude, datos, datos.get("texto") or None), None
        except ErrorClaude as exc:
            return n, datos, None, str(exc)

    cambios = 0
    with ThreadPoolExecutor(max_workers=conf["limites"]["extracciones_en_paralelo"]) as ex:
        for n, datos, ext, error in ex.map(extraer, con_texto):
            if error:
                log(f"  ! {n['sitio']}: {error}")
                continue
            if ext["categoria"] == "descartar":
                notas.por_id.pop(n["id_nota"], None)
                historial.registrar(datos, "descartada")
            else:
                notas.guardar_nota(_ficha_nota(datos, ext, "completo" if datos.get("texto") else "titulo", modelo))
            cambios += 1
    notas.guardar()
    historial.guardar()
    eventos = geo_y_eventos(notas, claude, log=log)
    from .agregados import publicar as publicar_tablero

    publicar_tablero(publicar_en_docs=publicar, log=log)
    costos = registro.guardar(extra={"notas": {"reprocesadas": cambios, "sin_cache": sin_cache, "eventos": len(eventos)}})
    log(f"Reprocesadas {cambios}. Costo estimado: USD {costos['costo_total_usd']:.2f}.")
    return {"reprocesadas": cambios, "sin_cache": sin_cache}
