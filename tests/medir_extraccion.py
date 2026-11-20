"""Mide la precisión de la extracción contra las 20 notas anotadas (tests/fixtures/notas_anotadas.yaml).

Uso:
  python tests/medir_extraccion.py                 # baja las notas que falten, extrae con Claude y compara
  python tests/medir_extraccion.py --sin-api ARCH  # vuelve a comparar respuestas guardadas, sin llamar a la API

Usa la API (unos centavos de dólar por corrida). Guarda las respuestas en salida/medicion_extraccion_<fecha>.json
y suma el costo a data/costos.jsonl. Los textos bajados quedan en data/cache/textos/fixtures (fuera de git).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar_vial import config  # noqa: E402
from radar_vial.extraer import _normalizar_provincia  # noqa: E402
from radar_vial.privacidad import nombres_en_texto, nombres_probables  # noqa: E402
from radar_vial.texto import log, normalizar  # noqa: E402

ANOTADAS = Path(__file__).parent / "fixtures" / "notas_anotadas.yaml"
CACHE = config.DIR_TEXTOS / "fixtures"
CONJUNTOS = ("vehiculos", "grupos_etarios", "factores")


def cargar_anotadas() -> list[dict]:
    return yaml.safe_load(ANOTADAS.read_text(encoding="utf-8"))["notas"]


def texto_de(nota: dict) -> dict:
    """Título y texto de la nota: de la caché temporal o, si no está, bajándola (respetando robots.txt)."""
    ruta = CACHE / f"{nota['id']}.json"
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    from radar_vial.red import Red
    from radar_vial.resolver import Robots, bajar_nota

    red = Red()
    bajada = bajar_nota(red, Robots(red), nota["url"])
    datos = {"titulo": bajada["titulo"], "url": nota["url"], "texto": bajada["texto"], "error": bajada["error"]}
    CACHE.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


# ------------------------------------------------------------------ comparación

def _opciones(esperado):
    return esperado["uno_de"] if isinstance(esperado, dict) and "uno_de" in esperado else [esperado]


def _valor(ficha: dict, campo: str):
    if campo == "heridos_total":
        partes = [ficha.get(c) for c in ("heridos_graves", "heridos_leves", "heridos_sin_detalle")]
        return None if all(p is None for p in partes) else sum(p or 0 for p in partes)
    if campo == "factores":
        return sorted({f["factor"] for f in ficha.get("factores_mencionados") or []})
    if campo == "provincia":
        return ficha.get("provincia_id")
    return ficha.get(campo)


def coincide(campo: str, extraido, esperado) -> bool:
    for e in _opciones(esperado):
        if campo in CONJUNTOS:
            if sorted(set(extraido or [])) == sorted(set(e or [])):
                return True
        elif campo == "provincia":
            if extraido == (_normalizar_provincia(e) if e else None):
                return True
        elif campo == "localidad":
            a, b = normalizar(extraido or ""), normalizar(e or "")
            if (not a and not b) or (a and b and (a in b or b in a)):
                return True
        elif campo == "via_contiene":
            via = normalizar(extraido or "")
            if all(normalizar(t) in via for t in e):
                return True
        elif extraido == e:
            return True
    return False


def comparar_ficha(ficha: dict, esperada: dict) -> dict[str, bool]:
    res = {}
    for campo, esperado in esperada.items():
        extraido = ficha.get("via") if campo == "via_contiene" else _valor(ficha, campo)
        res[campo] = coincide(campo, extraido, esperado)
    return res


def emparejar(fichas: list[dict], esperadas: list[dict]) -> list[tuple[dict, dict]]:
    """Empareja cada ficha esperada con la extraída que más campos acierta (sin repetir)."""
    libres = list(fichas)
    pares = []
    for esp in esperadas:
        if not libres:
            break
        mejor = max(libres, key=lambda f: sum(comparar_ficha(f, esp).values()))
        libres.remove(mejor)
        pares.append((mejor, esp))
    return pares


def evaluar(anotadas: list[dict], respuestas: dict[str, dict], textos: dict[str, str]) -> dict:
    aciertos, totales = defaultdict(int), defaultdict(int)
    detalle, alertas = [], []
    for nota in anotadas:
        r = respuestas.get(nota["id"])
        if r is None:
            alertas.append(f"{nota['id']}: sin respuesta")
            continue
        totales["categoria"] += 1
        ok_cat = coincide("categoria", r["categoria"], nota["categoria"])
        aciertos["categoria"] += ok_cat
        esperadas = nota.get("siniestros") or []
        if "siniestro" in _opciones(nota["categoria"]) and r["categoria"] == "siniestro" and esperadas:
            totales["cantidad_de_siniestros"] += 1
            aciertos["cantidad_de_siniestros"] += len(r["siniestros"]) == len(esperadas)
            for ficha, esp in emparejar(r["siniestros"], esperadas):
                for campo, ok in comparar_ficha(ficha, esp).items():
                    totales[campo] += 1
                    aciertos[campo] += ok
                    if not ok:
                        detalle.append(f"{nota['id']} {campo}: extraído={json.dumps(ficha.get('via') if campo == 'via_contiene' else _valor(ficha, campo), ensure_ascii=False)} esperado={json.dumps(esp[campo], ensure_ascii=False)}")
        if nota.get("contexto") and r.get("contexto"):
            for campo in ("subtipo", "provincia"):
                if campo in nota["contexto"]:
                    totales[f"contexto.{campo}"] += 1
                    valor = r["contexto"].get("provincia_id") if campo == "provincia" else r["contexto"].get(campo)
                    aciertos[f"contexto.{campo}"] += coincide(campo, valor, nota["contexto"][campo])
        if not ok_cat:
            detalle.append(f"{nota['id']} categoria: extraído={r['categoria']} esperado={nota['categoria']}")
        # privacidad: ningún nombre del texto en la ficha
        nombres = nombres_en_texto(textos.get(nota["id"], "")) | nombres_probables(textos.get(nota["id"], ""))
        volcado = json.dumps(r, ensure_ascii=False).lower()
        for n in nombres:
            if n.lower() in volcado:
                alertas.append(f"{nota['id']}: PRIVACIDAD - un nombre de la nota quedó en la ficha")
        for f in r.get("siniestros") or []:
            for marca in f.get("privacidad") or []:
                if marca.startswith("revisar"):
                    alertas.append(f"{nota['id']}: {marca}")
    return {"aciertos": dict(aciertos), "totales": dict(totales), "detalle": detalle, "alertas": alertas}


def informar(res: dict, respuestas: dict | None = None) -> None:
    if respuestas:
        # El control automático solo detecta nombres presentados con los patrones habituales de la prensa:
        # el equipo tiene que leer estos resúmenes y confirmar que ninguno identifica a una persona.
        log("")
        log("Resúmenes (revisar a ojo que no identifiquen a nadie):")
        for i, r in sorted(respuestas.items()):
            for f in r.get("siniestros") or []:
                log(f"  {i}: {f.get('resumen')}")
            if r.get("contexto"):
                log(f"  {i} (contexto): {r['contexto'].get('resumen')}")
    log("")
    log(f"{'CAMPO':28} {'ACIERTOS':>9} {'PRECISIÓN':>10}")
    for campo in sorted(res["totales"], key=lambda c: (c != "categoria", c)):
        a, t = res["aciertos"].get(campo, 0), res["totales"][campo]
        log(f"{campo:28} {a:4}/{t:<4} {100 * a / t:9.0f}%")
    if res["detalle"]:
        log("")
        log("Diferencias:")
        for d in res["detalle"]:
            log("  " + d)
    for a in res["alertas"]:
        log("! " + a)


def main(argv=None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sin-api", help="archivo de respuestas guardadas para volver a comparar")
    p.add_argument("--modelo", help="modelo de extracción a probar (por defecto, el de config.yaml)")
    p.add_argument("--esfuerzo", help="esfuerzo de razonamiento a probar (low, medium, high)")
    args = p.parse_args(argv)
    if args.modelo:
        config.general()["modelos"]["extraccion"] = args.modelo
    if args.esfuerzo:
        config.general()["esfuerzo"]["extraccion"] = args.esfuerzo
    anotadas = cargar_anotadas()
    textos = {n["id"]: texto_de(n).get("texto", "") for n in anotadas}

    if args.sin_api:
        respuestas = json.loads(Path(args.sin_api).read_text(encoding="utf-8"))
    else:
        from concurrent.futures import ThreadPoolExecutor

        from radar_vial.claude import Claude, ErrorClaude, RegistroCostos
        from radar_vial.extraer import extraer_nota
        from radar_vial.recolectar import _medios_por_sitio, cargar_fuentes
        from radar_vial.dominios import dominio_de

        medios = _medios_por_sitio(cargar_fuentes())
        conf = config.general()
        registro = RegistroCostos(f"medir_extraccion {conf['modelos']['extraccion']} {conf['esfuerzo']['extraccion']}")
        claude = Claude(registro)

        def una(nota):
            datos = texto_de(nota)
            sitio = dominio_de(nota["url"])
            entrada = {"id": nota["id"], "titulo": datos.get("titulo") or "", "bajada": "", "publicada": nota["publicada"],
                       "medio": nota["medio"], "sitio": sitio, "provincia_medio": (medios.get(sitio) or {}).get("provincia")}
            try:
                return nota["id"], extraer_nota(claude, entrada, datos.get("texto") or None)
            except ErrorClaude as exc:
                log(f"  ! {nota['id']}: {exc}")
                return nota["id"], None

        with ThreadPoolExecutor(max_workers=4) as ex:
            respuestas = {i: r for i, r in ex.map(una, anotadas) if r is not None}
        costos = registro.guardar(extra={"notas": {"medidas": len(respuestas)}})
        config.DIR_SALIDA.mkdir(exist_ok=True)
        sufijo = f"_{args.modelo}" if args.modelo else ""
        salida = config.DIR_SALIDA / f"medicion_extraccion_{date.today().isoformat()}{sufijo}.json"
        salida.write_text(json.dumps(respuestas, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"Respuestas guardadas en {salida.relative_to(config.RAIZ)}. Costo estimado: USD {costos['costo_total_usd']:.3f}")
    informar(evaluar(anotadas, respuestas, textos), respuestas)


if __name__ == "__main__":
    main()
