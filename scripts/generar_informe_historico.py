"""Informe de la recuperación histórica: lee las cifras (JSON de analizar_historico.py) y los textos (JSON propio)
y escribe un HTML autocontenido con gráficos SVG. Uso: generar_informe.py cifras.json textos.json salida.html"""
import json
import sys
from datetime import date
from html import escape

cifras = json.loads(open(sys.argv[1], encoding="utf-8").read())
textos = json.loads(open(sys.argv[2], encoding="utf-8").read())
destino = sys.argv[3]

N = lambda x: f"{x:,.0f}".replace(",", ".")  # noqa: E731
P = lambda a, b: f"{100 * a / b:.0f}%" if b else "—"  # noqa: E731
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
corta = lambda iso: f"{int(iso[8:10])}/{int(iso[5:7])}"  # noqa: E731

TIPO = {"choque_frontal": "Choque frontal", "choque_por_alcance": "Choque por alcance", "choque_lateral": "Choque lateral",
        "choque_sin_detalle": "Choque (sin detalle)", "vuelco": "Vuelco", "atropello": "Atropello", "despiste": "Despiste",
        "caida": "Caída de moto o bicicleta", "tren": "Con un tren", "multiple": "Choque múltiple", "otro": "Otro",
        "sin dato": "Sin dato"}
VEH = {"auto": "Auto", "moto": "Moto", "camion": "Camión", "colectivo": "Colectivo", "bicicleta": "Bicicleta",
       "peaton": "Peatón", "tren": "Tren", "utilitario": "Camioneta o utilitario", "otro": "Otro", "sin dato": "Sin dato"}
VIA = {"ruta_nacional": "Ruta nacional", "ruta_provincial": "Ruta provincial", "autopista": "Autopista o autovía",
       "urbana": "Calle o avenida", "rural": "Camino rural", "desconocida": "Sin dato", "sin dato": "Sin dato"}
FRANJA = {"madrugada": "Madrugada (0 a 6 h)", "manana": "Mañana (6 a 12 h)", "tarde": "Tarde (12 a 19 h)",
          "noche": "Noche (19 a 24 h)", "desconocida": "Sin dato", "sin dato": "Sin dato"}
GRUPO = {"ninez": "Niñez", "adolescente": "Adolescencia", "joven": "Juventud", "adulto": "Adultez",
         "persona_mayor": "Personas mayores", "sin dato": "Sin dato"}
FACTOR = {"alcohol": "Alcohol", "velocidad": "Velocidad", "celular": "Celular", "clima": "Clima",
          "estado_de_la_ruta": "Estado de la ruta", "fatiga": "Fatiga o descompensación", "sobrepaso": "Maniobra de sobrepaso",
          "sin_casco": "Sin casco", "sin_cinturon": "Sin cinturón", "animal_suelto": "Animal suelto",
          "semaforo_o_prioridad": "Semáforo o prioridad de paso", "falla_mecanica": "Falla mecánica", "otro": "Otro",
          "sin dato": "Sin dato"}


def barras_dia(serie, campos, colores, nombres, corte, alto=220, titulo=""):
    """Barras verticales por día (apiladas si hay más de un campo), con una línea en la fecha de corte."""
    dias = list(serie)
    totales = [sum(serie[d][c] for c in campos) for d in dias]
    tope = max(totales) or 1
    paso = 10 ** (len(str(int(tope))) - 1)
    tope_eje = ((tope // paso) + 1) * paso
    an, izq, abajo, arriba = 760, 44, 34, 12
    ancho = (an - izq - 8) / len(dias)
    h = alto - abajo - arriba
    y = lambda v: arriba + h - h * v / tope_eje  # noqa: E731
    partes = [f'<svg viewBox="0 0 {an} {alto}" role="img" aria-label="{escape(titulo)}" class="grafico">']
    for k in range(0, 5):
        v = tope_eje * k / 4
        partes.append(f'<line x1="{izq}" x2="{an - 8}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grilla"/>'
                      f'<text x="{izq - 6}" y="{y(v) + 4:.1f}" class="eje" text-anchor="end">{N(v)}</text>')
    for i, d in enumerate(dias):
        x = izq + i * ancho + ancho * 0.12
        base = 0
        for c, color in zip(campos, colores):
            v = serie[d][c]
            if v:
                partes.append(f'<rect x="{x:.1f}" y="{y(base + v):.1f}" width="{ancho * 0.76:.1f}" '
                              f'height="{y(base) - y(base + v):.1f}" fill="{color}"><title>{corta(d)}: '
                              f'{N(v)} {escape(nombres[campos.index(c)].lower())}</title></rect>')
            base += v
        if i % 3 == 0 or i == len(dias) - 1:
            partes.append(f'<text x="{x + ancho * 0.38:.1f}" y="{alto - abajo + 16}" class="eje" text-anchor="middle">{corta(d)}</text>')
    if corte in dias:
        xc = izq + dias.index(corte) * ancho
        partes.append(f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{arriba - 4}" y2="{alto - abajo}" class="corte"/>'
                      f'<text x="{xc + 5:.1f}" y="{arriba + 8}" class="corte-txt">Desde acá, la mitad de las notas tiene texto</text>')
    partes.append("</svg>")
    return "".join(partes)


def barras_h(filas, etiquetas=None, tope=None, sufijo=""):
    """Barras horizontales en HTML: [(nombre, valor)]."""
    tope = tope or max([v for _, v in filas] or [1]) or 1
    out = ['<div class="barras-h">']
    for nombre, v in filas:
        nombre = (etiquetas or {}).get(nombre, nombre)
        out.append(f'<div class="fila-h"><span class="nom">{escape(str(nombre))}</span>'
                   f'<span class="pista"><span class="barra" style="width:{100 * v / tope:.1f}%"></span></span>'
                   f'<span class="val">{N(v)}{sufijo}</span></div>')
    out.append("</div>")
    return "".join(out)


def tabla(encabezados, filas, numericas=()):
    out = ['<div class="tabla-env"><table><thead><tr>']
    out += [f'<th{" class=num" if i in numericas else ""}>{escape(h)}</th>' for i, h in enumerate(encabezados)]
    out.append("</tr></thead><tbody>")
    for f in filas:
        out.append("<tr>" + "".join(f'<td{" class=num" if i in numericas else ""}>{escape(str(v))}</td>' for i, v in enumerate(f)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


t, a, b, ref = cifras["total"], cifras["antes_8_11"], cifras["desde_8_11"], cifras["referencia_diario"]
cortedia = "2026-11-08"
sin_dato = lambda lista: [(k, v) for k, v in lista if k not in ("sin dato", "desconocida")]  # noqa: E731

provincias = [p for p in cifras["provincias"] if p["provincia"] != "Sin provincia"]
sin_prov = next((p["siniestros"] for p in cifras["provincias"] if p["provincia"] == "Sin provincia"), 0)

tiles = "".join(f'<div class="tile"><span class="tile-n">{v}</span><span class="tile-l">{escape(l)}</span></div>'
                for v, l in textos["tiles"])

html = f"""<meta charset="utf-8">
<title>Radar Vial histórico</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Encode+Sans:wght@400;500;600;700;900&display=swap" rel="stylesheet">
<style>
/* Una columna de lectura (68ch) con gráficos a lo ancho del contenedor; tokens del tablero de Radar Vial (Cruz Roja Argentina). */
:root {{
  --rojo: #E73743; --rojo-texto: #C11F2A; --tinta: #231F20; --pizarra: #5E686F; --papel: #FAF8F7; --blanco: #FFFFFF;
  --linea: #E3E6E8; --gris-dato: #8A9399; --rosa: #F6ACB1;
  --fuente: 'Encode Sans', 'Helvetica Neue', Arial, sans-serif;
  color-scheme: light;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--papel); color: var(--tinta); font-family: var(--fuente); font-size: 16px; line-height: 1.55; }}
.envoltura {{ max-width: 1000px; margin: 0 auto; padding-block: 32px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }}
.antetitulo {{ display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: var(--rojo-texto); margin: 0 0 8px; }}
.antetitulo::before {{ content: ""; width: 24px; height: 3px; background: currentColor; }}
h1 {{ font-weight: 900; font-size: clamp(32px, 5.5vw, 52px); line-height: 1.05; letter-spacing: -.02em; margin: 0; text-wrap: balance; }}
h2 {{ font-weight: 800; font-size: 24px; line-height: 1.2; margin: 48px 0 8px; text-wrap: balance; }}
h3 {{ font-weight: 700; font-size: 17px; margin: 24px 0 8px; }}
p, li {{ max-width: 68ch; }}
.bajada {{ font-size: 19px; color: var(--pizarra); margin: 12px 0 0; }}
.sub {{ color: var(--pizarra); font-size: 14px; margin: 0 0 12px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 28px 0 8px; }}
.tile {{ background: var(--blanco); border: 1px solid var(--linea); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 4px; }}
.tile-n {{ font-size: 34px; font-weight: 900; line-height: 1; font-variant-numeric: tabular-nums; }}
.tile-l {{ font-size: 14px; color: var(--pizarra); }}
.aviso {{ border-left: 4px solid var(--rojo); background: var(--blanco); padding: 14px 18px; margin: 24px 0; border-radius: 0 8px 8px 0; }}
.aviso p {{ margin: 6px 0; }}
.aviso strong {{ color: var(--rojo-texto); }}
ul.hallazgos {{ padding-left: 20px; display: grid; gap: 10px; }}
.tarjeta {{ background: var(--blanco); border: 1px solid var(--linea); border-radius: 8px; padding: 18px; margin: 16px 0; min-width: 0; }}
.grilla-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
.grilla-2 .tarjeta {{ margin: 0; }}
svg.grafico {{ width: 100%; height: auto; display: block; }}
svg .grilla {{ stroke: var(--linea); stroke-width: 1; }}
svg .eje {{ fill: var(--pizarra); font-size: 11px; font-family: var(--fuente); }}
svg .corte {{ stroke: var(--tinta); stroke-width: 1.5; stroke-dasharray: 4 3; }}
svg .corte-txt {{ fill: var(--tinta); font-size: 11px; font-weight: 600; font-family: var(--fuente); }}
.leyenda {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: var(--pizarra); margin-top: 8px; }}
.muestra {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }}
.barras-h {{ display: grid; gap: 6px; }}
.fila-h {{ display: grid; grid-template-columns: minmax(110px, 38%) 1fr 56px; gap: 10px; align-items: center; font-size: 14px; }}
.fila-h .nom {{ overflow-wrap: anywhere; }}
.pista {{ background: var(--papel); height: 14px; border-radius: 3px; overflow: hidden; }}
.barra {{ display: block; height: 100%; background: var(--rojo); border-radius: 0 3px 3px 0; }}
.val {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
.tabla-env {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--linea); }}
th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--pizarra); font-weight: 700; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
details summary {{ cursor: pointer; color: var(--rojo-texto); font-weight: 600; margin-top: 10px; }}
.pie {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--linea); color: var(--pizarra); font-size: 13px; }}
</style>
<div class="envoltura">
<p class="antetitulo">Radar Vial · Recuperación histórica</p>
<h1>{escape(textos["titulo"])}</h1>
<p class="bajada">{escape(textos["bajada"])}</p>
<div class="tiles">{tiles}</div>
<div class="aviso">{"".join(f"<p>{x}</p>" for x in textos["aviso"])}</div>

<h2>Lo principal</h2>
<ul class="hallazgos">{"".join(f"<li>{x}</li>" for x in textos["hallazgos"])}</ul>

<h2>Siniestros por día</h2>
<p class="sub">Según la fecha del hecho. Del 18-10 al 7-11 casi todas las notas quedaron solo con el título: la altura de esas barras no se compara con la de las siguientes.</p>
<div class="tarjeta">
{barras_dia(cifras["por_dia"], ["con_texto", "solo_titulo"], ["#E73743", "#8A9399"], ["Con texto de la nota", "Solo con el título"], cortedia, titulo="Siniestros por día")}
<div class="leyenda"><span><span class="muestra" style="background:#E73743"></span>Con el texto de al menos una nota</span><span><span class="muestra" style="background:#8A9399"></span>Conocidos solo por titulares</span></div>
<details><summary>Ver datos por día</summary>{tabla(["Día", "Con texto", "Solo titulares", "Personas fallecidas"], [[corta(d), N(v["con_texto"]), N(v["solo_titulo"]), N(v["fallecidos"])] for d, v in cifras["por_dia"].items()], (1, 2, 3))}</details>
</div>

<h2>Personas fallecidas por día</h2>
<p class="sub">Máximo informado entre las notas de cada siniestro.</p>
<div class="tarjeta">
{barras_dia(cifras["por_dia"], ["fallecidos"], ["#C11F2A"], ["Personas fallecidas"], cortedia, alto=180, titulo="Personas fallecidas por día")}
</div>

<h2>Por semana</h2>
{tabla(["Semana desde", "Siniestros", "Con víctimas fatales", "Personas fallecidas", "Solo titulares", "Con más de una fuente"],
       [[corta(k) + (" (3 días)" if k == "2026-11-15" else ""), N(v["siniestros"]), N(v["fatales"]), N(v["fallecidos"]),
         P(v["solo_titulo"], v["siniestros"]), N(v["multi_fuente"])] for k, v in cifras["semanas"].items()], (1, 2, 3, 4, 5))}

<h2>Provincias</h2>
<p class="sub">Siniestros en todo el período. La cantidad depende de cuántos medios de cada provincia publica Google News, no solo de cuántos siniestros hubo.{f" {N(sin_prov)} siniestros quedaron sin provincia." if sin_prov else ""}</p>
<div class="tarjeta">{barras_h([(p["provincia"], p["siniestros"]) for p in provincias])}</div>
<details><summary>Ver tabla por provincia</summary>{tabla(["Provincia", "Siniestros", "Cada 100.000 hab.", "Personas fallecidas", "Solo titulares", "Provincia inferida"],
       [[p["provincia"], N(p["siniestros"]), f'{p.get("tasa_100k", 0):.1f}'.replace(".", ","), N(p["fallecidos"]), P(p["solo_titulo"], p["siniestros"]), N(p["inferida"])] for p in provincias], (1, 2, 3, 4, 5))}</details>

<h2>Cómo fueron</h2>
<p class="sub">Solo siniestros con el texto de al menos una nota ({N(t["siniestros"] - t["solo_titulo"])}): de los titulares no se puede saber el tipo ni los vehículos.</p>
<div class="grilla-2">
<div class="tarjeta"><h3>Tipo de siniestro</h3>{barras_h(sin_dato(cifras["tipos_con_texto"])[:9], TIPO)}</div>
<div class="tarjeta"><h3>Vehículos y personas involucradas</h3>{barras_h(sin_dato(cifras["vehiculos_con_texto"])[:9], VEH)}</div>
<div class="tarjeta"><h3>Momento del día</h3>{barras_h(sin_dato(cifras["franja_con_texto"]), FRANJA)}</div>
<div class="tarjeta"><h3>Edades mencionadas</h3>{barras_h(sin_dato(cifras["grupos_con_texto"]), GRUPO)}</div>
<div class="tarjeta"><h3>Factores que mencionan las notas</h3>{barras_h(sin_dato(cifras["factores_con_texto"])[:8], FACTOR)}</div>
<div class="tarjeta"><h3>Tipo de vía (todos)</h3>{barras_h(sin_dato(cifras["tipo_via"]), VIA)}</div>
</div>

<h2>Rutas con más siniestros</h2>
{tabla(["Ruta", "Siniestros"], [[r, N(n)] for r, n in cifras["rutas"]], (1,))}

<h2>Calidad de los datos</h2>
<ul>{"".join(f"<li>{x}</li>" for x in textos["calidad"])}</ul>

<p class="pie">{textos["pie"]}</p>
</div>
"""
open(destino, "w", encoding="utf-8", newline="\n").write(html)
print("ok", destino, len(html))
