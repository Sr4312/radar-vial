/* Radar Vial · tablero estático (sin backend). Lee los JSON de data/ y arma todas las vistas en el navegador.
   Los textos que vienen de los datos (resúmenes, medios, lugares) se insertan siempre como texto, nunca como HTML. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ constantes
  const C = {
    rojo: "#E73743", rojoTexto: "#C11F2A", tinta: "#231F20", pizarra: "#5E686F", linea: "#E3E6E8",
    bruma: "#F1F3F4", carga: "#F6ACB1", previo: "#8A9399", pocos: "#C9CED2", secuencial: ["#F9D2D5", "#F6ACB1", "#F1858B", "#E94E58", "#C11F2A"],
  };
  const NUM = new Intl.NumberFormat("es-AR");
  const DEC1 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const DEC2 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
  const DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre"];
  const ETIQUETAS = {
    tipo: {
      choque_frontal: "Choque frontal", choque_por_alcance: "Choque por alcance", choque_lateral: "Choque lateral",
      choque_sin_detalle: "Choque (sin detalle)", vuelco: "Vuelco", atropello: "Atropello", despiste: "Despiste",
      caida: "Caída de moto o bicicleta", tren: "Con un tren", multiple: "Choque múltiple", otro: "Otro",
    },
    vehiculo: {
      auto: "Auto", moto: "Moto", camion: "Camión", colectivo: "Colectivo", bicicleta: "Bicicleta", peaton: "Peatón",
      tren: "Tren", utilitario: "Camioneta o utilitario", otro: "Otro",
    },
    via: {
      ruta_nacional: "Ruta nacional", ruta_provincial: "Ruta provincial", autopista: "Autopista o autovía",
      urbana: "Calle o avenida", rural: "Camino rural", desconocida: "Sin dato",
    },
    // " ": espacio que no corta línea (la "h" no queda sola en otro renglón)
    franja: { madrugada: "Madrugada (0 a 6 h)", manana: "Mañana (6 a 12 h)", tarde: "Tarde (12 a 19 h)", noche: "Noche (19 a 24 h)" },
    factor: {
      alcohol: "Alcohol", velocidad: "Velocidad", celular: "Celular", clima: "Clima", estado_de_la_ruta: "Estado de la ruta",
      fatiga: "Fatiga o descompensación", sobrepaso: "Maniobra de sobrepaso", sin_casco: "Sin casco",
      sin_cinturon: "Sin cinturón", animal_suelto: "Animal suelto", semaforo_o_prioridad: "Semáforo o prioridad de paso",
      falla_mecanica: "Falla mecánica", otro: "Otro",
    },
    subtipo: {
      control_alcoholemia: "Controles", normativa: "Normativa", estadistica: "Estadística", infraestructura_rutas: "Rutas",
      campana: "Campaña", otro: "Otro",
    },
  };
  const POR_PAGINA = 20;
  const ARGENTINA = [[-55.1, -73.6], [-21.8, -53.6]];
  const MIN_CASOS_TASA = 5;
  const CONTEXTO_POR_TANDA = 25;

  const estado = {
    datos: null, desde: null, hasta: null, incluirTitulos: true, provincia: "", encuadre: null, pagina: 0, graficos: {}, mapa: null, contextoVisibles: 25,
    capaProvincias: null, capaPuntos: null, provincias: {},
  };

  // ------------------------------------------------------------------ utilidades
  const $ = (id) => document.getElementById(id);

  function el(tag, atributos, ...hijos) {
    const nodo = document.createElement(tag);
    for (const [k, v] of Object.entries(atributos || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "texto") nodo.textContent = v;
      else if (k === "clase") nodo.className = v;
      else nodo.setAttribute(k, v === true ? "" : v);
    }
    for (const h of hijos.flat(Infinity)) {
      if (h === null || h === undefined || h === false) continue;
      nodo.append(h instanceof Node ? h : document.createTextNode(String(h)));
    }
    return nodo;
  }

  function vaciar(nodo) { while (nodo.firstChild) nodo.removeChild(nodo.firstChild); return nodo; }

  function enlace(url, texto) {
    const seguro = typeof url === "string" && /^https?:\/\//i.test(url);
    return seguro ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", texto }) : el("span", { texto });
  }

  // Fechas como texto AAAA-MM-DD; se calculan en UTC para no depender de la zona horaria del navegador.
  const fecha = (s) => { const [a, m, d] = s.split("-").map(Number); return new Date(Date.UTC(a, m - 1, d)); };
  const iso = (f) => f.toISOString().slice(0, 10);
  const sumarDias = (s, n) => { const f = fecha(s); f.setUTCDate(f.getUTCDate() + n); return iso(f); };
  const diasEntre = (a, b) => Math.round((fecha(b) - fecha(a)) / 86400000);
  const diaSemana = (s) => (fecha(s).getUTCDay() + 6) % 7;  // 0 = lunes
  const fechaCorta = (s) => { const f = fecha(s); return `${f.getUTCDate()}/${f.getUTCMonth() + 1}`; };
  const fechaLarga = (s) => { const f = fecha(s); return `${DIAS[diaSemana(s)]} ${f.getUTCDate()} de ${MESES[f.getUTCMonth()]}`; };
  const fechaCompleta = (s) => { const f = fecha(s); return `${f.getUTCDate()}/${f.getUTCMonth() + 1}/${f.getUTCFullYear()}`; };
  const plural = (n, uno, varios) => `${NUM.format(n)} ${n === 1 ? uno : varios}`;

  function diasDelRango(desde, hasta) {
    const dias = [];
    for (let s = desde; s <= hasta; s = sumarDias(s, 1)) dias.push(s);
    return dias;
  }

  // ------------------------------------------------------------------ carga
  async function cargar() {
    const archivos = ["meta", "eventos", "serie_diaria", "resumen_semana", "contexto"];
    const respuestas = await Promise.all(archivos.map((a) => fetch(`data/${a}.json`, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(`${a}.json: ${r.status}`); return r.json(); })));
    const datos = Object.fromEntries(archivos.map((a, i) => [a, respuestas[i]]));
    // eventos.json omite los campos vacíos para pesar menos: acá se completan los valores por defecto
    const DEFECTO = { vehiculos: [], factores: [], grupos_etarios: [], fuentes: [], fallecidos: null, heridos: null,
      solo_titulos: false, provincia_inferida: false, fecha_aproximada: false, provincia: null };
    datos.eventos = datos.eventos.map((e) => ({ ...DEFECTO, ...e, n_fuentes: e.n_fuentes || (e.fuentes || []).length }));
    datos.geo = await fetch("data/provincias.geojson").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    return datos;
  }

  // ------------------------------------------------------------------ selección
  function eventosDelRango() {
    const { desde, hasta, incluirTitulos } = estado;
    return estado.datos.eventos.filter((e) => e.fecha >= desde && e.fecha <= hasta && (incluirTitulos || !e.solo_titulos)
      && (!estado.provincia || e.provincia === estado.provincia));
  }

  /** Las 6 cifras de un día de la serie: las de la provincia elegida en el filtro general, o las del país. */
  const CERO6 = [0, 0, 0, 0, 0, 0];
  const filaDia = (v, todas = false) => (estado.provincia && !todas ? (v.provincias[estado.provincia] || CERO6) : v.total);

  /** Totales de la serie diaria (histórico completo) entre dos fechas, respetando la casilla de titulares. */
  function sumarSerie(desde, hasta, todas = false) {
    const t = { siniestros: 0, fallecidos: 0, heridos: 0, provincias: {} };
    const dias = estado.datos.serie_diaria.dias;
    for (const [dia, v] of Object.entries(dias)) {
      if (dia < desde || dia > hasta) continue;
      const [n, m, h, nt, mt, ht] = filaDia(v, todas);
      t.siniestros += n - (estado.incluirTitulos ? 0 : nt);
      t.fallecidos += m - (estado.incluirTitulos ? 0 : mt);
      t.heridos += h - (estado.incluirTitulos ? 0 : (ht || 0));
      for (const [pid, fila] of Object.entries(v.provincias)) {
        const p = t.provincias[pid] || (t.provincias[pid] = { siniestros: 0, fallecidos: 0 });
        p.siniestros += fila[0] - (estado.incluirTitulos ? 0 : fila[3]);
        p.fallecidos += fila[1] - (estado.incluirTitulos ? 0 : fila[4]);
      }
    }
    t.provinciasConCasos = Object.values(t.provincias).filter((p) => p.siniestros > 0).length;
    return t;
  }

  function serieDiaria(dias) {
    const datos = estado.datos.serie_diaria.dias;
    return dias.map((d) => {
      const v = datos[d];
      if (!v) return { siniestros: 0, fallecidos: 0 };
      const [n, m, , nt, mt] = filaDia(v);
      return { siniestros: n - (estado.incluirTitulos ? 0 : nt), fallecidos: m - (estado.incluirTitulos ? 0 : mt) };
    });
  }

  // ------------------------------------------------------------------ indicadores
  const BASE_MINIMA_PCT = 20;   // con menos casos que esto, un porcentaje engaña ("de 2 a 4: 100% más")

  /** Variación entre dos cantidades de días ya cerrados. `comparacion` es null si no hay con qué comparar. */
  function textoVariacion(actual, previo, comparacion) {
    if (!comparacion) return el("span", { texto: "Sin comparación todavía" });
    const { dias, parcial } = comparacion;
    const periodo = dias === 1 ? "el día anterior" : `los ${dias} días anteriores`;
    const tramo = parcial ? (dias === 1 ? "en el día ya cerrado " : `en los ${dias} días ya cerrados `) : "";
    if (actual === previo) return el("span", {}, `Igual ${tramo}que en ${periodo} (${NUM.format(previo)})`);
    const sube = actual > previo;
    const flecha = sube ? "▲" : "▼";
    const cuanto = previo >= BASE_MINIMA_PCT
      ? `${DEC1.format(Math.abs((100 * (actual - previo)) / previo))}%`
      : NUM.format(Math.abs(actual - previo));
    return el("span", {}, el("b", { clase: sube ? "sube" : "baja" }, el("span", { clase: "flecha", "aria-hidden": "true", texto: flecha }), ` ${cuanto} ${sube ? "más" : "menos"}`),
      ` ${tramo}que en ${periodo} (${NUM.format(previo)})`);
  }

  function dibujarIndicadores() {
    const { desde, hasta } = estado;
    const meta = estado.datos.meta;
    const actual = sumarSerie(desde, hasta);
    const inicio = meta.inicio_cobertura;
    // Se comparan solo días cerrados: los últimos (y el día en curso) todavía reciben notas, y contra un período
    // completo siempre darían "menos".
    const ultimoCerrado = sumarDias(meta.corte, -(meta.dias_en_carga || 0));
    const hastaCerrado = hasta < ultimoCerrado ? hasta : ultimoCerrado;
    const n = diasEntre(desde, hastaCerrado) + 1;
    let comparacion = null, cerrado = actual, previo = actual;
    const sinPrevio = n >= 1 && inicio && sumarDias(desde, -n) < inicio;
    if (n >= 1 && !sinPrevio) {
      cerrado = hastaCerrado === hasta ? actual : sumarSerie(desde, hastaCerrado);
      previo = sumarSerie(sumarDias(desde, -n), sumarDias(desde, -1));
      comparacion = { dias: n, parcial: hastaCerrado !== hasta };
    }
    const tarjetas = [
      [actual.siniestros, "Siniestros reportados", cerrado.siniestros, previo.siniestros],
      [actual.fallecidos, "Personas fallecidas", cerrado.fallecidos, previo.fallecidos],
      [actual.heridos, "Personas heridas", cerrado.heridos, previo.heridos],
      [actual.provinciasConCasos, "Provincias con casos", cerrado.provinciasConCasos, previo.provinciasConCasos],
    ];
    const caja = vaciar($("kpis"));
    const prov = estado.provincias[estado.provincia];
    // Cuántos siniestros del período se conocen solo por el titular (lo que suma o quita la casilla)
    let todos = 0, soloTitular = 0;
    for (const [dia, v] of Object.entries(estado.datos.serie_diaria.dias)) {
      if (dia < desde || dia > hasta) continue;
      const fila = filaDia(v);
      todos += fila[0]; soloTitular += fila[3];
    }
    $("ayuda-titulos").textContent = !soloTitular ? "En este período todos los siniestros tienen al menos una nota leída completa."
      : `De ${soloTitular === 1 ? "1 siniestro" : `${NUM.format(soloTitular)} siniestros`} de los ${NUM.format(todos)} del período solo se pudo leer el titular de la nota, no el texto: tienen menos datos (a veces sin lugar ni víctimas). ${estado.incluirTitulos ? "Están contados; desmarcá la casilla para dejarlos afuera." : "No están contados."}`;
    for (const [valor, etiqueta, valorCerrado, ant] of tarjetas) {
      if (prov && etiqueta === "Provincias con casos") {
        // con una provincia elegida, la cuarta tarjeta es su tasa (si hay casos suficientes para calcularla)
        const hayTasa = actual.siniestros >= MIN_CASOS_TASA;
        caja.append(el("div", { clase: "tarjeta kpi" },
          el("div", { clase: "valor", texto: hayTasa ? DEC2.format((100000 * actual.siniestros) / prov.poblacion) : "Sin tasa" }),
          el("div", { clase: "etiqueta", texto: "Siniestros cada 100.000 habitantes" }),
          el("div", { clase: "delta", texto: hayTasa ? `Población: ${NUM.format(prov.poblacion)} (Censo 2022)` : `Con menos de ${MIN_CASOS_TASA} siniestros no se calcula` })));
        continue;
      }
      caja.append(el("div", { clase: "tarjeta kpi" },
        el("div", { clase: "valor", texto: NUM.format(valor) }),
        el("div", { clase: "etiqueta", texto: etiqueta === "Provincias con casos" ? `${etiqueta} (de 24)` : etiqueta }),
        el("div", { clase: "delta" }, textoVariacion(valorCerrado, ant, comparacion))));
    }
    // Aviso sobre los días que todavía se completan y sobre la cobertura de los detalles
    const enCarga = (estado.datos.resumen_semana.dias_en_carga || []).filter((d) => d >= desde && d <= hasta);
    const partes = [];
    if (prov) partes.push(`Se muestran solo los siniestros de ${prov.nombre}.`);
    if (hasta > meta.corte) partes.push(`El ${fechaCorta(hasta)} todavía no terminó: sus cifras son parciales.`);
    if (!comparacion) {
      partes.push(sinPrevio ? "Todavía no hay un período anterior completo para comparar."
        : "El período elegido no tiene días cerrados para comparar.");
    }
    if (inicio && desde < inicio) partes.push(`El radar registra siniestros desde el ${fechaCompleta(inicio)}: los días anteriores tienen solo notas sueltas.`);
    if (enCarga.length) {
      partes.push(`${enCarga.length === 1 ? "El día" : "Los días"} ${enCarga.map(fechaCorta).join(" y ")} todavía se ${enCarga.length === 1 ? "está" : "están"} completando: las notas y las cifras de víctimas siguen llegando, por eso la comparación usa solo los días ya cerrados.`);
    }
    const primerDia = sumarDias(estado.datos.meta.corte, -(estado.datos.meta.dias_eventos - 1));
    if (desde < primerDia) partes.push(`El mapa de puntos, las distribuciones, los rankings de rutas y la tabla muestran los siniestros desde el ${fechaCorta(primerDia)}.`);
    $("aviso-carga").textContent = partes.join(" ");
    $("aviso-carga").hidden = !partes.length;
  }

  // ------------------------------------------------------------------ gráficos (Chart.js)
  // Valor al final de cada barra, en color de texto (nunca en el color del dato)
  const pluginValores = {
    id: "valores",
    afterDatasetsDraw(chart, _args, opciones) {
      if (!opciones || !opciones.mostrar) return;
      const { ctx } = chart;
      const horizontal = chart.options.indexAxis === "y";
      ctx.save();
      ctx.fillStyle = C.tinta;
      ctx.font = "600 12px 'Encode Sans', Arial, sans-serif";
      chart.getDatasetMeta(0).data.forEach((barra, i) => {
        const v = chart.data.datasets[0].data[i];
        if (!v) return;
        const texto = NUM.format(v);
        if (horizontal) { ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(texto, barra.x + 6, barra.y); }
        else { ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(texto, barra.x, barra.y - 4); }
      });
      ctx.restore();
    },
  };

  function configurarChart() {
    Chart.defaults.font.family = "'Encode Sans', 'Helvetica Neue', Arial, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = C.pizarra;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation.duration = 250;
    Chart.defaults.plugins.legend.display = false;
    Object.assign(Chart.defaults.plugins.tooltip, {
      backgroundColor: C.tinta, padding: 10, cornerRadius: 6, displayColors: false,
      titleFont: { weight: "600" }, bodyFont: { weight: "700", size: 13 },
    });
    Chart.register(pluginValores);
  }

  /** Parte una etiqueta larga en renglones (Chart.js dibuja cada elemento del arreglo en una línea). */
  function partirEtiqueta(texto, largo = 16) {
    const palabras = String(texto).split(" ");
    const lineas = [];
    let actual = "";
    for (const p of palabras) {
      if (actual && (actual + " " + p).length > largo) { lineas.push(actual); actual = p; }
      else actual = actual ? actual + " " + p : p;
    }
    if (actual) lineas.push(actual);
    return lineas.length > 1 ? lineas : texto;
  }

  function graficoBarras(id, etiquetas, valores, { horizontal = false, colores = null, bordes = 0, titulos = null, unidad = "", valoresVisibles = true } = {}) {
    if (estado.graficos[id]) estado.graficos[id].destroy();
    const lienzo = $(id);
    const maximo = Math.max(1, ...valores);
    titulos = titulos || etiquetas.slice();
    estado.graficos[id] = new Chart(lienzo, {
      type: "bar",
      data: {
        labels: horizontal ? etiquetas.map((e) => partirEtiqueta(e)) : etiquetas,
        datasets: [{
          data: valores, backgroundColor: colores || C.rojo, hoverBackgroundColor: colores || C.rojoTexto,
          borderColor: C.rojo, borderWidth: bordes,
          borderRadius: horizontal ? { topRight: 4, bottomRight: 4 } : { topLeft: 4, topRight: 4 },
          borderSkipped: horizontal ? "left" : "bottom", maxBarThickness: 24, categoryPercentage: 0.8, barPercentage: 0.9,
        }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        layout: { padding: horizontal ? { right: 36 } : { top: 18 } },
        scales: {
          x: horizontal
            ? { beginAtZero: true, suggestedMax: maximo * 1.1, grid: { color: C.linea }, border: { display: false }, ticks: { precision: 0 } }
            : { grid: { display: false }, border: { color: C.linea }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 8 } },
          y: horizontal
            ? { grid: { display: false }, border: { color: C.linea }, ticks: { color: C.tinta, autoSkip: false } }
            : { beginAtZero: true, suggestedMax: maximo * 1.15, grid: { color: C.linea }, border: { display: false }, ticks: { precision: 0 } },
        },
        plugins: {
          valores: { mostrar: valoresVisibles },
          tooltip: {
            callbacks: {
              title: (items) => titulos[items[0].dataIndex],
              label: (item) => `${NUM.format(item.raw)}${unidad ? " " + unidad : ""}`,
            },
          },
        },
      },
    });
  }

  function tablaSimple(contenedor, encabezados, filas, numericas = []) {
    const tabla = el("table", {},
      el("thead", {}, el("tr", {}, encabezados.map((h, i) => el("th", { clase: numericas.includes(i) ? "num" : null, texto: h })))),
      el("tbody", {}, filas.map((f) => el("tr", {}, f.map((c, i) => el("td", { clase: numericas.includes(i) ? "num" : null },
        c instanceof Node ? c : String(c)))))));
    vaciar(contenedor).append(tabla);
  }

  // ------------------------------------------------------------------ series por día
  function dibujarSeries() {
    const dias = diasDelRango(estado.desde, estado.hasta);
    const serie = serieDiaria(dias);
    const enCarga = new Set(estado.datos.resumen_semana.dias_en_carga || []);
    const inicio = estado.datos.meta.inicio_cobertura;
    const nota = (d) => (inicio && d < inicio ? " (antes del inicio del registro)" : enCarga.has(d) ? " (todavía se completa)" : "");
    const colores = dias.map((d) => (inicio && d < inicio ? C.previo : enCarga.has(d) ? C.carga : C.rojo));
    const bordes = dias.map((d) => (enCarga.has(d) ? 2 : 0));   // el rosa claro solo no llega a 3:1 de contraste
    const etiquetas = dias.map(fechaCorta);
    const titulos = dias.map((d) => fechaLarga(d) + nota(d));
    const pocos = dias.length <= 14;
    graficoBarras("g-siniestros-dia", etiquetas, serie.map((s) => s.siniestros), { colores, bordes, titulos, unidad: "siniestros", valoresVisibles: pocos });
    graficoBarras("g-fallecidos-dia", etiquetas, serie.map((s) => s.fallecidos), { colores, bordes, titulos, unidad: "personas fallecidas", valoresVisibles: pocos });
    tablaSimple($("tabla-dias"), ["Día", "Siniestros", "Personas fallecidas"],
      dias.map((d, i) => [fechaLarga(d) + nota(d), NUM.format(serie[i].siniestros), NUM.format(serie[i].fallecidos)]), [1, 2]);
  }

  // ------------------------------------------------------------------ distribuciones
  function contar(eventos, clave) {
    const cuenta = {};
    for (const e of eventos) for (const v of [].concat(clave(e) || [])) cuenta[v] = (cuenta[v] || 0) + 1;
    return cuenta;
  }

  function tarjetaDistribucion(contenedor, { id, titulo, sub, pares, nota, horizontal = true }) {
    const alto = horizontal ? Math.max(130, pares.length * 36 + 34) : 220;
    const tarjeta = el("article", { clase: "tarjeta" },
      el("h2", { texto: titulo }), el("p", { clase: "sub", texto: sub }));
    if (!pares.length) {
      tarjeta.append(el("p", { clase: "nota", texto: "Sin datos en el período elegido." }));
      contenedor.append(tarjeta);
      return;
    }
    const lienzo = el("div", { clase: "lienzo", style: `height:${alto}px` },
      el("canvas", { id, role: "img", "aria-label": `${titulo}: ${pares.map(([e, v]) => `${e} ${v}`).join(", ")}` }));
    const tabla = el("div", { clase: "tabla-envoltura" });
    tarjeta.append(lienzo);
    if (nota) tarjeta.append(el("p", { clase: "nota", texto: nota }));
    tarjeta.append(el("details", { clase: "datos" }, el("summary", { texto: "Ver datos" }), tabla));
    contenedor.append(tarjeta);
    graficoBarras(id, pares.map((p) => p[0]), pares.map((p) => p[1]), { horizontal, unidad: "siniestros" });
    tablaSimple(tabla, ["Categoría", "Siniestros"], pares.map(([e, v]) => [e, NUM.format(v)]), [1]);
  }

  function ordenarPares(cuenta, etiquetas, orden = null) {
    const claves = orden || Object.keys(cuenta).sort((a, b) => cuenta[b] - cuenta[a]);
    return claves.filter((k) => cuenta[k]).map((k) => [etiquetas[k] || k, cuenta[k]]);
  }

  function dibujarDistribuciones(eventos) {
    for (const id of Object.keys(estado.graficos)) {
      if (id.startsWith("d-")) { estado.graficos[id].destroy(); delete estado.graficos[id]; }
    }
    const caja = vaciar($("distribuciones"));
    const total = eventos.length;
    const tipos = contar(eventos, (e) => e.tipo);
    tarjetaDistribucion(caja, { id: "d-tipo", titulo: "Tipo de siniestro", sub: "Siniestros según cómo ocurrieron.",
      pares: ordenarPares(tipos, ETIQUETAS.tipo) });
    const vehiculos = contar(eventos, (e) => e.vehiculos);
    tarjetaDistribucion(caja, { id: "d-vehiculos", titulo: "Vehículos involucrados", sub: "Un siniestro puede involucrar varios tipos.",
      pares: ordenarPares(vehiculos, ETIQUETAS.vehiculo),
      nota: `Sin dato de vehículos: ${NUM.format(eventos.filter((e) => !e.vehiculos.length).length)} de ${NUM.format(total)}.` });
    const vias = contar(eventos, (e) => (e.tipo_via && e.tipo_via !== "desconocida" ? e.tipo_via : null));
    tarjetaDistribucion(caja, { id: "d-via", titulo: "Tipo de vía", sub: "Dónde ocurrieron.", pares: ordenarPares(vias, ETIQUETAS.via),
      nota: `Sin dato: ${NUM.format(eventos.filter((e) => !e.tipo_via || e.tipo_via === "desconocida").length)} de ${NUM.format(total)}.` });
    const franjas = contar(eventos, (e) => (e.franja && e.franja !== "desconocida" ? e.franja : null));
    tarjetaDistribucion(caja, { id: "d-franja", titulo: "Franja horaria", sub: "Momento del día del siniestro.",
      pares: ordenarPares(franjas, ETIQUETAS.franja, ["madrugada", "manana", "tarde", "noche"]),
      nota: `Sin dato: ${NUM.format(eventos.filter((e) => !e.franja || e.franja === "desconocida").length)} de ${NUM.format(total)}.` });
    const conFecha = eventos.filter((e) => !e.fecha_aproximada);
    const dias = contar(conFecha, (e) => String(diaSemana(e.fecha)));
    tarjetaDistribucion(caja, { id: "d-dia", titulo: "Día de la semana", sub: "Según la fecha del hecho.", horizontal: false,
      pares: [0, 1, 2, 3, 4, 5, 6].map((d) => [DIAS_CORTOS[d], dias[String(d)] || 0]),
      nota: `Sin fecha precisa: ${NUM.format(total - conFecha.length)} de ${NUM.format(total)}.` });
    const factores = contar(eventos, (e) => e.factores.map((f) => f.factor));
    const presuntos = contar(eventos, (e) => e.factores.filter((f) => f.presunto).map((f) => f.factor));
    const conFactor = eventos.filter((e) => e.factores.length).length;
    tarjetaDistribucion(caja, { id: "d-factores", titulo: "Factores mencionados",
      sub: "Lo que mencionan las notas, muchas veces como hipótesis. No son causas confirmadas.",
      pares: ordenarPares(factores, ETIQUETAS.factor),
      nota: `${NUM.format(conFactor)} de ${NUM.format(total)} siniestros mencionan algún factor. Presuntos: ${Object.entries(presuntos)
        .sort((a, b) => b[1] - a[1]).map(([k, v]) => `${(ETIQUETAS.factor[k] || k).toLowerCase()} ${NUM.format(v)}`).join(", ") || "ninguno"}.` });
  }

  // ------------------------------------------------------------------ mapa
  function clasesTasa(tasas) {
    const positivas = tasas.filter((t) => t > 0).sort((a, b) => a - b);
    if (!positivas.length) return [];
    const cortes = [];
    for (let i = 1; i < 5; i++) cortes.push(positivas[Math.min(positivas.length - 1, Math.floor((i * positivas.length) / 5))]);
    return [...new Set(cortes)].sort((a, b) => a - b);
  }

  function colorTasa(tasa, cortes) {
    if (!tasa) return C.bruma;
    let i = 0;
    while (i < cortes.length && tasa > cortes[i]) i++;
    return C.secuencial[Math.min(i, C.secuencial.length - 1)];
  }

  function iniciarMapa() {
    if (estado.mapa || !window.L) return;
    const mapa = L.map("mapa", { scrollWheelZoom: false, zoomSnap: 0.25, attributionControl: true });
    mapa.attributionControl.setPrefix('<a href="https://leafletjs.com" rel="noopener">Leaflet</a>');   // sin la bandera que agrega por defecto
    mapa.fitBounds(ARGENTINA, { padding: [4, 4] });
    // el contenedor termina de medir cuando cargan las fuentes y la grilla: se vuelve a encuadrar
    setTimeout(() => { mapa.invalidateSize(); if (!estado.provincia) mapa.fitBounds(ARGENTINA, { padding: [4, 4] }); }, 150);
    L.tileLayer("https://wms.ign.gob.ar/geoserver/gwc/service/tms/1.0.0/capabaseargenmap@EPSG%3A3857@png/{z}/{x}/{y}.png", {
      tms: true, minZoom: 3, maxZoom: 15,
      attribution: '<a href="https://www.ign.gob.ar/" rel="noopener">Instituto Geográfico Nacional</a>',
    }).addTo(mapa);
    estado.mapa = mapa;
  }

  function popupEventos(lista) {
    const caja = el("div");
    lista.slice(0, 4).forEach((e, i) => {
      if (i) caja.append(el("hr", { style: "border:0;border-top:1px solid #E3E6E8;margin:8px 0" }));
      caja.append(el("div", {}, el("b", { texto: `${fechaCorta(e.fecha)} · ${ETIQUETAS.tipo[e.tipo] || "Siniestro"}` })),
        el("div", { texto: e.resumen || "" }),
        el("div", { style: "color:#5E686F", texto: plural(e.n_fuentes, "fuente", "fuentes") }));
    });
    if (lista.length > 4) caja.append(el("div", { style: "margin-top:6px;color:#5E686F", texto: `Y ${plural(lista.length - 4, "siniestro más", "siniestros más")} en este lugar` }));
    return caja;
  }

  function dibujarMapa(eventos) {
    iniciarMapa();
    if (!estado.mapa) return;
    const totales = sumarSerie(estado.desde, estado.hasta, true);   // el mapa siempre pinta todas las provincias
    const filas = estado.datos.meta.provincias.map((p) => {
      const t = totales.provincias[p.id] || { siniestros: 0, fallecidos: 0 };
      return { ...p, siniestros: t.siniestros, fallecidos: t.fallecidos, tasa: (100000 * t.siniestros) / p.poblacion };
    });
    const porId = Object.fromEntries(filas.map((f) => [f.id, f]));
    // Con pocos siniestros la tasa salta por un solo caso (y por cuánta prensa local hay): no se pinta.
    const pocos = (f) => f && f.siniestros > 0 && f.siniestros < MIN_CASOS_TASA;
    const colorProvincia = (f) => (pocos(f) ? C.pocos : colorTasa(f && f.siniestros ? f.tasa : 0, cortes));
    const cortes = clasesTasa(filas.filter((f) => !pocos(f)).map((f) => f.tasa));
    if (estado.capaProvincias) estado.capaProvincias.remove();
    if (estado.datos.geo) {
      estado.capaProvincias = L.geoJSON(estado.datos.geo, {
        style: (f) => (f.properties.id === estado.provincia
          ? { fillColor: colorProvincia(porId[f.properties.id]), fillOpacity: 0.78, color: C.tinta, weight: 2.5 }
          : { fillColor: colorProvincia(porId[f.properties.id]), fillOpacity: estado.provincia ? 0.35 : 0.78, color: "#FFFFFF", weight: 1 }),
        onEachFeature: (f, capa) => {
          const p = porId[f.properties.id];
          if (!p) return;
          capa.bindTooltip(`${p.nombre}: ${plural(p.siniestros, "siniestro", "siniestros")} · ${pocos(p) ? "pocos casos para calcular una tasa" : `${DEC2.format(p.tasa)} cada 100.000 hab.`}`, { sticky: true });
          const elegida = () => f.properties.id === estado.provincia;
          capa.on({
            mouseover: () => capa.setStyle({ weight: 2.5, color: C.tinta }),
            mouseout: () => { if (!elegida()) capa.setStyle({ weight: 1, color: "#FFFFFF" }); },
            // un clic en la provincia la elige en el filtro general; otro clic la quita
            click: () => elegirProvincia(elegida() ? "" : f.properties.id),
          });
        },
      }).addTo(estado.mapa);
      // encuadre: la provincia elegida o el país (solo cuando cambia, para no mover el mapa en cada filtro)
      if (estado.encuadre !== estado.provincia) {
        estado.encuadre = estado.provincia;
        let limites = null;
        estado.capaProvincias.eachLayer((capa) => {
          if (capa.feature.properties.id !== estado.provincia) return;
          limites = limites ? limites.extend(capa.getBounds()) : capa.getBounds();
        });
        estado.mapa.fitBounds(limites || ARGENTINA, { padding: [12, 12] });
      }
    }
    // Puntos: un círculo por lugar (los siniestros del mismo lugar se agrupan)
    if (estado.capaPuntos) estado.capaPuntos.remove();
    const lugares = {};
    for (const e of eventos) {
      if (e.lat == null || e.lon == null || !["localidad", "departamento"].includes(e.nivel_geo)) continue;
      const clave = `${e.lat.toFixed(3)},${e.lon.toFixed(3)}`;
      (lugares[clave] || (lugares[clave] = [])).push(e);
    }
    estado.capaPuntos = L.layerGroup(Object.values(lugares).map((lista) => {
      const fatal = lista.some((e) => (e.fallecidos || 0) > 0);
      return L.circleMarker([lista[0].lat, lista[0].lon], {
        radius: Math.min(5 + 2 * Math.sqrt(lista.length - 1), 14), weight: 2, color: fatal ? "#FFFFFF" : C.rojo,
        fillColor: fatal ? C.rojoTexto : "#FFFFFF", fillOpacity: 1,
      }).bindPopup(popupEventos(lista.sort((a, b) => b.fecha.localeCompare(a.fecha))));
    })).addTo(estado.mapa);
    // Escala del mapa
    const escala = vaciar($("escala-mapa"));
    escala.append(el("span", { texto: "Siniestros cada 100.000 hab.:" }), " ",
      el("span", { clase: "paso", style: `background:${C.bruma}` }), el("span", { texto: " 0 " }),
      el("span", { clase: "paso", style: `background:${C.pocos}` }), el("span", { texto: ` Menos de ${MIN_CASOS_TASA} siniestros ` }));
    const limites = [0, ...cortes];
    C.secuencial.slice(0, cortes.length + 1).forEach((color, i) => {
      const desde = limites[i];
      escala.append(el("span", { clase: "paso", style: `background:${color}` }),
        el("span", { texto: i < cortes.length ? ` Hasta ${DEC2.format(cortes[i])} ` : desde ? ` Más de ${DEC2.format(desde)} ` : " Con siniestros " }));
    });
    // Tabla del mapa (acceso sin mapa)
    tablaSimple($("tabla-mapa"), ["Provincia", "Siniestros", "Fallecidos", "Cada 100.000 hab."],
      filas.slice().sort((a, b) => b.tasa - a.tasa).map((f) => [f.nombre, NUM.format(f.siniestros), NUM.format(f.fallecidos), DEC2.format(f.tasa)]), [1, 2, 3]);
    return filas;
  }

  // ------------------------------------------------------------------ rankings
  function dibujarRankings(eventos, filasProvincias) {
    const sinProvincia = eventos.filter((e) => !e.provincia).length;
    const top = (filasProvincias || []).filter((f) => f.siniestros > 0).sort((a, b) => b.siniestros - a.siniestros || b.fallecidos - a.fallecidos).slice(0, 10);
    const cajaProv = $("ranking-provincias");
    if (!top.length) vaciar(cajaProv).append(el("p", { clase: "nota", texto: "Sin siniestros en el período elegido." }));
    else {
      tablaSimple(cajaProv, ["Provincia", "Siniestros", "Fallecidos", "Cada 100.000 hab."],
        top.map((f) => [f.nombre, NUM.format(f.siniestros), NUM.format(f.fallecidos), DEC2.format(f.tasa)]), [1, 2, 3]);
      cajaProv.querySelector("table").classList.add("ranking");
    }
    if (sinProvincia) cajaProv.append(el("p", { clase: "nota", texto: `${plural(sinProvincia, "siniestro", "siniestros")} sin provincia identificada no entran en el ranking.` }));
    const rutas = {};
    for (const e of eventos) {
      if (!e.ruta) continue;
      const r = rutas[e.ruta] || (rutas[e.ruta] = { siniestros: 0, fallecidos: 0, provincias: new Set() });
      r.siniestros += 1; r.fallecidos += e.fallecidos || 0;
      if (e.provincia && estado.provincias[e.provincia]) r.provincias.add(estado.provincias[e.provincia].nombre);
    }
    const topRutas = Object.entries(rutas).sort((a, b) => b[1].siniestros - a[1].siniestros || b[1].fallecidos - a[1].fallecidos).slice(0, 10);
    const cajaRutas = $("ranking-rutas");
    if (!topRutas.length) vaciar(cajaRutas).append(el("p", { clase: "nota", texto: "Ninguna nota del período nombra una ruta." }));
    else {
      tablaSimple(cajaRutas, ["Ruta", "Siniestros", "Fallecidos", "Provincias"],
        topRutas.map(([ruta, r]) => [ruta, NUM.format(r.siniestros), NUM.format(r.fallecidos), [...r.provincias].sort().join(", ")]), [1, 2]);
      cajaRutas.querySelector("table").classList.add("ranking");
    }
  }

  // ------------------------------------------------------------------ tabla de siniestros
  function textoVictimas(e) {
    const partes = [];
    if (e.fallecidos != null) partes.push(e.fallecidos ? plural(e.fallecidos, "persona fallecida", "personas fallecidas") : "Sin personas fallecidas");
    if (e.heridos != null) partes.push(e.heridos ? plural(e.heridos, "persona herida", "personas heridas") : "Sin personas heridas");
    return partes.length ? partes.join(" · ") : "Sin datos de víctimas";
  }

  function filtrosTabla(eventos) {
    const t = $("f-tipo").value, v = $("f-vehiculo").value, fatales = $("f-fatales").value, via = $("f-via").value;
    const fuentes = $("f-fuentes").value;
    return eventos.filter((e) => (!t || e.tipo === t) && (!via || (e.tipo_via || "desconocida") === via)
      && (!fuentes || (fuentes === "varias" ? e.n_fuentes > 1 : e.n_fuentes === 1))
      && (!v || e.vehiculos.includes(v))
      && (!fatales || (fatales === "con" ? (e.fallecidos || 0) > 0 : !(e.fallecidos > 0))));
  }

  function dibujarTabla(eventos) {
    const filtrados = filtrosTabla(eventos).sort((a, b) => b.fecha.localeCompare(a.fecha) || (b.n_fuentes - a.n_fuentes));
    const paginas = Math.max(1, Math.ceil(filtrados.length / POR_PAGINA));
    estado.pagina = Math.min(estado.pagina, paginas - 1);
    const pagina = filtrados.slice(estado.pagina * POR_PAGINA, (estado.pagina + 1) * POR_PAGINA);
    const caja = vaciar($("tabla-eventos"));
    $("n-lista").textContent = filtrados.length === eventos.length ? plural(eventos.length, "siniestro", "siniestros")
      : `${NUM.format(filtrados.length)} de ${plural(eventos.length, "siniestro", "siniestros")}`;
    if (!pagina.length) {
      caja.append(el("p", { clase: "nota", texto: "No hay siniestros con estos filtros en el período elegido." }));
    } else {
      const filas = pagina.map((e) => {
        const prov = estado.provincias[e.provincia];
        const lugar = [e.localidad, prov ? prov.nombre : "Sin provincia identificada"].filter(Boolean).join(", ");
        const marcas = [];
        if (e.solo_titulos) marcas.push(el("span", { clase: "marca", texto: "Solo titulares" }));
        if (e.provincia_inferida) marcas.push(el("span", { clase: "marca", texto: "Provincia inferida" }));
        if (e.fecha_aproximada) marcas.push(el("span", { clase: "marca", texto: "Fecha aproximada" }));
        const fuentes = e.fuentes.slice(0, 6).map((f) => enlace(f.url, f.medio || "Nota"));
        if (e.n_fuentes > 6) fuentes.push(el("span", { texto: plural(e.n_fuentes - 6, "fuente más", "fuentes más") }));
        return el("tr", {},
          el("td", { "data-titulo": "Fecha", clase: "num", texto: fechaCorta(e.fecha) }),
          el("td", { "data-titulo": "Lugar" }, el("div", { clase: "lugar", texto: lugar }), e.via ? el("div", { clase: "via", texto: e.via }) : null),
          el("td", { "data-titulo": "Tipo", texto: ETIQUETAS.tipo[e.tipo] || "Sin dato" }),
          el("td", { "data-titulo": "Vehículos", texto: e.vehiculos.map((v) => ETIQUETAS.vehiculo[v] || v).join(", ") || "Sin dato" }),
          el("td", { "data-titulo": "Víctimas", texto: textoVictimas(e) }),
          el("td", { "data-titulo": "Resumen", clase: "resumen" }, el("div", { texto: e.resumen || "" }), marcas),
          el("td", { "data-titulo": "Fuentes", clase: "fuentes" }, fuentes));
      });
      caja.append(el("table", { clase: "eventos" },
        el("thead", {}, el("tr", {}, ["Fecha", "Lugar", "Tipo", "Vehículos", "Víctimas", "Resumen", "Fuentes"].map((h) => el("th", { texto: h })))),
        el("tbody", {}, filas)));
    }
    const pag = vaciar($("paginacion"));
    const anterior = el("button", { type: "button", texto: "Anteriores" });
    const siguiente = el("button", { type: "button", texto: "Siguientes" });
    anterior.disabled = estado.pagina === 0;
    siguiente.disabled = estado.pagina >= paginas - 1;
    anterior.addEventListener("click", () => { estado.pagina -= 1; dibujarTabla(eventos); $("tabla-eventos").scrollIntoView({ block: "start" }); });
    siguiente.addEventListener("click", () => { estado.pagina += 1; dibujarTabla(eventos); $("tabla-eventos").scrollIntoView({ block: "start" }); });
    pag.append(el("span", { texto: `${plural(filtrados.length, "siniestro", "siniestros")} · página ${estado.pagina + 1} de ${paginas}` }),
      el("span", { style: "display:flex;gap:8px" }, anterior, siguiente));
  }

  function opcionesTabla() {
    const provincias = $("f-provincia");
    for (const p of estado.datos.meta.provincias.slice().sort((a, b) => a.nombre.localeCompare(b.nombre, "es"))) {
      provincias.append(el("option", { value: p.id, texto: p.nombre }));
    }
    for (const [k, v] of Object.entries(ETIQUETAS.via)) if (k !== "desconocida") $("f-via").append(el("option", { value: k, texto: v }));
    for (const [k, v] of Object.entries(ETIQUETAS.tipo)) $("f-tipo").append(el("option", { value: k, texto: v }));
    for (const [k, v] of Object.entries(ETIQUETAS.vehiculo)) $("f-vehiculo").append(el("option", { value: k, texto: v }));
    for (const [k, v] of Object.entries(ETIQUETAS.subtipo)) $("f-contexto").append(el("option", { value: k, texto: v }));
  }

  // ------------------------------------------------------------------ contexto vial
  function dibujarContexto() {
    const lista = vaciar($("lista-contexto"));
    const subtipo = $("f-contexto").value;
    const items = estado.datos.contexto.filter((c) => c.fecha >= estado.desde && c.fecha <= estado.hasta
      && (!estado.provincia || c.provincia === estado.provincia || c.ambito === "nacional")
      && (!subtipo || (c.subtipo || "otro") === subtipo));
    if (!items.length) {
      lista.append(el("li", { clase: "nota", texto: subtipo ? "Sin novedades de ese tipo en el período elegido." : "Sin novedades de contexto vial en el período elegido." }));
      return;
    }
    for (const c of items.slice(0, estado.contextoVisibles)) {
      const prov = estado.provincias[c.provincia];
      const donde = prov ? prov.nombre : (c.ambito === "nacional" ? "Nacional" : "");
      lista.append(el("li", {},
        el("div", {}, el("span", { clase: "capsula", texto: ETIQUETAS.subtipo[c.subtipo] || "Contexto" })),
        el("div", { style: "margin-top:6px", texto: c.resumen || "" }),
        c.dato_clave ? el("div", { clase: "dato", texto: c.dato_clave }) : null,
        el("div", { clase: "meta" }, [fechaCorta(c.fecha), donde, c.organismo].filter(Boolean).join(" · "), " · ",
          c.fuentes.map((f, i) => [i ? ", " : "", enlace(f.url, f.medio || "Nota")]))));
    }
    const faltan = items.length - estado.contextoVisibles;
    if (faltan > 0) {
      const mas = el("button", { type: "button", texto: `Ver ${NUM.format(Math.min(faltan, CONTEXTO_POR_TANDA))} más (${faltan === 1 ? "queda 1 novedad" : `quedan ${NUM.format(faltan)} novedades`})` });
      mas.addEventListener("click", () => { estado.contextoVisibles += CONTEXTO_POR_TANDA; dibujarContexto(); });
      lista.append(el("li", { clase: "nota" }, mas));
    }
  }

  // ------------------------------------------------------------------ histórico
  function dibujarHistorico() {
    const dias = estado.datos.serie_diaria.dias;
    const corte = estado.datos.meta.corte;
    const semanas = {};
    for (const [dia, v] of Object.entries(dias)) {
      if (dia > corte) continue;
      const lunes = sumarDias(dia, -diaSemana(dia));
      const s = semanas[lunes] || (semanas[lunes] = { siniestros: 0, fallecidos: 0, heridos: 0 });
      const [n, m, h, nt, mt, ht] = filaDia(v);
      s.siniestros += n - (estado.incluirTitulos ? 0 : nt);
      s.fallecidos += m - (estado.incluirTitulos ? 0 : mt);
      s.heridos += h - (estado.incluirTitulos ? 0 : (ht || 0));
    }
    const claves = Object.keys(semanas).sort();
    const enCurso = (lunes) => sumarDias(lunes, 6) > corte;
    // Semanas que empezaron antes del inicio del registro: incompletas, no se compara contra ellas
    const inicio = estado.datos.meta.inicio_cobertura || Object.keys(dias).sort()[0];
    const incompleta = (lunes) => !inicio || lunes < inicio;
    const marca = (k) => (!incompleta(k) ? (enCurso(k) ? " (en curso)" : "")
      : sumarDias(k, 6) < inicio ? " (anterior al inicio del registro)" : " (el registro empezó durante esta semana)");
    graficoBarras("g-semanas", claves.map((k) => fechaCorta(k)), claves.map((k) => semanas[k].siniestros), {
      colores: claves.map((k) => (incompleta(k) ? C.previo : enCurso(k) ? C.carga : C.rojo)),
      bordes: claves.map((k) => (enCurso(k) && !incompleta(k) ? 2 : 0)), unidad: "siniestros", valoresVisibles: claves.length <= 20,
      titulos: claves.map((k) => `Semana del ${fechaCorta(k)} al ${fechaCorta(sumarDias(k, 6))}${marca(k)}`),
    });
    const filas = claves.slice().reverse().map((k, i, arr) => {
      const s = semanas[k];
      const anterior = semanas[sumarDias(k, -7)];
      const anioAnterior = semanas[sumarDias(k, -364)];
      let variacion = "Sin datos";
      if (enCurso(k)) {
        variacion = "Semana en curso";   // incompleta: contra una semana entera siempre daría "menos"
      } else if (anterior && anterior.siniestros && !incompleta(sumarDias(k, -7)) && !incompleta(k)) {
        const dif = s.siniestros - anterior.siniestros;
        const signo = dif > 0 ? "+" : dif < 0 ? "-" : "";
        variacion = anterior.siniestros >= BASE_MINIMA_PCT
          ? `${signo}${DEC1.format(Math.abs((100 * dif) / anterior.siniestros))}%` : `${signo}${NUM.format(Math.abs(dif))}`;
      }
      return [`Del ${fechaCorta(k)} al ${fechaCorta(sumarDias(k, 6))}${marca(k)}`,
        NUM.format(s.siniestros), NUM.format(s.fallecidos), NUM.format(s.heridos), variacion,
        anioAnterior ? NUM.format(anioAnterior.siniestros) : "Sin datos"];
    });
    tablaSimple($("tabla-semanas"), ["Semana", "Siniestros", "Fallecidos", "Heridos", "Frente a la semana anterior", "Misma semana del año anterior"],
      filas, [1, 2, 3, 4, 5]);
  }

  // ------------------------------------------------------------------ armado general
  function dibujarTodo() {
    const eventos = eventosDelRango();
    dibujarIndicadores();
    dibujarSeries();
    const filas = dibujarMapa(eventos);
    dibujarDistribuciones(eventos);
    dibujarRankings(eventos, filas);
    dibujarTabla(eventos);
    dibujarContexto();
    if (!$("vista-historico").hidden) dibujarHistorico();
  }

  function elegirProvincia(id) {
    estado.provincia = id;
    $("f-provincia").value = id;
    estado.pagina = 0;
    estado.contextoVisibles = CONTEXTO_POR_TANDA;
    const prov = estado.provincias[id];
    $("aviso-historico").textContent = prov ? `Se muestran solo los siniestros de ${prov.nombre} (filtro de la pestaña "Esta semana").` : "";
    dibujarTodo();
  }

  function fijarRango(valor) {
    const corte = estado.datos.meta.corte;
    const desdeInput = $("desde"), hastaInput = $("hasta");
    if (valor === "personalizado") {
      $("campo-desde").hidden = false; $("campo-hasta").hidden = false;
      // dentro de los límites del calendario (al tipear el año a mano se pueden pasar) y en orden
      const acotar = (v, actual) => {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(v || "")) return actual;
        return v < desdeInput.min ? desdeInput.min : v > desdeInput.max ? desdeInput.max : v;
      };
      estado.desde = acotar(desdeInput.value, estado.desde);
      estado.hasta = acotar(hastaInput.value, estado.hasta);
      if (estado.desde > estado.hasta) [estado.desde, estado.hasta] = [estado.hasta, estado.desde];
      desdeInput.value = estado.desde; hastaInput.value = estado.hasta;
    } else {
      $("campo-desde").hidden = true; $("campo-hasta").hidden = true;
      estado.hasta = corte;
      estado.desde = sumarDias(corte, -(Number(valor) - 1));
      desdeInput.value = estado.desde; hastaInput.value = estado.hasta;
    }
  }

  function mostrarVista(nombre) {
    for (const v of ["semana", "historico", "metodologia"]) {
      $(`vista-${v}`).hidden = v !== nombre;
      $(`tab-${v}`).setAttribute("aria-selected", String(v === nombre));
      $(`tab-${v}`).tabIndex = v === nombre ? 0 : -1;
    }
    if (nombre === "historico") dibujarHistorico();
    if (nombre === "semana" && estado.mapa) setTimeout(() => estado.mapa.invalidateSize(), 0);
    if (location.hash !== `#${nombre}`) history.replaceState(null, "", nombre === "semana" ? location.pathname : `#${nombre}`);
  }

  function conectarControles() {
    $("rango").addEventListener("change", (ev) => { fijarRango(ev.target.value); estado.pagina = 0; dibujarTodo(); });
    for (const id of ["desde", "hasta"]) $(id).addEventListener("change", () => { fijarRango("personalizado"); estado.pagina = 0; dibujarTodo(); });
    $("incluir-titulos").addEventListener("change", (ev) => { estado.incluirTitulos = ev.target.checked; estado.pagina = 0; dibujarTodo(); });
    $("f-contexto").addEventListener("change", () => { estado.contextoVisibles = CONTEXTO_POR_TANDA; dibujarContexto(); });
    $("f-provincia").addEventListener("change", (ev) => elegirProvincia(ev.target.value));
    for (const id of ["f-tipo", "f-vehiculo", "f-fatales", "f-via", "f-fuentes"]) {
      $(id).addEventListener("change", () => { estado.pagina = 0; dibujarTabla(eventosDelRango()); });
    }
    const pestanas = ["semana", "historico", "metodologia"];
    pestanas.forEach((v, i) => {
      const boton = $(`tab-${v}`);
      boton.addEventListener("click", () => mostrarVista(v));
      boton.addEventListener("keydown", (ev) => {
        if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
        const siguiente = pestanas[(i + (ev.key === "ArrowRight" ? 1 : pestanas.length - 1)) % pestanas.length];
        mostrarVista(siguiente);
        $(`tab-${siguiente}`).focus();
      });
    });
  }

  function textosFijos() {
    const meta = estado.datos.meta;
    const generado = new Date(meta.generado);
    const hora = generado.toLocaleString("es-AR", { timeZone: "America/Argentina/Buenos_Aires", day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
    const actualizado = vaciar($("actualizado"));
    actualizado.append("Actualizado: ", el("strong", { texto: hora }), el("br"), `Datos hasta el ${fechaCompleta(meta.corte)}`);
    $("aviso-demo").hidden = !meta.demo;
    $("n-medios").textContent = `${NUM.format(meta.medios_activos)}`;
    const oficiales = vaciar($("lista-oficiales"));
    for (const o of meta.oficiales || []) oficiales.append(el("li", {}, enlace(o.url, o.nombre)));
    const rango = $("desde"), hasta = $("hasta");
    rango.max = hasta.max = sumarDias(meta.corte, 1);
    rango.min = hasta.min = Object.keys(estado.datos.serie_diaria.dias).sort()[0] || meta.inicio_cobertura || meta.corte;
  }

  async function iniciar() {
    try {
      estado.datos = await cargar();
    } catch (err) {
      $("actualizado").textContent = "No se pudieron cargar los datos.";
      const aviso = el("p", { clase: "caja", texto: "No se pudieron cargar los datos del tablero. Si estás abriendo el archivo directamente desde la computadora, usá el comando `python -m radar_vial demo`, que lo sirve por http." });
      document.querySelector("main").prepend(aviso);
      console.error(err);
      return;
    }
    estado.provincias = Object.fromEntries(estado.datos.meta.provincias.map((p) => [p.id, p]));
    if (window.Chart) configurarChart();
    textosFijos();
    opcionesTabla();
    fijarRango("7");
    conectarControles();
    dibujarTodo();
    const vistaDelEnlace = () => {
      const v = location.hash.replace("#", "");
      mostrarVista(["historico", "metodologia"].includes(v) ? v : "semana");
    };
    window.addEventListener("hashchange", vistaDelEnlace);
    if (location.hash) vistaDelEnlace();
  }

  document.addEventListener("DOMContentLoaded", iniciar);
})();
