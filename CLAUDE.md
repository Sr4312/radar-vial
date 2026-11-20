# Radar Vial - notas para Claude Code

Herramienta del Laboratorio de Innovación del Observatorio Humanitario de Cruz Roja Argentina: detecta y
cuantifica las notas de prensa sobre siniestros viales en Argentina y las muestra en un dashboard estático
(`docs/`, GitHub Pages). **La unidad de análisis es el siniestro, no la nota**: diez notas sobre el mismo
choque son un evento con diez fuentes. Hermano del Radar Humanitario (`Desktop\NEWS-OCHRA`), del que toma
la carga de config, el historial y los lectores de feeds; acá no hay mails.

## Estado por etapas
1. Recolección: hecha y probada contra la red real (Google News + RSS + sitemaps, historial, resolución de
   links, descarga, comando `fuentes`).
2. Filtro y extracción: hecho, conectado en `diario` y `reprocesar`, probado con API simulada
   (`tests/test_pipeline.py`) y con la API real. Medición del 20-11-2026 contra las 20 notas anotadas: todos los
   campos coincidieron (USD 0,15 las 20 notas). Es preliminar: las anotaciones son borrador hecho por Claude y
   muchas aceptan alternativas; el equipo tiene que validarlas.
3. Geografía y eventos: hecho y conectado al final de `diario` y `reprocesar` (`pipeline.geo_y_eventos`);
   probado con datos reales: 380 fichas del 13 al 20-11-2026 -> 169 siniestros (77 con más de una fuente).
4. Dashboard: hecho (`docs/`, sitio estático) y probado en el navegador, en escritorio y en celular, con datos
   reales y con `demo`. `diario` y `reprocesar` publican en `docs/data/` (con `--sin-publicar`, en
   `salida/vista_previa/`).
5. Automatización y documentación: hecho. `.github/workflows/radar-vial.yml` (validado con actionlint, todavía
   sin correr en GitHub), README.md para Windows, METODOLOGIA.md. Falta: crear el repositorio, cargar el secreto
   y la primera corrida en Actions (ver Pendientes).

## Mapa del proyecto
- `config/config.yaml` - modelos, ventanas, límites, parámetros de red.
- `config/consultas.yaml` - términos que se cruzan con cada jurisdicción en Google News (una búsqueda por par,
  **sin OR**: Google News devuelve mucho menos con OR, medido el 19-11-2026), términos para las ciudades,
  búsquedas de contexto vial y palabras clave del prefiltro de los feeds y sitemaps de medios.
- `config/provincias.yaml` - las 24 jurisdicciones con id INDEC/Georef (verificados), `busqueda`, `ciudades`, alias.
- `config/fuentes.yaml` - catálogo de medios (lo genera `scripts/descubrir_fuentes.py`, se edita a mano):
  `feeds` (RSS), `sitemap` (sitemap de noticias, se lee si no hay feed), `activo`, `verificar`.
  `oficiales`: ANSV, ONG y organismos provinciales, solo como referencia (no se cuentan).
- `radar_vial/red.py` - sesión HTTP con timeout, reintentos y pausa por servidor.
- `radar_vial/recolectar.py` - arma las tareas (GN, RSS, sitemap), lee con ventana de 48 h, prefiltra los
  feeds de medios por palabras clave y fusiona la misma nota llegada por varias vías (`fusionar`).
- `radar_vial/dominios.py` - descubre feeds y sitemaps de noticias de cada dominio (caché en `data/cache/dominios.json`).
- `radar_vial/resolver.py` - URL original de los links de Google News (buscando el título en el sitemap y el RSS
  del medio), descarga con trafilatura respetando robots.txt, caché temporal de textos.
- `radar_vial/historial.py` - URL canónica, hash de título distintivo, estados y reintentos, 90 días.
- `radar_vial/pipeline.py` - `correr_diario`: recolectar -> historial -> filtro -> resolver y bajar (solo las
  relevantes) -> deduplicar por URL canónica -> extracción -> `data/notas.jsonl`. Tope por corrida
  (`limites.max_extraccion_por_corrida`): lo que no entra va a una cola en la caché temporal. `reprocesar`
  rehace fichas desde la caché de textos.
- `radar_vial/claude.py` - una llamada = un JSON con salida estructurada (`output_config.format`); esfuerzo por
  etapa; `cache_control` en el sistema; respaldo por rechazo (`fallbacks: "default"`) solo en Sonnet 5.5;
  tokens y costo estimado a `data/costos.jsonl` (precios en config.yaml).
- `radar_vial/filtrar.py` (Haiku, lotes de 40, solo título y bajada; ante la duda deja pasar) y
  `radar_vial/extraer.py` (Sonnet: confirma categoría y arma una ficha por siniestro; `choque_sin_detalle` se
  sumó a la lista de tipos porque muchas notas dicen solo "chocaron").
- `radar_vial/privacidad.py` - segunda red: detecta nombres en el texto original con los patrones de la prensa
  y los saca de la ficha; quita edades exactas del resumen.
- `radar_vial/auditoria.py` - dos CSV: muestra de fichas (`generar`) y de la agrupación (`generar_eventos`:
  siniestros fusionados "¿son el mismo?" y pares de la misma localidad y fecha "¿son distintos?").
- `radar_vial/geo.py` - Georef: localidad dentro de la provincia (prefiere nombre exacto e id corto: localidad,
  no barrio), si no departamento, si no centroide de provincia (`centro` propio para Tierra del Fuego). "La
  capital" -> `capital` de provincias.yaml. Sin provincia, se infiere (marcada `provincia_inferida` e
  `inferida_de`) si la localidad está en una sola provincia o en la del medio; si no hay localidad, de la
  provincia del medio (si las búsquedas no la contradicen) o de la única provincia por cuyas búsquedas de
  Google News llegó la nota (`provincias_busqueda`, guardado en cada nota). Caché en `data/cache/georef.json`.
  Se guarda en cada ficha (`geo`); las de nivel "ninguno" se reintentan en cada corrida.
- `radar_vial/eventos.py` - `agrupar`: fichas en orden de publicación, candidatos de ±2 días (índice por fecha),
  `comparar` da (compatibles, puntaje). Contradicciones duras: provincias distintas, más de 1 día (2 si la fecha
  es aproximada), rutas con distinto número, km a más de 30 entre localidades distintas, dos esquinas distintas
  (cada una con 2 calles y ninguna en común; se ignoran palabras genéricas como bulevar o rotonda, el nombre de
  la localidad y errores de tipeo), dos fichas de una misma nota. `comparar_detalle` marca cada contradicción
  como absoluta (provincia, fecha, número de ruta, km lejanos en otra localidad) o tolerable (dos esquinas).
  `Evento.evaluar`: una absoluta con cualquier ficha deja afuera; una tolerable solo si contradice a la mayoría
  de las fichas del evento (una nota con una calle mal no bloquea), y cada una resta 1. Puntaje >= 4 con margen
  de 1 y ficha no débil: se fusiona; dudoso (o ficha solo de título): `Desempate`
  con Claude, que ve fichas y títulos (de la caché temporal); solo fusiona con seguridad alta o media; decisión
  guardada en `data/cache/decisiones_eventos.json`. `consolidar`: dato más completo, víctimas de la nota más
  reciente, tipo específico sobre "sin detalle". Se rehace todo en cada corrida y `asignar_ids` conserva ids
  (`ev_AAAAMMDD_<prov>_<hash>`). Salida: `data/eventos.jsonl`. Para revisar la agrupación: buscar eventos con
  fichas de localidades o vehículos distintos (fusión de más) y pares de eventos de la misma localidad y fecha
  (fusión faltante); así se encontraron los casos de Villa María, Canals, Posadas y Mocoretá del 20-11-2026.
- Tope por corrida con `cupo_contexto` (50) reservado para las notas de contexto (`pipeline.elegir_para_extraer`).
- `tests/fixtures/notas_anotadas.yaml` - 20 notas reales (URL + anotación **borrador**, a validar por el equipo);
  `tests/medir_extraccion.py` baja los textos a la caché, extrae y reporta precisión por campo.

## Mediciones (20-11-2026)
- Primera corrida real (`diario --sin-publicar --tope 50`): 1.847 notas candidatas en 48 h; el filtro marcó 494
  siniestros y 182 de contexto (676 relevantes, 37%). Duración 12 min (unos 8 de recolección). Costo: filtro
  USD 0,05; extracción USD 0,30 por 49 notas (unos USD 0,006 por nota). 7 de 50 notas quedaron solo con título.
- El mismo siniestro llega por muchos medios (un choque en San Juan: unas 10 notas): la etapa de eventos es la
  que convierte notas en siniestros.
- Precisión contra las 20 notas anotadas (borrador): Sonnet 5.5 con esfuerzo medium, 1 diferencia en unos 180
  campos (USD 0,15); Haiku 5.5, 5 diferencias (USD 0,013). Se dejó Sonnet.
- Tercera corrida (`diario --si-no-corrio-hoy`, como en Actions): vació la cola (225) y extrajo 278 notas (83
  de siniestros, 160 de contexto gracias al cupo, 35 descartadas al leerlas), 76 solo con título; USD 1,68,
  22 min, sin errores. Quedaron 216 siniestros a partir de 473 fichas (90 con más de una fuente).
- Contexto: 162 notas -> 129 novedades con umbral 0,25 de parecido de resúmenes (0,35 dejaba duplicados, 0,20
  mezclaba novedades distintas). 68 de las 129 son partes de estado de rutas: tapan normas, controles y campañas.
- Ajustes de consigna que salieron de la corrida real: el resumen no habla de la nota; no se mencionan
  ocupaciones ni vínculos (si aparecen, `privacidad` marca la ficha "revisar"); una alcoholemia negativa no es
  un factor.

## Dashboard (docs/)
- `radar_vial/agregados.py` escribe `docs/data/`: `eventos.json` (últimos 31 días, campos vacíos omitidos,
  hasta 12 fuentes por siniestro y `n_fuentes`), `serie_diaria.json` (todo el histórico por día y provincia:
  siniestros, fallecidos, heridos y lo mismo solo de titulares), `resumen_semana.json` (7 días completos hasta
  ayer contra los 7 anteriores; los 2 últimos días "en carga"), `contexto.json` (agrupado entre medios por
  subtipo, provincia, fecha y parecido del resumen) y `meta.json` (provincias con población, oficiales).
- `docs/index.html` + `docs/assets/app.js` + `estilos.css`: sin backend. Chart.js 4.4.1 y Leaflet 1.9.4 desde
  cdnjs con hash de integridad (SRI); si se cambia la versión, recalcular el hash. Teselas Argenmap del IGN
  (TMS, `tms: true`). Mapa: `docs/data/provincias.geojson`, generado una vez con `scripts/preparar_mapa.py`
  (WFS del IGN simplificado; sin el sector antártico, que la proyección web no puede mostrar; hay una nota).
- Reglas del tablero: los textos de los datos van siempre con `textContent` (función `el`), nunca innerHTML;
  números con `Intl.NumberFormat("es-AR")`; texto chico en rojo con #C11F2A (AA), #E73743 solo para marcas
  de datos y filetes; un solo color de datos por gráfico; siniestros y fallecidos en gráficos separados (sin
  doble eje); cada gráfico tiene su tabla en "Ver datos"; casilla para excluir los siniestros solo de titulares.
- `inicio_cobertura` (config.yaml, 2026-11-18): desde cuándo registra el radar. Va en meta.json; el tablero no
  compara contra períodos que empiezan antes ("Sin datos completos"), pinta en gris los días y semanas previos y
  lo avisa. `resumen_semana.json` trae `periodo_completo` y `previo_completo`. La serie diaria tiene 6
  columnas (siniestros, fallecidos y heridos, y lo mismo solo de titulares) para que la casilla excluya todo.
- Población: INDEC, Censo 2022, resultados definitivos (total 45.892.285; el 46.044.703 que circula es el
  provisorio). Está en `config/provincias.yaml`.
- `python -m radar_vial demo` arma `salida/demo/` con siniestros ficticios (lugares reales, enlaces a
  example.org, aviso fijo de datos de ejemplo) y lo sirve en http://localhost:8000. `.claude/launch.json` tiene
  `radar-vial-demo` y `radar-vial-docs` (sirve docs/ en el puerto 8001) para la vista previa.
- Peso: con 169 siniestros, `eventos.json` pesa 175 KB (54 KB comprimido); los enlaces son el 37%. Si con el
  volumen real pasa de unos 2 MB, separar las fuentes en otro archivo que se cargue con la tabla.

## Automatización (GitHub Actions)
- `.github/workflows/radar-vial.yml`: cron `17 9-21/2 * * *` (06:17 a 18:17 de Argentina, cada 2 h) con
  `diario --si-no-corrio-hoy`: corre una sola vez por día (`data/estado.json`, `radar_vial/estado.py`), porque
  los cron de GitHub llegan tarde o no llegan (lección del Radar Humanitario). Disparo manual: siempre corre, con
  `sin_publicar` y `tope` (los inputs entran por `env`, no pegados en el script; el tope se valida numérico).
- Pasos: pytest -> caché de Actions de `data/cache/textos` (clave por corrida, restaura la última) -> diario ->
  commit de `data/` (historial, notas, eventos, costos, estado y cachés públicas) y de `docs/data` si se publicó,
  con reintentos de push -> resumen de costos en la página de la corrida -> artefacto `salida/` (14 días) ->
  job `publicar` (Pages desde Actions: Settings > Pages > Source: GitHub Actions) solo si cambió `docs/data`.
- Secreto: `ANTHROPIC_API_KEY` (Settings > Secrets and variables > Actions). Nunca en el código ni en `.env.ejemplo`.
- Los textos de las notas no migran: los que se bajan en Actions viven solo en la caché de Actions, y los de esta
  computadora solo acá. `reprocesar` corrido localmente solo rehace las notas procesadas en la misma máquina;
  para rehacer lo procesado en Actions, correrlo desde un workflow (o esperar a la corrida diaria).

## Pendientes conocidos
- Crear el repositorio (público, para Pages gratis), subirlo, cargar el secreto, activar Pages y hacer la primera
  corrida manual. Verificar ahí que Google News no bloquee las 314 búsquedas desde las IP de Actions (desde la
  oficina no hubo errores) y la duración real (una corrida de 400 notas tardó 29 min; el job tiene 90).
- Validar las 20 notas de `tests/fixtures/notas_anotadas.yaml` (borrador) y medir la precisión de la agrupación
  con las planillas de `auditoria`.
- Medir el volumen diario real con el historial ya armado (estimado: unas 340 notas relevantes por día) y ajustar
  `max_extraccion_por_corrida` (hoy 400) para que la cola no crezca.
- 16 medios con `verificar: true` en `config/fuentes.yaml` (entre ellos La Voz, que bloquea lectores automáticos).
- Peso de `docs/data/eventos.json` con el volumen real (ver Dashboard).

## Estados del historial
`descartada`, `siniestro`, `contexto`, `duplicada`, `sin_texto` son finales. `solo_titulo` (ficha hecha solo con
el título porque no se encontró la URL o no se pudo bajar), `pendiente` (falló la extracción) y `sin_resolver`
se reintentan hasta 3 veces; si una corrida posterior consigue el texto, la ficha se rehace (mismo `id_nota`).

## Decisiones que no hay que romper
- **Links de Google News**: no se decodifican con el servicio interno de Google (no documentado; el entorno lo
  bloqueó y es frágil). Se resuelven por título contra el sitemap de noticias o el RSS del propio medio y, si no
  aparece, buscando el título exacto en el RSS público de Bing Noticias (solo se acepta un resultado del mismo
  dominio y con el mismo título; `resolucion.bing` en config.yaml). Lo que no aparece queda `sin_resolver` y se
  reintenta (hasta 3 corridas). El filtro corre antes de resolver: solo se resuelven notas relevantes.
- **Privacidad**: el texto completo de las notas trae nombres de personas. Va solo a `data/cache/textos/`
  (gzip, 14 días, en `.gitignore`); en Actions se conserva con la caché de Actions, nunca en el repo. El
  historial guarda claves y estado, no títulos. El dashboard muestra el resumen propio y el nombre del medio
  como texto del link (los titulares pueden traer nombres).
- **Títulos genéricos** ("Murió un motociclista en un choque") no deduplican: `titulo_distintivo` exige 5
  palabras no genéricas. Preferimos procesar dos veces a fusionar dos siniestros distintos.
- **robots.txt** se respeta al bajar notas. Se lee lo que los medios publican para lectores automáticos
  (feeds, sitemaps). User-Agent honesto: `RadarVial/1.0 (Observatorio Humanitario - Cruz Roja Argentina)`.
- Mensajes de consola: `texto.log`, que reemplaza lo que la consola cp1252 de Windows no puede mostrar.

## Comandos
- `.venv\Scripts\python.exe -m radar_vial demo [--sin-servidor]` - tablero con datos ficticios en http://localhost:8000.
- `.venv\Scripts\python.exe -m radar_vial diario [--sin-publicar] [--tope N] [--si-no-corrio-hoy]` - corrida real
  (usa la API); `--tope` limita las notas que pasan a la extracción en esa corrida (el resto queda en la cola).
- `.venv\Scripts\python.exe -m radar_vial reprocesar --desde AAAA-MM-DD [--sin-publicar]` - rehace fichas y
  eventos sin volver a bajar (textos de los últimos 14 días) y republica.
- `.venv\Scripts\python.exe -m radar_vial auditoria --n 30 [--dias 7]` - CSV en `salida/` para revisión manual.
- `.venv\Scripts\python.exe tests\medir_extraccion.py [--sin-api salida\medicion_extraccion_<fecha>.json]` -
  precisión por campo (usa la API salvo con `--sin-api`).
- `.venv\Scripts\python.exe -m radar_vial fuentes [--solo google|medios] [--muestra 15]` - diagnóstico.
- `.venv\Scripts\python.exe -m pytest -q` - pruebas sin red ni claves. Correrlas después de cada cambio.
- `.venv\Scripts\python.exe scripts\preparar_mapa.py` - regenera `docs/data/provincias.geojson` (necesita shapely).
- `.venv\Scripts\python.exe scripts\descubrir_fuentes.py [dominio ...]` - descubrir feeds de medios nuevos
  (sin argumentos regenera `config/fuentes.yaml` a partir de la lista CANDIDATOS: pisa las ediciones a mano).
