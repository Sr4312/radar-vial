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

El repositorio es `Sr4312/radar-vial` (privado).

1. En el repositorio: **Settings > Secrets and variables > Actions > Secrets > New repository secret**.
   Nombre: `ANTHROPIC_API_KEY`; valor: la clave del Observatorio.
2. **Actions > Radar Vial > Run workflow** para la primera corrida (tarda unos 30 minutos).

Desde ahí corre solo todos los días. Si un día falla, el siguiente intento (cada dos horas hasta las 18:17)
lo vuelve a probar; si ya corrió, los intentos siguientes terminan en segundos.

### 6. Publicar el tablero en la web (GitHub Pages)

GitHub Pages **no está disponible en repositorios privados con el plan gratuito**. Opciones: pasar el
repositorio a público, usar una cuenta u organización con plan pago, o publicar `docs/` en otro servicio de
sitios estáticos. Ojo: con un plan pago, el sitio de Pages de un repositorio privado igual es **público**.

Cuando Pages esté disponible:

1. **Settings > Pages > Build and deployment > Source: GitHub Actions**.
2. **Settings > Secrets and variables > Actions > Variables > New repository variable**: nombre
   `PUBLICAR_PAGES`, valor `true`.
3. Correr el workflow. El tablero queda en `https://<cuenta>.github.io/radar-vial/`.

### 7. Ver el tablero sin GitHub Pages

- **Desde la computadora**: traer lo último (`git pull`) y servir la carpeta `docs`:

```powershell
.venv\Scripts\python.exe -m http.server 8000 --directory docs
```

  y abrir <http://localhost:8000>.
- **Desde GitHub**: en cada corrida, **Actions > (la corrida) > Artifacts > tablero-…** baja el tablero en un
  zip. Descomprimirlo y servirlo igual que arriba (con doble clic sobre `index.html` no carga los datos).

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

Desde GitHub: **Actions > Radar Vial > Run workflow**, con las opciones *sin_publicar* y *tope*.

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
- Extracción (Sonnet): unos USD 0,006 por nota.
- Una corrida con 400 notas extraídas costó USD 2,34 y tardó 29 minutos.

El tope de notas por corrida (`limites.max_extraccion_por_corrida`) es el freno de costos: lo que no entra
queda en cola para la corrida siguiente.

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

Pruebas: `.venv\Scripts\python.exe -m pytest -q`. Medición de precisión (usa la API, centavos):
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
