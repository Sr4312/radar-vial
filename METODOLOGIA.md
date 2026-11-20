# Metodología del Radar Vial

Observatorio Humanitario · Cruz Roja Argentina

> **Qué mide y qué no.** El Radar Vial cuenta los siniestros viales **reportados en medios de prensa**
> de Argentina. No es estadística oficial. Subestima los siniestros sin víctimas o sin cobertura y las
> zonas con poca prensa local, y las cifras de víctimas de un siniestro pueden cambiar con los días.

## 1. Definiciones

- **Siniestro vial**: un hecho concreto en la vía pública en Argentina en el que intervienen uno o más
  vehículos o peatones: choques, vuelcos, atropellos, despistes, caídas de moto o bicicleta y siniestros
  con trenes en pasos a nivel. Es la unidad de análisis: diez notas sobre el mismo choque son **un**
  siniestro con diez fuentes.
- **Contexto vial**: notas sobre seguridad vial sin un siniestro concreto (controles y alcoholemia,
  cambios normativos, estadísticas oficiales o balances con cifras agregadas, estado de rutas e
  infraestructura, campañas). Se listan aparte y **no se suman** a los conteos.
- **Quedan afuera**: accidentes no viales (domésticos, laborales fuera de la vía pública, aéreos,
  náuticos), "choque" en sentido figurado, hechos de otros países, deportes de motor en competencia,
  notas sin un hecho concreto en Argentina y siniestros de hace más de 30 días (juicios, aniversarios)
  sin víctimas nuevas.
- **Fecha del siniestro**: el día en que ocurrió el hecho, no el de la nota. Si la nota no permite
  saberlo, se usa la fecha de publicación y el siniestro queda marcado como de **fecha aproximada**.
- **Víctimas**: personas fallecidas; heridas graves (descriptas como graves, en estado crítico o con
  pronóstico reservado), leves, o sin detalle de gravedad. Cada persona cuenta una sola vez. Si la nota
  no informa un dato, el dato queda vacío: nunca se estima.
- **Factores mencionados**: circunstancias que la nota menciona (alcohol, velocidad, celular, clima,
  estado de la ruta, etc.), marcadas como **presuntas** cuando la nota las presenta como hipótesis.
  Nunca se presentan como causas confirmadas ni se atribuyen culpas.

## 2. De dónde salen las notas

Todos los días se leen las notas publicadas en las últimas 48 horas en:

- **Google News**: una búsqueda por cada término (choque, accidente de tránsito, siniestro vial, vuelco,
  atropellado, motociclista murió, ruta nacional, colisión, despiste, paso a nivel) y cada una de las 24
  jurisdicciones, más búsquedas por ciudades grandes (`config/consultas.yaml`). No se combinan términos
  con "OR" porque Google News devuelve muchas menos notas (medido en noviembre de 2026).
- **Feeds RSS y sitemaps de noticias** de medios nacionales y de todas las provincias
  (`config/fuentes.yaml`). La prensa provincial y local es imprescindible: la mayoría de los siniestros
  solo los cubre el medio local.

El radar lee lo que los medios publican para lectores automáticos (feeds y sitemaps), respeta su
`robots.txt` y se identifica como "RadarVial (Observatorio Humanitario - Cruz Roja Argentina)".

## 3. Cómo se procesa cada nota

1. **Deduplicación de notas.** Una nota que llega por varias búsquedas o medios se reconoce por su URL
   canónica (sin parámetros de seguimiento ni versión AMP o móvil) o por su título, solo cuando el
   título es distintivo: títulos genéricos como "Murió un motociclista en un choque" se repiten entre
   notas distintas y no se usan para deduplicar.
2. **Filtro.** Un modelo de lenguaje económico (Claude Haiku) clasifica cada nota por su título en
   siniestro, contexto o descartar. Ante la duda deja pasar la nota.
3. **URL original y texto.** Los links de Google News no traen la URL del medio: se la busca por el título
   en el sitemap de noticias y el RSS del propio medio y, si no aparece, en el buscador público de Bing
   Noticias (solo se acepta un resultado del mismo medio y con el mismo título). Si no se encuentra o el
   medio no permite leer la página, la ficha se arma solo con el título y queda con **confianza baja**; si
   en una corrida posterior aparece la nota, la ficha se rehace con el texto completo.
4. **Extracción.** Un modelo de mejor calidad (Claude Sonnet) lee la nota y completa una ficha por
   siniestro con fecha, franja horaria, lugar, vía, tipo de siniestro, vehículos, víctimas, factores
   mencionados, grupos etarios y un resumen propio de una oración. Lo que la nota no dice queda vacío.
5. **Normalización geográfica.** Provincia, departamento y localidad se validan contra la API Georef
   (datos.gob.ar) y se guarda su centroide e identificadores oficiales. Si la localidad no aparece, se usa
   el departamento o la provincia. Si la nota no dice la provincia, se completa solo cuando hay una pista
   clara (la localidad existe en una sola provincia, el medio es de esa provincia o la nota llegó solo por
   búsquedas de esa provincia) y queda marcada como **provincia inferida**.

## 4. De notas a siniestros (agrupación en eventos)

Cada ficha se compara con los siniestros ya armados:

- **Candidatos**: misma provincia (o provincia sin identificar en una de las fichas), fecha del hecho a un
  día o menos (dos si alguna fecha es aproximada).
- **Nunca se fusionan**: provincias distintas, fechas fuera de esa ventana, rutas con distinto número,
  kilómetros muy separados en localidades distintas, o dos siniestros que una misma nota describe por
  separado. Basta que una sola nota del siniestro lo contradiga.
- **Dos esquinas distintas** de una misma ciudad tampoco se fusionan, salvo que la contradicción venga de
  una sola nota frente a la mayoría de las del siniestro (un medio puede equivocarse de calle).
- **Puntaje** por coincidencias: localidad, ruta y kilómetro, calle, vehículos, tipo de siniestro, franja
  horaria, víctimas fatales, grupos etarios. Las diferencias restan.
- **Decisión**: con puntaje alto y sin otro candidato parecido, se fusiona. En los casos dudosos (y siempre
  que la ficha se haya armado solo con el título) decide el modelo de lenguaje con las fichas y los títulos
  a la vista; solo se fusiona si lo considera el mismo siniestro con seguridad alta o media.
- **Al fusionar**: de cada dato se toma el más completo (notas con texto completo y mayor confianza
  primero). Las cifras de víctimas se toman de la nota más reciente que las informa, porque suben con el
  paso de los días (un herido que muere después). Se conservan todas las fuentes del siniestro.

Ejemplo real (primeras corridas, 20-11-2026): 380 fichas de notas publicadas entre el 13 y el 20 de
noviembre se agruparon en 169 siniestros; 77 llegaron por más de un medio y el que más, por 12.

## 5. Cómo se calculan los indicadores del tablero

- **Esta semana**: los últimos 7 días completos según la fecha del hecho, hasta el día anterior a la
  actualización. Se compara con los 7 días previos, salvo que ese período empiece antes del inicio del
  registro (ver Limitaciones). El selector permite ver 14 o 30 días, o fechas a elección.
- **Siniestros, personas fallecidas y heridas**: suma de los siniestros (no de las notas) del período, con
  las cifras de víctimas consolidadas de cada siniestro.
- **Tasa por provincia**: siniestros del período cada 100.000 habitantes, con la población total de cada
  jurisdicción del Censo Nacional de Población, Hogares y Viviendas 2022 (INDEC, resultados definitivos).
- **Mapa**: cartografía oficial del Instituto Geográfico Nacional. Los puntos marcan la localidad o el
  departamento del siniestro; los siniestros sin ese dato solo cuentan en su provincia.
- **Distribuciones**: un siniestro puede tener varios vehículos y varios factores; los "sin dato" se
  informan aparte y no se reparten.

## 6. Privacidad y ética

El Radar Vial lo publica Cruz Roja Argentina. Por eso:

- No se guardan nombres de víctimas, conductores ni testigos, ni edades exactas, ocupaciones, vínculos
  familiares u otros datos que permitan identificarlos, ni fotos.
- No se identifica de ningún modo a niñas, niños ni adolescentes.
- El texto completo de las notas no se publica ni se guarda en el repositorio: queda en una caché
  temporal de 14 días. El tablero muestra el resumen propio y el enlace a cada fuente.
- Un control automático revisa cada ficha y saca nombres y edades que se hayan colado; además, el equipo
  revisa una muestra semanal de fichas y de la agrupación en siniestros (comando `auditoria`).
- Los enlaces a las notas son públicos y algunos contienen nombres en la dirección (así los publican los
  medios).

## 7. Limitaciones

- **Cobertura de prensa**: el radar ve lo que la prensa publica. Los siniestros sin víctimas, los de zonas
  rurales y los de provincias con poca prensa digital quedan subrepresentados.
- **Desde cuándo**: el radar registra siniestros desde el 18 de noviembre de 2026. Los días anteriores solo
  tienen notas tardías sueltas: el tablero los muestra aparte y no compara contra ellos.
- **Días recientes incompletos**: las notas y las cifras de víctimas llegan con demora. Los últimos días
  siempre están incompletos, por eso la comparación con la semana anterior hay que leerla con cuidado.
- **Errores de extracción y de agrupación**: la extracción y la agrupación las hace un modelo de lenguaje
  con reglas. Su precisión se mide con 20 notas reales anotadas (la anotación está en validación por el
  equipo) y se revisa una muestra semanal, pero puede haber datos mal leídos y siniestros fusionados de más
  o de menos.
- **Siniestros conocidos solo por titulares**: cuando no se pudo leer ninguna nota completa, el siniestro
  tiene menos datos y menos confianza. En las primeras corridas fueron cerca de 3 de cada 10. El tablero
  permite excluirlos.
- **No es estadística oficial**: para cifras oficiales, consultar a la Agencia Nacional de Seguridad Vial y
  a los observatorios viales provinciales.
