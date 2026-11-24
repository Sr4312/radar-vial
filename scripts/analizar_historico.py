"""Cifras para el informe de la recuperación histórica (18-10 al 17-11-2026). Uso: analizar_historico.py [eventos.jsonl]"""
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "data/historico/eventos.jsonl"
DESDE, HASTA = date(2026, 10, 18), date(2026, 11, 17)
CORTE_TEXTO = date(2026, 11, 8)   # antes de esto casi todas las notas quedaron solo con el título (Bing: ~14 días)

provs = {p["id"]: p for p in yaml.safe_load((RAIZ / "config/provincias.yaml").read_text(encoding="utf-8"))["provincias"]}
evs = [json.loads(l) for l in ARCHIVO.read_text(encoding="utf-8").splitlines() if l.strip()]
evs = [e for e in evs if DESDE <= date.fromisoformat(e["fecha_hecho"]) <= HASTA]
fal = lambda e: e.get("fallecidos") or 0  # noqa: E731
her = lambda e: e.get("heridos_total") or 0  # noqa: E731
out = {}


def resumen(lista):
    return {"siniestros": len(lista), "fatales": sum(1 for e in lista if fal(e) > 0), "fallecidos": sum(fal(e) for e in lista),
            "heridos": sum(her(e) for e in lista), "solo_titulo": sum(1 for e in lista if e.get("solo_titulos")),
            "multi_fuente": sum(1 for e in lista if e["n_fuentes"] > 1), "fichas": sum(len(e["fichas"]) for e in lista)}


out["total"] = resumen(evs)
antes = [e for e in evs if date.fromisoformat(e["fecha_hecho"]) < CORTE_TEXTO]
despues = [e for e in evs if date.fromisoformat(e["fecha_hecho"]) >= CORTE_TEXTO]
out["antes_8_11"] = {**resumen(antes), "dias": (CORTE_TEXTO - DESDE).days}
out["desde_8_11"] = {**resumen(despues), "dias": (HASTA - CORTE_TEXTO).days + 1}

semanas = defaultdict(list)
for e in evs:
    d = date.fromisoformat(e["fecha_hecho"])
    inicio = DESDE + timedelta(days=7 * ((d - DESDE).days // 7))
    semanas[inicio.isoformat()].append(e)
out["semanas"] = {k: resumen(v) for k, v in sorted(semanas.items())}

por_dia = Counter(e["fecha_hecho"] for e in evs)
out["dias"] = dict(sorted(por_dia.items()))

por_prov = defaultdict(list)
for e in evs:
    por_prov[e.get("provincia_id") or "?"].append(e)
filas = []
for pid, lista in por_prov.items():
    r = resumen(lista)
    p = provs.get(pid)
    r["provincia"] = p["nombre"] if p else "Sin provincia"
    if p:
        r["tasa_100k"] = round(r["siniestros"] / p["poblacion"] * 100000, 2)
        r["fallecidos_100k"] = round(r["fallecidos"] / p["poblacion"] * 100000, 2)
    r["inferida"] = sum(1 for e in lista if e.get("provincia_inferida"))
    filas.append(r)
out["provincias"] = sorted(filas, key=lambda r: -r["siniestros"])


def contar(campo, lista=evs, multiple=False):
    c = Counter()
    for e in lista:
        v = e.get(campo)
        for x in (v or ["sin dato"]) if multiple else [v or "sin dato"]:
            c[x if not isinstance(x, dict) else x.get("factor")] += 1
    return c.most_common()


completos = [e for e in evs if not e.get("solo_titulos")]
out["tipos"] = contar("tipo_siniestro")
out["tipos_con_texto"] = contar("tipo_siniestro", completos)
out["vehiculos_con_texto"] = contar("vehiculos", completos, multiple=True)
out["tipo_via"] = contar("tipo_via")
out["franja_con_texto"] = contar("hora_franja", completos)
out["grupos_con_texto"] = contar("grupos_etarios", completos, multiple=True)
out["factores_con_texto"] = contar("factores_mencionados", completos, multiple=True)
out["dia_semana"] = Counter(["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][date.fromisoformat(e["fecha_hecho"]).weekday()]
                            for e in evs).most_common()
out["nivel_geo"] = contar("nivel_geo")
out["n_fuentes"] = sorted(Counter(min(e["n_fuentes"], 6) for e in evs).items())
out["fecha_aproximada"] = sum(1 for e in evs if e.get("fecha_aproximada"))
rutas = Counter(e["via"].split(" km")[0].strip() for e in evs
                if e.get("tipo_via") in ("ruta_nacional", "ruta_provincial") and e.get("via"))
out["rutas"] = rutas.most_common(15)
out["fallecidos_por_tipo_via"] = sorted(((k, sum(fal(e) for e in evs if (e.get("tipo_via") or "sin dato") == k))
                                         for k in {e.get("tipo_via") or "sin dato" for e in evs}), key=lambda x: -x[1])
dia = defaultdict(lambda: {"con_texto": 0, "solo_titulo": 0, "fallecidos": 0})
for e in evs:
    x = dia[e["fecha_hecho"]]
    x["solo_titulo" if e.get("solo_titulos") else "con_texto"] += 1
    x["fallecidos"] += fal(e)
d = DESDE
while d <= HASTA:
    dia[d.isoformat()]
    d += timedelta(days=1)
out["por_dia"] = dict(sorted(dia.items()))
# referencia: el radar diario (texto completo de las notas recientes), días cerrados 18 al 20-11
diario = [json.loads(l) for l in (RAIZ / "data/eventos.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
ref = [e for e in diario if "2026-11-18" <= e["fecha_hecho"] <= "2026-11-20"]
out["referencia_diario"] = {**resumen(ref), "dias": 3}
destino = Path(sys.argv[2]) if len(sys.argv) > 2 else None
texto = json.dumps(out, ensure_ascii=False, indent=1)
if destino:
    destino.write_text(texto, encoding="utf-8")
print(texto)
