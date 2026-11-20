"""Comandos del Radar Vial.

  python -m radar_vial demo            dashboard con datos de ejemplo, sin API
  python -m radar_vial fuentes         prueba cada consulta y feed, informa cuáles responden
  python -m radar_vial diario          corrida real
  python -m radar_vial diario --sin-publicar
  python -m radar_vial reprocesar --desde AAAA-MM-DD
  python -m radar_vial auditoria --n 30
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from datetime import date

from . import config
from .texto import log


def cmd_fuentes(args) -> None:
    from .recolectar import armar_tareas, cargar_fuentes, recolectar
    from .red import Red
    from .resolver import Resolvedor, Robots, bajar_nota

    red = Red()
    tareas = armar_tareas(fuentes=cargar_fuentes())
    if args.solo == "google":
        tareas = [t for t in tareas if t.tipo == "google_news"]
    elif args.solo == "medios":
        tareas = [t for t in tareas if t.tipo != "google_news"]
    log(f"Probando {len(tareas)} búsquedas y feeds (ventana de {config.general()['recoleccion']['ventana_horas']} h)...")
    items, resultados = recolectar(red, tareas, log=log)

    # --- Detalle por fuente
    log("")
    log(f"{'FUENTE':58} {'ESTADO':8} {'TOTAL':>5} {'48H':>5} {'PASAN':>5}")
    for r in resultados:
        estado = "ERROR" if r.error else ("TOPE" if r.saturada else "ok")
        log(f"{r.tarea.nombre[:58]:58} {estado:8} {r.total:5} {r.en_ventana:5} {r.aceptadas:5}" + (f"  {r.error[:70]}" if r.error else ""))

    caidas = [r for r in resultados if r.error]
    saturadas = [r for r in resultados if r.saturada]
    log("")
    log(f"Responden {len(resultados) - len(caidas)} de {len(resultados)}; con error: {len(caidas)}; al tope de 100 resultados: {len(saturadas)}.")
    if saturadas:
        log("  Búsquedas al tope (conviene partir el grupo de términos): " + ", ".join(r.tarea.nombre for r in saturadas))

    # --- Aporte de cada término: notas que trajo y cuántas solo llegaron por ese término
    por_termino, exclusivas = Counter(), Counter()
    for it in items:
        terminos = {o["termino"] for o in it["origenes"] if o.get("termino")}
        otras_vias = any(o["tipo"] != "google_news" for o in it["origenes"])
        for t in terminos:
            por_termino[t] += 1
        if len(terminos) == 1 and not otras_vias:
            exclusivas[next(iter(terminos))] += 1
    if por_termino:
        log("")
        log("Aporte por término de búsqueda (notas que trajo / que solo llegaron por ese término):")
        for t, n in por_termino.most_common():
            log(f"  {t:40} {n:5} {exclusivas.get(t, 0):5}")

    # --- Cobertura por jurisdicción: notas que llegaron por búsquedas de esa provincia o por sus medios
    por_prov = Counter()
    for it in items:
        provs = {o.get("provincia") for o in it["origenes"] if o.get("provincia")} or {it.get("provincia_medio")}
        for p in provs:
            por_prov[p] += 1
    fuentes = cargar_fuentes()
    medios_activos = Counter(m.get("provincia") for m in fuentes.get("medios", []) if m.get("activo"))
    log("")
    log("Cobertura por jurisdicción (notas candidatas en la ventana / medios propios activos):")
    for p in config.provincias():
        log(f"  {p['corto']:22} {por_prov.get(p['id'], 0):5} notas   {medios_activos.get(p['id'], 0):2} medios")
    log(f"  {'Nacionales':22} {'':5}         {medios_activos.get(None, 0):2} medios")

    # --- Muestra: resolver links de Google News y bajar el texto
    resolucion = []
    if args.muestra:
        from .recolectar import compilar_prefiltro
        from .texto import normalizar

        rnd = random.Random(7)
        # Se prueban notas que parecen siniestros (pasan el prefiltro de palabras clave): son las que, tras
        # el filtro con Claude, van a necesitar la URL original. Las de otros países se descartan antes.
        pf = compilar_prefiltro(config.cargar_yaml("consultas.yaml")["palabras_clave"])
        gn = [it for it in items if it.get("gn_id") and not it.get("clave") and pf.search(normalizar(it["titulo"]))
              and not it["sitio"].endswith((".es", ".mx", ".cl", ".uy", ".co", ".pe", ".ve", ".bo", ".py", ".ec"))]
        directas = [it for it in items if it.get("clave")]
        muestra = rnd.sample(gn, min(args.muestra, len(gn))) + rnd.sample(directas, min(max(args.muestra // 3, 1), len(directas)))
        log("")
        log(f"Muestra: {len(muestra)} notas ({min(args.muestra, len(gn))} de Google News, el resto con URL directa)...")
        resolvedor, robots = Resolvedor(red), Robots(red)
        for it in muestra:
            url, metodo = resolvedor.resolver_con_metodo(it)
            fila = {"origen": "google_news" if it.get("gn_id") and not it.get("clave") else "directa",
                    "medio": it["medio"], "sitio": it["sitio"], "titulo": it["titulo"], "resuelta": bool(url),
                    "metodo": metodo or "", "url": url or "", "texto_caracteres": 0, "error": ""}
            if url:
                nota = bajar_nota(red, robots, url)
                fila["texto_caracteres"] = len(nota["texto"])
                fila["error"] = nota["error"] or ""
            else:
                fila["error"] = "no se encontró la URL original en el sitemap ni en el RSS del medio"
            resolucion.append(fila)
            marca = "ok " if url and not fila["error"] else ("URL" if url else "---")
            log(f"  [{marca}] {fila['origen']:11} {(metodo or ''):7} {it['sitio'][:26]:26} {fila['texto_caracteres']:6} car.  {fila['error'][:60]}")
        resolvedor.guardar()
        gn_filas = [f for f in resolucion if f["origen"] == "google_news"]
        if gn_filas:
            resueltas = sum(f["resuelta"] for f in gn_filas)
            con_texto = sum(1 for f in gn_filas if f["resuelta"] and not f["error"])
            por_metodo = Counter(f["metodo"] for f in gn_filas if f["resuelta"])
            log(f"Google News: se encontró la URL original de {resueltas} de {len(gn_filas)} "
                f"(en el medio: {por_metodo.get('medio', 0)}, por Bing: {por_metodo.get('bing', 0)}); con texto: {con_texto}.")
        dir_filas = [f for f in resolucion if f["origen"] == "directa"]
        if dir_filas:
            log(f"URL directa: con texto {sum(1 for f in dir_filas if not f['error'])} de {len(dir_filas)}.")
        sin_resolver = Counter(f["sitio"] for f in gn_filas if not f["resuelta"])
        if sin_resolver:
            log("  Medios sin resolver en la muestra: " + ", ".join(f"{s} ({n})" for s, n in sin_resolver.most_common(10)))

    # --- Reporte local (salida/ no se sube al repo)
    config.DIR_SALIDA.mkdir(exist_ok=True)
    ruta = config.DIR_SALIDA / f"fuentes_{date.today().isoformat()}.csv"
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["fuente", "tipo", "provincia", "estado", "total", "ventana", "pasan", "error"])
        for r in resultados:
            estado = "error" if r.error else ("tope" if r.saturada else "ok")
            w.writerow([r.tarea.nombre, r.tarea.tipo, r.tarea.provincia or "", estado, r.total, r.en_ventana, r.aceptadas, r.error or ""])
    if resolucion:
        ruta_m = config.DIR_SALIDA / f"fuentes_muestra_{date.today().isoformat()}.csv"
        with open(ruta_m, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(resolucion[0]), delimiter=";")
            w.writeheader()
            w.writerows(resolucion)
    log("")
    log(f"Reporte: {ruta.relative_to(config.RAIZ)}")


def cmd_diario(args) -> None:
    from . import estado
    from .claude import ErrorClaude
    from .pipeline import correr_diario

    if args.si_no_corrio_hoy and estado.corrio_hoy():
        log(f"La corrida de hoy ({estado.hoy().isoformat()}) ya se hizo: no hay nada que hacer.")
        return
    try:
        resumen = correr_diario(publicar=not args.sin_publicar, log=log, tope=args.tope)
    except ErrorClaude as exc:
        log(f"No se pudo correr: {exc}")
        sys.exit(1)
    if resumen.get("incompleta"):
        # todo lo que sí se procesó quedó guardado; el día no se marca para que el próximo intento lo repita
        log(f"Corrida incompleta: {resumen['incompleta']}. No se marca como hecha.")
        sys.exit(1)
    # una corrida de prueba con --tope no reemplaza a la del día
    if not args.sin_publicar and args.tope is None:
        estado.marcar_diario(resumen, publicado=True)


def cmd_reprocesar(args) -> None:
    from .claude import ErrorClaude
    from .pipeline import reprocesar

    try:
        date.fromisoformat(args.desde)
    except ValueError:
        log("--desde tiene que ser una fecha AAAA-MM-DD")
        sys.exit(2)
    try:
        reprocesar(args.desde, log=log, publicar=not args.sin_publicar)
    except ErrorClaude as exc:
        log(f"No se pudo correr: {exc}")
        sys.exit(1)


def cmd_auditoria(args) -> None:
    from .auditoria import generar, generar_eventos

    ruta, filas = generar(n=args.n, dias=args.dias)
    if not filas:
        log(f"No hay fichas de los últimos {args.dias} días para auditar (¿ya corrió `diario`?).")
        return
    log(f"Muestra de {filas} fichas para revisar a mano: {ruta}")
    log("Abrila con Excel, abrí cada link y completá las tres columnas de revisión.")
    ruta_ev, filas_ev = generar_eventos(n=max(args.n // 2, 5), dias=args.dias)
    log(f"Muestra de la agrupación ({filas_ev} filas: siniestros fusionados y pares separados): {ruta_ev}")


def cmd_demo(args) -> None:
    from .demo import correr_demo

    correr_demo(servir=not args.sin_servidor, puerto=args.puerto, log=log)


def _pendiente(etapa: str):
    def cmd(args) -> None:
        log(f"Este comando llega en la etapa de {etapa}.")
        sys.exit(2)
    return cmd


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m radar_vial", description="Radar Vial · Observatorio Humanitario")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("fuentes", help="prueba cada consulta y feed, informa cuáles responden")
    s.add_argument("--solo", choices=["google", "medios"], help="probar solo Google News o solo los medios")
    s.add_argument("--muestra", type=int, default=15, help="notas de Google News para probar la resolución y descarga (0 = no probar)")
    s.set_defaults(func=cmd_fuentes)

    s = sub.add_parser("demo", help="dashboard con datos de ejemplo, sin API")
    s.add_argument("--puerto", type=int, default=8000)
    s.add_argument("--sin-servidor", action="store_true", help="solo arma salida/demo, sin abrir un servidor local")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("diario", help="corrida real")
    s.add_argument("--sin-publicar", action="store_true", help="genera todo pero no actualiza docs/")
    s.add_argument("--tope", type=int, help="notas que pasan a la extracción en esta corrida (pisa config.yaml)")
    s.add_argument("--si-no-corrio-hoy", action="store_true",
                   help="no hace nada si hoy ya hubo una corrida publicada (para los reintentos de GitHub Actions)")
    s.set_defaults(func=cmd_diario)

    s = sub.add_parser("reprocesar", help="rehace extracción y eventos sin volver a bajar")
    s.add_argument("--desde", required=True, help="AAAA-MM-DD")
    s.add_argument("--sin-publicar", action="store_true", help="genera todo pero no actualiza docs/")
    s.set_defaults(func=cmd_reprocesar)

    s = sub.add_parser("auditoria", help="muestra al azar para revisión manual (CSV)")
    s.add_argument("--n", type=int, default=30, help="cantidad de fichas de la muestra")
    s.add_argument("--dias", type=int, default=7, help="tomar notas publicadas en los últimos N días")
    s.set_defaults(func=cmd_auditoria)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
