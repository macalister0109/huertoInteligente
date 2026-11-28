/* Detalle de cama: gráficos (24 h, 7 o 30 días) con la franja ideal sombreada,
   resumen por día y descarga CSV (el formulario funciona sin JavaScript). */
"use strict";

(() => {
  const H = Huerto;
  const camaId = document.body.dataset.camaId;
  const RECARGA_MS = 60_000;
  const COLORES = { suelo: "#0f2c59", temp: "#c4570c", luz: "#a87a00", ideal: "rgba(22, 163, 74, 0.14)", borde: "rgba(21, 128, 61, 0.7)", exterior: "#5b6066", riego: "#0b7fab", recta: "#7b2cbf" };
  const graficos = {};
  let horas = 24;
  // Clima exterior (opcional): si no hay, el gráfico de temperatura queda igual
  let serieExterior = [];
  let opcionesTemp = null;
  // Humedad del suelo: riegos detectados y recta de tendencia del tramo actual
  let opcionesSuelo = null;
  let riegos = [];
  let recta = null;
  const TEXTO_PERIODO = { 24: "Últimas 24 horas", 168: "Últimos 7 días", 720: "Últimos 30 días" };

  // En períodos largos el eje muestra el día; en 24 h, la hora
  const etiquetaEje = (v) => {
    const iso = new Date(v).toISOString();
    return horas > 24 ? H.dia(iso) : H.hora(iso);
  };

  // Misma tipografía y colores que el resto del sitio (huerto.css / landing.css)
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 15;
  Chart.defaults.color = "#0f172a";
  Chart.defaults.borderColor = "#e2e8f0";
  Chart.defaults.animation = false;

  function lineaHorizontal(etiqueta, y, desde, hasta, extra = {}) {
    return {
      label: etiqueta, data: [{ x: desde, y }, { x: hasta, y }],
      borderColor: COLORES.borde, borderWidth: 2, borderDash: [8, 5], pointRadius: 0, fill: false, ...extra,
    };
  }

  function conjuntos({ datos, clave, etiqueta, color, minimo, maximo, desde, hasta, referencia, exterior, extras }) {
    const lista = [];
    if (minimo !== null && maximo !== null) {
      // Franja ideal: la línea del máximo se rellena hasta la del mínimo
      lista.push(lineaHorizontal("Rango ideal", maximo, desde, hasta, { fill: "+1", backgroundColor: COLORES.ideal }));
      lista.push(lineaHorizontal("_min", minimo, desde, hasta));
    } else if (minimo !== null) {
      lista.push(lineaHorizontal("Mínimo ideal", minimo, desde, hasta));
    } else if (maximo !== null) {
      lista.push(lineaHorizontal("Máximo ideal", maximo, desde, hasta));
    }
    if (referencia) lista.push(lineaHorizontal(referencia.etiqueta, referencia.valor, desde, hasta, { borderColor: COLORES.luz }));
    if (exterior && exterior.length) {
      lista.push({
        label: "Afuera (zona)", data: exterior, esSerie: true,
        borderColor: COLORES.exterior, backgroundColor: COLORES.exterior, borderWidth: 2,
        borderDash: [3, 4], pointRadius: 2, spanGaps: false,
      });
    }
    lista.push({
      label: etiqueta, data: datos.map((p) => ({ x: p.t, y: p[clave] })), esSerie: true, order: 1,
      borderColor: color, backgroundColor: color, borderWidth: 3, pointRadius: 0,
      spanGaps: false, tension: 0.2,
    });
    // Chart.js dibuja encima los de «order» menor: riegos y recta sobre la línea
    (extras || []).forEach((d) => lista.push({ order: 0, ...d }));
    return lista;
  }

  function dibujar(id, opciones, unidad) {
    const datasets = conjuntos(opciones);
    if (graficos[id]) {
      graficos[id].data.datasets = datasets;
      graficos[id].options.scales.x.min = opciones.desde;
      graficos[id].options.scales.x.max = opciones.hasta;
      graficos[id].options.scales.x.ticks.callback = etiquetaEje;
      graficos[id].update("none");
      return;
    }
    graficos[id] = new Chart(document.getElementById(id), {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: {
            type: "linear", min: opciones.desde, max: opciones.hasta,
            ticks: { maxTicksLimit: 7, callback: etiquetaEje },
          },
          y: { ticks: { callback: (v) => `${H.entero(v)} ${unidad}` } },
        },
        plugins: {
          legend: { labels: { filter: (item) => !item.text.startsWith("_") } },
          tooltip: {
            filter: (item) => item.dataset.esSerie === true,
            callbacks: {
              title: (items) => (items.length ? H.hora(new Date(items[0].parsed.x).toISOString()) : ""),
              label: (item) => `${item.dataset.label}: ${H.entero(item.parsed.y)} ${unidad}`,
            },
          },
        },
      },
    });
  }

  async function cargar() {
    let datos;
    try {
      datos = await H.obtenerJson(`/api/camas/${camaId}/serie?horas=${horas}`);
      H.avisoConexion("");
    } catch (e) {
      H.avisoConexion("Sin conexión con el equipo central. Reintentando…");
      return;
    }
    const desde = Date.parse(datos.desde);
    const hasta = Date.parse(datos.hasta);
    const r = datos.rango;
    const base = { datos: datos.puntos, desde, hasta };

    opcionesSuelo = { ...base, clave: "suelo", etiqueta: "Humedad del suelo", color: COLORES.suelo,
      minimo: r.humedad_min, maximo: r.humedad_max };
    riegos = datos.riegos || [];
    dibujarSuelo();
    opcionesTemp = { ...base, clave: "temp", etiqueta: "Temperatura", color: COLORES.temp,
      minimo: r.temp_min, maximo: r.temp_max };
    dibujar("grafico-temp", { ...opcionesTemp, exterior: serieExterior }, "°C");
    dibujar("grafico-luz", { ...base, clave: "lux", etiqueta: "Luz", color: COLORES.luz,
      minimo: null, maximo: null,
      referencia: { etiqueta: `Luz directa (sobre ${H.entero(datos.umbral_luz)} lux)`, valor: datos.umbral_luz } }, "lux");

    H.dibujarAvisos(document.getElementById("avisos-cama"), datos.alertas,
      "Sin avisos en los últimos 7 días.", false);
  }

  // ------------------------------------------------- tendencia (RF-15)

  function extrasSuelo() {
    const extras = [];
    const visibles = riegos.filter((e) => e.fin && e.despues !== null);
    if (visibles.length) {
      extras.push({
        label: "Riego detectado", data: visibles.map((e) => ({ x: Date.parse(e.fin), y: e.despues })),
        showLine: false, pointStyle: "triangle", pointRadius: 9, pointHoverRadius: 11, esSerie: true,
        borderColor: COLORES.riego, backgroundColor: COLORES.riego,
      });
    }
    if (recta) {
      extras.push({
        label: "Tendencia (desde el último riego)", data: recta.map((p) => ({ x: Date.parse(p.t), y: p.valor })),
        borderColor: COLORES.recta, borderWidth: 4, borderDash: [10, 6], pointRadius: 0, fill: false, esSerie: true,
      });
    }
    return extras;
  }

  function dibujarSuelo() {
    if (!opcionesSuelo) return;
    // La recta puede llegar al futuro (hasta el cruce): el eje se estira para mostrarla
    const hasta = recta ? Math.max(opcionesSuelo.hasta, Date.parse(recta[1].t)) : opcionesSuelo.hasta;
    dibujar("grafico-suelo", { ...opcionesSuelo, hasta, extras: extrasSuelo() }, "%");
  }

  async function cargarTendencia() {
    let datos;
    try {
      datos = await H.obtenerJson(`/api/camas/${camaId}/tendencia`);
    } catch (e) {
      return;   // sin tendencia: la página sigue igual
    }
    if (datos.error) return;
    const p = datos.prediccion;
    const s6 = datos.suelo["6h"];
    document.getElementById("tendencia-etiqueta").textContent = s6.texto;
    document.getElementById("tendencia-estimacion").textContent = p ? `${p.texto}.` : "";
    const detalle = [];
    if (p && p.n_puntos) {
      detalle.push(`Recta calculada con ${p.n_puntos} lecturas desde ${H.hora(p.desde)}`);
      if (p.r2 !== null) detalle.push(`R² = ${H.decimal(p.r2)}`);
    }
    if (p && p.motivo && p.estado === "sin_tendencia") detalle.push(`motivo: ${p.motivo}`);
    if (datos.alerta_preventiva_activa) detalle.push("aviso preventivo activado");
    document.getElementById("tendencia-detalle").textContent = detalle.join(" · ");
    const amplitud = (datos.amplitud.ayer || datos.amplitud.hoy || {}).texto;
    document.getElementById("tendencia-amplitud").textContent = amplitud || "";
    document.getElementById("panel-tendencia").hidden = false;
    // Sin tendencia clara no se dibuja la recta: sugeriría algo que el sistema descartó
    const valida = p && ["estimacion", "fuera_horizonte", "bajo_minimo"].includes(p.estado);
    recta = valida && p.recta && p.recta.length === 2 ? p.recta : null;
    dibujarSuelo();
  }

  // ------------------------------------------- comparación con el exterior

  function fila(variable, cama, afuera, diferencia) {
    return H.el("tr", {},
      H.el("th", { scope: "row" }, variable),
      H.el("td", {}, cama ?? "—"), H.el("td", {}, afuera ?? "—"),
      H.el("td", {}, diferencia ?? "—"));
  }

  function dibujarComparacion(datos) {
    const seccion = document.getElementById("comparacion-exterior");
    const c = datos.comparacion;
    const l = datos.lectura;
    const notas = [];
    let filas = [];
    if (!c) {
      notas.push(H.el("p", { class: "vacio" }, "Sin dato del clima exterior para la hora de la última medición."));
    } else {
      const t = c.temperatura;
      const h = c.humedad_aire;
      filas = [
        fila("Temperatura", t ? `${H.entero(t.sensor)} °C` : null, t ? `${H.entero(t.externo)} °C` : null,
          t ? H.el("strong", {}, t.texto) : null),
        fila("Humedad del aire", h ? `${H.entero(h.sensor)} %` : null, h ? `${H.entero(h.externo)} %` : null,
          h ? H.el("strong", {}, h.texto) : null),
        // Suelo: SIN diferencia. Son escalas distintas (sonda calibrada vs. % volumétrico modelado)
        fila("Humedad del suelo",
          l && l.suelo_prom !== null ? `${H.entero(l.suelo_prom)} % (escala de la sonda)` : null,
          c.suelo_zona, "No se comparan: son escalas distintas"),
      ];
      if (c.et0) notas.push(H.el("p", {}, `${c.et0}.`));
      c.sugerencias.forEach((s) => notas.push(H.el("p", { class: "sugerencia" }, s)));
      notas.push(H.el("p", { class: "detalle-ayuda" },
        `Dato de la zona de las ${H.hora(c.referencia_observada_en)} (${c.fuente_nombre || c.fuente}), comparado con la medición de las ${H.hora(c.lectura_medida_en)}.`));
    }
    document.getElementById("comparacion-filas").replaceChildren(...filas);
    document.getElementById("comparacion-notas").replaceChildren(...notas);
    seccion.hidden = false;
  }

  async function cargarClima() {
    let datos;
    try {
      datos = await H.obtenerJson(`/api/camas/${camaId}/clima?horas=${horas}`);
    } catch (e) {
      return;   // sin clima: la página sigue igual
    }
    dibujarComparacion(datos);
    serieExterior = datos.serie.map((p) => ({ x: p.t, y: p.temp }));
    if (opcionesTemp) dibujar("grafico-temp", { ...opcionesTemp, exterior: serieExterior }, "°C");
  }

  // ------------------------------------------------------------ resumen por día
  function celda(v, unidad) {
    if (!v) return H.el("td", { class: "sin-dato" }, "—");
    return H.el("td", {},
      H.el("strong", {}, `${H.entero(v.prom)} ${unidad}`),
      H.el("span", { class: "rango-dia" }, ` (${H.entero(v.min)} a ${H.entero(v.max)})`));
  }

  async function cargarResumen() {
    const cuerpo = document.getElementById("resumen-diario");
    let datos;
    try {
      datos = await H.obtenerJson(`/api/camas/${camaId}/diario?dias=30`);
    } catch (e) {
      return;   // el aviso de conexión ya lo muestra cargar()
    }
    const conDatos = datos.dias.filter((d) => d.lecturas > 0);
    if (!conDatos.length) {
      cuerpo.replaceChildren(H.el("tr", {}, H.el("td", { colspan: 5, class: "vacio" }, "Aún no hay lecturas.")));
      return;
    }
    // Desde el primer día con datos: no se listan los días antes de instalar el nodo
    const primero = datos.dias.indexOf(conDatos[conDatos.length - 1]);
    cuerpo.replaceChildren(...datos.dias.slice(0, primero + 1).map((d) =>
      H.el("tr", { class: d.lecturas ? null : "dia-sin-datos" },
        H.el("th", { scope: "row" }, H.dia(`${d.fecha}T12:00:00`)),
        celda(d.suelo, "%"), celda(d.temp, "°C"), celda(d.hum_aire, "%"),
        H.el("td", {}, d.lecturas ? H.entero(d.lecturas) : "Sin datos"))));
  }

  // ------------------------------------------------------------ período
  document.querySelectorAll(".boton-periodo").forEach((boton) => {
    boton.addEventListener("click", () => {
      horas = Number(boton.dataset.horas);
      document.querySelectorAll(".boton-periodo").forEach((b) =>
        b.setAttribute("aria-pressed", String(b === boton)));
      document.getElementById("detalle-ayuda").textContent =
        `${TEXTO_PERIODO[horas]}. La franja verde es el rango ideal.`;
      cargar();
      cargarClima();
      cargarTendencia();
    });
  });

  cargar();
  cargarResumen();
  setTimeout(cargarClima, 0);      // aparte: nunca retrasa los gráficos de la cama
  setTimeout(cargarTendencia, 0);
  setInterval(cargarTendencia, 5 * RECARGA_MS);
  setInterval(cargar, RECARGA_MS);
  setInterval(cargarClima, 5 * RECARGA_MS);
  setInterval(cargarResumen, 10 * RECARGA_MS);
})();
