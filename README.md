# Radar Vial

**Observatorio Humanitario · Cruz Roja Argentina · Laboratorio de Innovación**

Todos los días, el Radar Vial detecta las notas de prensa de Argentina sobre siniestros viales, las convierte
en siniestros (diez notas sobre el mismo choque son **un** siniestro con diez fuentes) y publica un tablero web
que se actualiza solo: siniestros, víctimas, mapa por provincia, distribuciones, rankings y la tabla de cada
siniestro con sus fuentes.

> Son siniestros **reportados en medios**, no estadística oficial. Ver [METODOLOGIA.md](METODOLOGIA.md).

---

## Cómo funciona (en una línea por paso)

1. **Recolecta** las notas de las últimas 48 horas: Google News (cada término por cada provincia) y los feeds y
   sitemaps de noticias de unos 70 medios nacionales y provinciales.
2. **Filtra** con un modelo económico (Claude Haiku): ¿es un siniestro vial en Argentina, contexto vial o nada?
3. **Lee** las notas relevantes y arma una ficha de cada siniestro con un modelo de mejor calidad (Claude Sonnet).
4. **Ubica** cada siniestro con la API oficial Georef y **agrupa** las notas que cuentan el mismo hecho.
5. **Publica** los datos del tablero en `docs/data/` (GitHub Pages).

Todo corre solo con GitHub Actions, todos los días desde las 06:17 de Argentina.

---

## Puesta en marcha en Windows, paso a paso

### 1. Instalar lo necesario (una sola vez)

- **Python 3.12**: bajarlo de [python.org](https://www.python.org/downloads/windows/). En el instalador, marcar
  *Add python.exe to PATH*.
- **Git**: bajarlo de [git-scm.com](https://git-scm.com/download/win) e instalarlo con las opciones por defecto.

### 2. Preparar la carpeta

Abrir **PowerShell** en la carpeta del proyecto (en el Explorador: clic derecho en la carpeta, *Abrir en
Terminal*) y correr, uno por uno:

```powershell
py -3.12 -m venv .venv
```

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Cargar la clave de la API de Claude

1. Copiar el archivo `.env.ejemplo` y renombrar la copia como `.env` (en la misma carpeta).
2. Abrir `.env` con el Bloc de notas y pegar la clave del Observatorio después del `=`:
   `ANTHROPIC_API_KEY=sk-ant-...`
3. Guardar.

**Importante:** la clave va **solo** en `.env`. Ese archivo nunca se sube a GitHub (está en `.gitignore`).
`.env.ejemplo` sí se sube: no pegues la clave ahí.

### 4. Probar que todo anda

Ver el tablero con datos de ejemplo (no usa la API):

```powershell
.venv\Scripts\python.exe -m radar_vial demo
```

Abrir <http://localhost:8000> en el navegador. Para cortar: `Ctrl+C` en la terminal.

Probar que las fuentes responden (no usa la API; tarda unos 10 minutos):

```powershell
.venv\Scripts\python.exe -m radar_vial fuentes
```

Hacer una corrida real sin publicar (usa la API; con `--tope 30` cuesta unos centavos de dólar):

```powershell
.venv\Scripts\python.exe -m radar_vial diario --sin-publicar --tope 30
```

La vista previa queda en `salida\vista_previa`. Para verla:

```powershell
.venv\Scripts\python.exe -m http.server 8000 --directory salida\vista_previa
```

### 5. Correr en GitHub (una sola vez)

El repositorio es [`Sr4312/radar-vial`](https://github.com/Sr4312/radar-vial) (público).

1. En el repositorio: **Settings > Secrets and variables > Actions > Secrets > New repository secret**.
   Nombre: `ANTHROPIC_API_KEY`; valor: la clave del Observatorio.
2. **Actions > Radar Vial > Run workflow** para la primera corrida (tarda unos 30 minutos).

Desde ahí corre solo todos los días. Si un día falla, el siguiente intento (cada dos horas hasta las 18:17)
lo vuelve a probar; si ya corrió, los intentos siguientes terminan en segundos.

### 6. El tablero en la web (GitHub Pages)

El tablero se publica en **<https://sr4312.github.io/radar-vial/>** después de cada corrida diaria. Ya está
configurado: Pages publica desde GitHub Actions (**Settings > Pages > Source: GitHub Actions**) y la variable
del repositorio `PUBLICAR_PAGES` vale `true` (**Settings > Secrets and variables > Actions > Variables**).
Para dejar de publicar sin tocar el workflow, cambiar esa variable a `false`.

GitHub Pages es gratis solo en repositorios públicos: si el repositorio vuelve a privado, la publicación se
corta (con un plan pago se puede, pero el sitio igual es público).

### 6 bis. Publicar en Vercel (opcional, en lugar de GitHub Pages o además)

El repositorio ya trae `vercel.json`: Vercel sirve la carpeta `docs/` tal cual (sin instalar ni compilar) y
vuelve a publicar solo cuando una corrida cambia el tablero.

1. Entrar a [vercel.com](https://vercel.com) con la cuenta de GitHub del Observatorio.
2. **Add New > Project**, elegir `Sr4312/radar-vial` e **Import** (no hay que cambiar ninguna opción: las toma
   de `vercel.json`). Vercel pide permiso para leer el repositorio.
3. **Deploy**. El tablero queda en `https://<nombre-del-proyecto>.vercel.app` y se actualiza solo con cada
   corrida diaria.
4. Opcional: **Settings > Domains** para usar un dominio propio (por ejemplo, un subdominio de cruzroja.org.ar).

Si se usa solo Vercel, se puede apagar GitHub Pages cambiando la variable `PUBLICAR_PAGES` a `false`.

### 7. Ver el tablero sin GitHub Pages

- **Desde la computadora**: traer lo último (`git pull`) y servir la carpeta `docs`:

```powershell
.venv\Scripts\python.exe -m http.server 8000 --directory docs
```

  y abrir <http://localhost:8000>.
- Con doble clic sobre `index.html` no carga los datos: hay que servirlo por http como arriba.

---

## Comandos

| Comando | Qué hace | ¿Usa la API? |
|---|---|---|
| `python -m radar_vial demo` | Tablero con datos ficticios en <http://localhost:8000> | No |
| `python -m radar_vial fuentes` | Prueba cada búsqueda y cada medio; reporte en `salida\` | No |
| `python -m radar_vial diario` | Corrida real: recolecta, extrae, agrupa y publica en `docs\data\` | Sí |
| `python -m radar_vial diario --sin-publicar` | Igual, pero la vista previa queda en `salida\vista_previa\` | Sí |
| `python -m radar_vial diario --tope 50` | Limita cuántas notas se extraen en esa corrida | Sí |
| `python -m radar_vial reprocesar --desde AAAA-MM-DD` | Rehace las fichas y los siniestros sin volver a bajar las notas (usa los textos de los últimos 14 días) | Sí |
| `python -m radar_vial auditoria --n 30` | Dos planillas para revisar a mano: fichas y agrupación en siniestros | No |

En la computadora del Observatorio, anteponer `.venv\Scripts\` a `python` (por ejemplo,
`.venv\Scripts\python.exe -m radar_vial demo`).

Desde GitHub: **Actions > Radar Vial > Run workflow**, con las opciones *sin_publicar*, *tope* y *solo_publicar*
(publica en Pages el tablero que ya está en `docs/`, sin correr el radar; sirve tras cambiar el diseño).

---

## Revisión semanal (auditoría)

```powershell
.venv\Scripts\python.exe -m radar_vial auditoria --n 30
```

Genera en `salida\` dos planillas que abren con Excel:

- `auditoria_<fecha>.csv`: 30 fichas al azar. Abrir cada link y completar si la categoría y los datos están bien.
- `auditoria_eventos_<fecha>.csv`: siniestros armados con varias notas ("¿son el mismo siniestro?") y pares que
  quedaron separados ("¿son distintos?").

Las auditorías leen los datos guardados en la computadora: antes, traer lo último del repositorio (`git pull`).

---

## Configuración (sin tocar código)

| Archivo | Qué se cambia ahí |
|---|---|
| `config/config.yaml` | Modelos, esfuerzo, tope de notas por corrida, cupo para notas de contexto, precios, inicio de la cobertura |
| `config/consultas.yaml` | Términos de búsqueda, ciudades, búsquedas de contexto y palabras clave del prefiltro |
| `config/fuentes.yaml` | Medios: feeds, sitemaps, provincia, activo, `verificar` (lo que hay que revisar a mano) |
| `config/provincias.yaml` | Las 24 jurisdicciones: búsquedas, capital y población (Censo 2022, INDEC) |

Para sumar medios nuevos: `.venv\Scripts\python.exe scripts\descubrir_fuentes.py medio.com.ar` muestra qué feeds
y sitemaps tiene; después se agrega a mano en `config/fuentes.yaml`.

---

## Costos

Cada corrida anota tokens y costo estimado en `data/costos.jsonl` (y en el resumen de cada corrida de GitHub
Actions). Referencias medidas en noviembre de 2026:

- Filtro (Haiku): unos USD 0,05 por cada 1.800 notas candidatas.
- Extracción (Sonnet): unos USD 0,0045 por nota.
- Corridas diarias del 21 al 24-11-2026: de 365 a 383 notas extraídas, de USD 2,34 a 2,50 y de 24 a 31 minutos.
  En un día completo el filtro marca de 440 a 640 notas relevantes.

El tope de notas por corrida (`limites.max_extraccion_por_corrida`, 700) es el freno de costos: lo que no entra
queda en cola para la corrida siguiente, y lo que pasa 7 días en la cola se descarta (el registro de la corrida
avisa cuántas notas vencieron). Los reintentos de notas que ya tienen ficha de solo título no ocupan el tope.

---

## Privacidad

- El texto completo de las notas trae nombres de personas: nunca se sube al repositorio. Queda en una caché
  temporal (14 días) en la computadora o en la caché de GitHub Actions.
- Las fichas y el tablero no guardan nombres, edades exactas, ocupaciones ni vínculos familiares, y nunca
  identifican a niñas, niños o adolescentes. El tablero muestra un resumen propio y el enlace a cada nota.
- Los enlaces a las notas son públicos; algunos tienen nombres en la dirección, como los publican los medios.

---

## Estructura

```
config/          configuración editable (YAML)
radar_vial/      el programa (recolección, filtro, extracción, geografía, eventos, tablero)
docs/            el tablero que publica GitHub Pages (index.html, assets/, data/)
data/            historial, fichas, siniestros, costos y cachés públicas (lo actualiza cada corrida)
scripts/         herramientas: descubrir feeds de medios, regenerar el mapa (necesita: pip install shapely)
tests/           pruebas (sin red ni clave) y las 20 notas anotadas para medir la precisión
.github/         el workflow diario de GitHub Actions
```

Pruebas: `.venv\Scripts\python.exe -m pytest -q`. Con la variable de entorno
`RADAR_VIAL_DIAS_ADELANTE=40` corren como si hoy fuera 40 días más tarde, para encontrar fechas fijas antes de que
venzan (las pruebas corren antes de cada corrida programada). Medición de precisión (usa la API, centavos):
`.venv\Scripts\python.exe tests\medir_extraccion.py`.

Para el detalle técnico, ver [CLAUDE.md](CLAUDE.md); para las definiciones y limitaciones,
[METODOLOGIA.md](METODOLOGIA.md).

---

## Problemas comunes

- **"Falta ANTHROPIC_API_KEY"**: falta el archivo `.env` o la clave está vacía (ver paso 3).
- **El tablero dice "No se pudieron cargar los datos"**: se abrió `index.html` con doble clic. Hay que verlo por
  http (`demo`, o `python -m http.server` en la carpeta), o publicado en GitHub Pages.
- **La consola muestra signos raros en lugar de acentos**: es la consola de Windows; los archivos están bien.
- **Un medio dejó de aparecer**: correr `fuentes` y revisar su feed en `config/fuentes.yaml`.

Créditos de datos: notas de los medios enlazados en cada siniestro; población: INDEC, Censo 2022 (resultados
definitivos); cartografía: Instituto Geográfico Nacional; localidades: API Georef (datos.gob.ar).
